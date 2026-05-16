"""
Attachment Deduplication Engine - Content-addressable storage with hash-based keys

Features:
- SHA256 content addressing
- Reference counting for shared files
- Hard link optimization
- Deduplication statistics
"""

import os
import hashlib
import threading
import time
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple
from collections import defaultdict

logger = logging.getLogger("storage.dedup")


class DeduplicationError(Exception):
    """Deduplication errors"""
    pass


@dataclass
class DedupEntry:
    """Entry in deduplication index"""
    content_hash: str
    storage_path: str
    size: int
    reference_count: int = 0
    first_seen: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)


@dataclass
class DedupStats:
    """Deduplication statistics"""
    total_files: int = 0
    unique_files: int = 0
    total_size_bytes: int = 0
    unique_size_bytes: int = 0
    saved_bytes: int = 0
    hard_links_created: int = 0
    files_by_hash: Dict[str, int] = field(default_factory=dict)


class AttachmentDeduplicationEngine:
    """
    Content-addressable storage engine with SHA256 hashing.
    
    Storage structure:
    /storage_root/
        /content/          # Actual file content (hash-named)
        /index/            # Dedup index JSON
        /references/       # Reference tracking
    """
    
    def __init__(
        self,
        storage_root: str = "./data/storage/dedup",
        enable_hard_links: bool = True,
        enable_reference_counting: bool = True,
        index_save_interval: int = 100
    ):
        self.storage_root = Path(storage_root)
        self.enable_hard_links = enable_hard_links
        self.enable_reference_counting = enable_reference_counting
        self.index_save_interval = index_save_interval
        
        self._ensure_directories()
        
        self._index: Dict[str, DedupEntry] = {}
        self._lock = threading.RLock()
        
        self._operation_count = 0
        self._load_index()
        
        logger.info(f"Deduplication engine initialized at {storage_root}")
    
    def _ensure_directories(self):
        """Create storage directory structure"""
        dirs = ["content", "index", "references"]
        for d in dirs:
            (self.storage_root / d).mkdir(parents=True, exist_ok=True)
    
    def _content_path(self, content_hash: str) -> Path:
        """Get path for content hash"""
        return self.storage_root / "content" / f"{content_hash}.bin"
    
    def compute_hash(self, data: bytes) -> str:
        """Compute SHA256 hash of data"""
        return hashlib.sha256(data).hexdigest()
    
    def compute_hash_file(self, file_path: Path) -> str:
        """Compute SHA256 hash of file"""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    
    def store(
        self,
        data: bytes,
        reference_id: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Store data with deduplication.
        
        Returns:
            Tuple of (content_hash, storage_path)
        """
        with self._lock:
            content_hash = self.compute_hash(data)
            content_path = self._content_path(content_hash)
            
            is_new = False
            
            if content_path.exists():
                logger.debug(f"Content {content_hash[:8]}... already exists")
            else:
                content_path.parent.mkdir(parents=True, exist_ok=True)
                with open(content_path, "wb") as f:
                    f.write(data)
                is_new = True
                logger.info(f"Stored new content: {content_hash[:8]}...")
            
            if self.enable_reference_counting:
                if content_hash not in self._index:
                    self._index[content_hash] = DedupEntry(
                        content_hash=content_hash,
                        storage_path=str(content_path),
                        size=len(data),
                        reference_count=1
                    )
                else:
                    self._index[content_hash].reference_count += 1
                    self._index[content_hash].last_accessed = time.time()
            
            self._operation_count += 1
            
            if self._operation_count % self.index_save_interval == 0:
                self._save_index()
            
            return content_hash, str(content_path)
    
    def store_file(
        self,
        source_path: Path,
        reference_id: Optional[str] = None
    ) -> Tuple[str, str]:
        """Store file with deduplication"""
        content_hash = self.compute_hash_file(source_path)
        content_path = self._content_path(content_hash)
        
        with self._lock:
            if not content_path.exists():
                import shutil
                content_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, content_path)
                logger.info(f"Stored file: {content_hash[:8]}...")
            
            if self.enable_reference_counting:
                file_size = source_path.stat().st_size
                if content_hash not in self._index:
                    self._index[content_hash] = DedupEntry(
                        content_hash=content_hash,
                        storage_path=str(content_path),
                        size=file_size,
                        reference_count=1
                    )
                else:
                    self._index[content_hash].reference_count += 1
                    self._index[content_hash].last_accessed = time.time()
                
                self._save_index()
            
            return content_hash, str(content_path)
    
    def retrieve(self, content_hash: str) -> Optional[bytes]:
        """Retrieve content by hash"""
        with self._lock:
            content_path = self._content_path(content_hash)
            
            if not content_path.exists():
                logger.warning(f"Content not found: {content_hash[:8]}...")
                return None
            
            try:
                with open(content_path, "rb") as f:
                    data = f.read()
                
                if content_hash in self._index:
                    self._index[content_hash].last_accessed = time.time()
                
                return data
            except Exception as e:
                logger.error(f"Failed to retrieve {content_hash[:8]}...: {e}")
                return None
    
    def has_content(self, content_hash: str) -> bool:
        """Check if content exists"""
        return self._content_path(content_hash).exists()
    
    def release_reference(self, content_hash: str) -> bool:
        """Release a reference to content, remove if last reference"""
        with self._lock:
            if content_hash not in self._index:
                return False
            
            entry = self._index[content_hash]
            entry.reference_count -= 1
            
            if entry.reference_count <= 0:
                content_path = self._content_path(content_hash)
                try:
                    if content_path.exists():
                        content_path.unlink()
                    del self._index[content_hash]
                    logger.info(f"Removed orphaned content: {content_hash[:8]}...")
                    self._save_index()
                    return True
                except Exception as e:
                    logger.error(f"Failed to remove content: {e}")
                    return False
            
            return True
    
    def get_stats(self) -> DedupStats:
        """Get deduplication statistics"""
        with self._lock:
            total_files = sum(e.reference_count for e in self._index.values())
            unique_files = len(self._index)
            total_size = sum(e.reference_count * e.size for e in self._index.values())
            unique_size = sum(e.size for e in self._index.values())
            
            return DedupStats(
                total_files=total_files,
                unique_files=unique_files,
                total_size_bytes=total_size,
                unique_size_bytes=unique_size,
                saved_bytes=total_size - unique_size,
                files_by_hash={h: e.reference_count for h, e in self._index.items()}
            )
    
    def create_hard_link(self, content_hash: str, link_path: Path) -> bool:
        """Create hard link to content (same filesystem only)"""
        if not self.enable_hard_links:
            return False
        
        content_path = self._content_path(content_hash)
        
        if not content_path.exists():
            return False
        
        try:
            link_path.parent.mkdir(parents=True, exist_ok=True)
            if link_path.exists():
                link_path.unlink()
            os.link(content_path, link_path)
            logger.debug(f"Created hard link: {link_path.name}")
            return True
        except Exception as e:
            logger.error(f"Failed to create hard link: {e}")
            return False
    
    def find_duplicates(self) -> Dict[str, List[str]]:
        """Find files with same content hash"""
        with self._lock:
            duplicates = {}
            for content_hash, entry in self._index.items():
                if entry.reference_count > 1:
                    duplicates[content_hash] = {
                        "path": entry.storage_path,
                        "count": entry.reference_count,
                        "size": entry.size
                    }
            return duplicates
    
    def cleanup_empty_content(self) -> int:
        """Remove content files with no index entry"""
        with self._lock:
            cleaned = 0
            content_dir = self.storage_root / "content"
            
            for content_file in content_dir.glob("*.bin"):
                content_hash = content_file.stem
                if content_hash not in self._index:
                    try:
                        content_file.unlink()
                        cleaned += 1
                    except Exception as e:
                        logger.error(f"Failed to clean {content_file.name}: {e}")
            
            if cleaned > 0:
                logger.info(f"Cleaned {cleaned} orphaned content files")
            
            return cleaned
    
    def _load_index(self):
        """Load dedup index from disk"""
        index_file = self.storage_root / "index" / "dedup_index.json"
        
        if index_file.exists():
            try:
                import json
                with open(index_file, "r") as f:
                    data = json.load(f)
                    for item in data.get("entries", []):
                        entry = DedupEntry(**item)
                        self._index[entry.content_hash] = entry
                logger.info(f"Loaded {len(self._index)} dedup entries")
            except Exception as e:
                logger.error(f"Failed to load dedup index: {e}")
    
    def _save_index(self):
        """Save dedup index to disk"""
        import json
        index_file = self.storage_root / "index" / "dedup_index.json"
        
        try:
            data = {
                "entries": [
                    {
                        "content_hash": e.content_hash,
                        "storage_path": e.storage_path,
                        "size": e.size,
                        "reference_count": e.reference_count,
                        "first_seen": e.first_seen,
                        "last_accessed": e.last_accessed
                    }
                    for e in self._index.values()
                ],
                "updated_at": time.time()
            }
            
            with open(index_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save dedup index: {e}")


deduplication_engine = AttachmentDeduplicationEngine()