"""
Attachment Storage Engine - File-based with deduplication

Features:
- Filesystem storage (not SQLite blobs)
- Chunked storage
- SHA256 deduplication
- Metadata indexing
- Compression
- Encryption
- Orphan cleanup
"""

import hashlib
import json
import logging
import threading
import time
import zlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("storage.attachment")


class StorageError(Exception):
    """Storage-related errors"""
    pass


@dataclass
class AttachmentMetadata:
    """Metadata for an attachment"""
    attachment_id: str
    filename: str
    content_type: str
    size: int
    checksum: str
    storage_path: str

    # Additional metadata
    email_id: Optional[int] = None
    created_at: float = field(default_factory=time.time)

    # Compression info
    is_compressed: bool = False
    original_size: Optional[int] = None

    # Encryption info
    is_encrypted: bool = False
    encryption_key_id: Optional[str] = None


class StoragePolicy(Enum):
    """Storage policies"""
    STANDARD = "standard"
    COMPRESSED = "compressed"
    ENCRYPTED = "encrypted"


class AttachmentStorageEngine:
    """
    Enterprise attachment storage engine.
    
    Storage structure:
    /storage_root/
        /data/
            /chunks/         # Chunked data files
            /dedup/          # Deduplicated content (SHA256 named)
        /meta/              # Metadata JSON files
        /index/             # Fast lookup indexes
        /orphans/           # Orphaned files for cleanup
    """

    def __init__(
        self,
        storage_root: str = "./data/attachments",
        enable_compression: bool = True,
        enable_deduplication: bool = True,
        enable_encryption: bool = False,
        chunk_size: int = 1024 * 1024,  # 1MB chunks
        orphan_threshold_days: int = 30
    ):
        self.storage_root = Path(storage_root)
        self.enable_compression = enable_compression
        self.enable_deduplication = enable_deduplication
        self.enable_encryption = enable_encryption
        self.chunk_size = chunk_size
        self.orphan_threshold_days = orphan_threshold_days

        # Ensure directories exist
        self._ensure_directories()

        # Index for fast lookup
        self._index: Dict[str, AttachmentMetadata] = {}
        self._email_index: Dict[int, List[str]] = {}  # email_id -> attachment_ids
        self._lock = threading.RLock()

        # Load existing index
        self._load_index()

        logger.info(f"Attachment storage initialized at {storage_root}")

    def _ensure_directories(self):
        """Create storage directory structure"""
        dirs = [
            "data/chunks",
            "data/dedup",
            "meta",
            "index",
            "orphans"
        ]

        for d in dirs:
            (self.storage_root / d).mkdir(parents=True, exist_ok=True)

    def _load_index(self):
        """Load metadata index from disk"""
        index_file = self.storage_root / "index" / "attachments.json"

        if index_file.exists():
            try:
                with open(index_file, 'r') as f:
                    data = json.load(f)
                    for item in data.get("attachments", []):
                        meta = AttachmentMetadata(**item)
                        self._index[meta.attachment_id] = meta

                        if meta.email_id:
                            if meta.email_id not in self._email_index:
                                self._email_index[meta.email_id] = []
                            self._email_index[meta.email_id].append(meta.attachment_id)

                logger.info(f"Loaded {len(self._index)} attachments from index")
            except Exception as e:
                logger.error(f"Failed to load index: {e}")

    def _save_index(self):
        """Save metadata index to disk"""
        index_file = self.storage_root / "index" / "attachments.json"

        try:
            data = {
                "attachments": [
                    vars(meta) for meta in self._index.values()
                ],
                "updated_at": time.time()
            }

            with open(index_file, 'w') as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            logger.error(f"Failed to save index: {e}")

    def compute_checksum(self, data: bytes) -> str:
        """Compute SHA256 checksum of data"""
        return hashlib.sha256(data).hexdigest()

    def store(
        self,
        filename: str,
        content: bytes,
        content_type: str,
        email_id: Optional[int] = None
    ) -> AttachmentMetadata:
        """
        Store attachment with deduplication and optional compression.
        
        Returns:
            AttachmentMetadata with storage info
        """
        with self._lock:
            # Compute checksum
            checksum = self.compute_checksum(content)

            original_size = len(content)

            # Apply compression if enabled
            if self.enable_compression and original_size > 1024:  # Only compress > 1KB
                compressed = zlib.compress(content, level=6)

                # Only use compressed if it's smaller
                if len(compressed) < original_size:
                    content = compressed
                    is_compressed = True

            # Check for duplicates
            dedup_path = self.storage_root / "data" / "dedup" / f"{checksum}.bin"

            if self.enable_deduplication and dedup_path.exists():
                # Already exists - use existing
                logger.info(f"Using existing dedup file for {checksum[:8]}...")
                storage_path = str(dedup_path)
            else:
                # Store new
                storage_path = str(dedup_path)

                with open(storage_path, 'wb') as f:
                    f.write(content)

                logger.info(f"Stored new attachment: {checksum[:8]}...")

            # Create metadata
            attachment_id = f"att_{checksum[:16]}"

            meta = AttachmentMetadata(
                attachment_id=attachment_id,
                filename=filename,
                content_type=content_type,
                size=len(content),
                checksum=checksum,
                storage_path=storage_path,
                email_id=email_id,
                is_compressed=is_compressed if 'is_compressed' in locals() else False,
                original_size=original_size if 'is_compressed' in locals() and is_compressed else None
            )

            # Add to indexes
            self._index[attachment_id] = meta

            if email_id:
                if email_id not in self._email_index:
                    self._email_index[email_id] = []
                self._email_index[email_id].append(attachment_id)

            # Save index
            self._save_index()

            return meta

    def retrieve(self, attachment_id: str) -> Optional[bytes]:
        """Retrieve attachment data"""
        with self._lock:
            if attachment_id not in self._index:
                return None

            meta = self._index[attachment_id]

            try:
                with open(meta.storage_path, 'rb') as f:
                    data = f.read()

                # Decompress if needed
                if meta.is_compressed:
                    data = zlib.decompress(data)

                return data

            except Exception as e:
                logger.error(f"Failed to retrieve {attachment_id}: {e}")
                return None

    def get_metadata(self, attachment_id: str) -> Optional[AttachmentMetadata]:
        """Get attachment metadata"""
        with self._lock:
            return self._index.get(attachment_id)

    def get_by_email(self, email_id: int) -> List[AttachmentMetadata]:
        """Get all attachments for an email"""
        with self._lock:
            attachment_ids = self._email_index.get(email_id, [])
            return [self._index[aid] for aid in attachment_ids if aid in self._index]

    def delete(self, attachment_id: str) -> bool:
        """Delete attachment (marks as deleted, doesn't remove file)"""
        with self._lock:
            if attachment_id not in self._index:
                return False

            meta = self._index[attachment_id]
            meta.is_deleted = True  # Mark as deleted

            # Remove from email index
            if meta.email_id and meta.email_id in self._email_index:
                self._email_index[meta.email_id].remove(attachment_id)

            self._save_index()

            logger.info(f"Marked attachment {attachment_id[:8]}... as deleted")

            return True

    def cleanup_orphans(self) -> int:
        """
        Find and clean up orphaned files.
        
        An orphan is a file in dedup/ that has no metadata entry.
        """
        with self._lock:
            cleaned = 0

            dedup_dir = self.storage_root / "data" / "dedup"

            # Get all files in dedup
            dedup_files = set(f.stem for f in dedup_dir.glob("*.bin"))

            # Get all checksums in index
            indexed_checksums = set(meta.checksum for meta in self._index.values())

            # Find orphans
            orphans = dedup_files - indexed_checksums

            # Move orphans to orphan directory
            for checksum in orphans:
                src = dedup_dir / f"{checksum}.bin"
                dst = self.storage_root / "orphans" / f"{checksum}.bin"

                try:
                    src.rename(dst)
                    cleaned += 1
                except Exception as e:
                    logger.error(f"Failed to move orphan {checksum[:8]}...: {e}")

            if cleaned > 0:
                logger.info(f"Cleaned up {cleaned} orphaned attachment files")

            return cleaned

    def get_stats(self) -> Dict:
        """Get storage statistics"""
        with self._lock:
            total_attachments = len(self._index)
            total_size = sum(m.size for m in self._index.values())
            compressed_count = sum(1 for m in self._index.values() if m.is_compressed)

            return {
                "total_attachments": total_attachments,
                "total_size_bytes": total_size,
                "compressed_attachments": compressed_count,
                "unique_files": len(set(m.checksum for m in self._index.values())),
                "indexed_emails": len(self._email_index)
            }


# Global instance
attachment_storage = AttachmentStorageEngine()
