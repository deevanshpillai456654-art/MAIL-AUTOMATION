"""
Chunked Storage Manager - Chunk-based storage with parallel operations

Features:
- 1MB default chunk size
- Chunk indexing and retrieval
- Parallel chunk operations
- Chunk integrity checks
- Partial retrieval support
"""

import os
import hashlib
import threading
import time
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum

logger = logging.getLogger("storage.chunked")


class ChunkError(Exception):
    """Chunk storage errors"""
    pass


class IntegrityCheck(Enum):
    """Integrity check methods"""
    SHA256 = "sha256"
    CRC32 = "crc32"
    NONE = "none"


@dataclass
class ChunkInfo:
    """Information about a chunk"""
    chunk_id: str
    offset: int
    size: int
    checksum: str
    integrity_method: IntegrityCheck = IntegrityCheck.SHA256


@dataclass
class ChunkedFileInfo:
    """Information about a chunked file"""
    file_id: str
    original_size: int
    chunk_size: int
    chunks: List[ChunkInfo] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    is_complete: bool = False


@dataclass
class ChunkStats:
    """Chunk storage statistics"""
    total_files: int = 0
    total_chunks: int = 0
    total_size_bytes: int = 0
    chunk_size_bytes: int = 0
    parallel_operations: int = 0
    failed_operations: int = 0


class ChunkedStorageManager:
    """
    Chunk-based storage manager for large files.
    
    Features:
    - Configurable chunk size (default 1MB)
    - Parallel chunk read/write
    - Integrity verification
    - Partial file retrieval
    """
    
    def __init__(
        self,
        storage_root: str = "./data/storage/chunked",
        chunk_size: int = 1024 * 1024,  # 1MB
        max_workers: int = 4,
        enable_integrity: bool = True,
        integrity_method: IntegrityCheck = IntegrityCheck.SHA256
    ):
        self.storage_root = Path(storage_root)
        self.chunk_size = chunk_size
        self.max_workers = max_workers
        self.enable_integrity = enable_integrity
        self.integrity_method = integrity_method
        
        self._ensure_directories()
        
        self._file_index: Dict[str, ChunkedFileInfo] = {}
        self._chunk_cache: Dict[str, bytes] = {}
        self._cache_max_size = 10 * chunk_size
        self._lock = threading.Lock()
        
        self._stats = ChunkStats(chunk_size_bytes=chunk_size)
        
        self._load_index()
        
        logger.info(f"Chunked storage initialized (chunk_size={chunk_size})")
    
    def _ensure_directories(self):
        """Create storage directories"""
        dirs = ["chunks", "index", "temp"]
        for d in dirs:
            (self.storage_root / d).mkdir(parents=True, exist_ok=True)
    
    def _chunk_path(self, chunk_id: str) -> Path:
        """Get path for chunk"""
        return self.storage_root / "chunks" / f"{chunk_id}.chunk"
    
    def _compute_checksum(self, data: bytes) -> str:
        """Compute checksum for data"""
        if self.integrity_method == IntegrityCheck.SHA256:
            return hashlib.sha256(data).hexdigest()
        elif self.integrity_method == IntegrityCheck.CRC32:
            import zlib
            return format(zlib.crc32(data) & 0xFFFFFFFF, '08x')
        else:
            return ""
    
    def verify_checksum(self, data: bytes, expected_checksum: str) -> bool:
        """Verify data checksum"""
        actual = self._compute_checksum(data)
        return actual == expected_checksum
    
    def store(
        self,
        data: bytes,
        file_id: Optional[str] = None
    ) -> ChunkedFileInfo:
        """
        Store data in chunks.
        
        Returns:
            ChunkedFileInfo with chunk details
        """
        if file_id is None:
            file_id = hashlib.sha256(data).hexdigest()[:16]
        
        chunks = []
        offset = 0
        chunk_num = 0
        
        while offset < len(data):
            chunk_data = data[offset:offset + self.chunk_size]
            chunk_id = f"{file_id}_{chunk_num:04d}"
            
            checksum = self._compute_checksum(chunk_data)
            chunk_path = self._chunk_path(chunk_id)
            
            chunk_path.parent.mkdir(parents=True, exist_ok=True)
            with open(chunk_path, "wb") as f:
                f.write(chunk_data)
            
            chunk_info = ChunkInfo(
                chunk_id=chunk_id,
                offset=offset,
                size=len(chunk_data),
                checksum=checksum,
                integrity_method=self.integrity_method
            )
            chunks.append(chunk_info)
            
            offset += self.chunk_size
            chunk_num += 1
        
        file_info = ChunkedFileInfo(
            file_id=file_id,
            original_size=len(data),
            chunk_size=self.chunk_size,
            chunks=chunks,
            is_complete=True
        )
        
        with self._lock:
            self._file_index[file_id] = file_info
            self._stats.total_files += 1
            self._stats.total_chunks += len(chunks)
            self._stats.total_size_bytes += len(data)
            self._save_index()
        
        logger.info(f"Stored {file_id} in {len(chunks)} chunks")
        
        return file_info
    
    def store_parallel(
        self,
        data: bytes,
        file_id: Optional[str] = None
    ) -> ChunkedFileInfo:
        """Store data using parallel chunk writes"""
        if file_id is None:
            file_id = hashlib.sha256(data).hexdigest()[:16]
        
        chunks = []
        chunk_data_list = []
        
        offset = 0
        chunk_num = 0
        while offset < len(data):
            chunk_data = data[offset:offset + self.chunk_size]
            chunk_id = f"{file_id}_{chunk_num:04d}"
            checksum = self._compute_checksum(chunk_data)
            
            chunk_info = ChunkInfo(
                chunk_id=chunk_id,
                offset=offset,
                size=len(chunk_data),
                checksum=checksum,
                integrity_method=self.integrity_method
            )
            chunks.append(chunk_info)
            chunk_data_list.append((chunk_id, chunk_data))
            
            offset += self.chunk_size
            chunk_num += 1
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._write_chunk, chunk_id, data): chunk_id
                for chunk_id, data in chunk_data_list
            }
            
            for future in as_completed(futures):
                with self._lock:
                    self._stats.parallel_operations += 1
        
        file_info = ChunkedFileInfo(
            file_id=file_id,
            original_size=len(data),
            chunk_size=self.chunk_size,
            chunks=chunks,
            is_complete=True
        )
        
        with self._lock:
            self._file_index[file_id] = file_info
            self._stats.total_files += 1
            self._stats.total_chunks += len(chunks)
            self._stats.total_size_bytes += len(data)
            self._save_index()
        
        return file_info
    
    def _write_chunk(self, chunk_id: str, data: bytes):
        """Write a single chunk to disk"""
        chunk_path = self._chunk_path(chunk_id)
        chunk_path.parent.mkdir(parents=True, exist_ok=True)
        with open(chunk_path, "wb") as f:
            f.write(data)
    
    def retrieve(self, file_id: str) -> Optional[bytes]:
        """Retrieve all chunks and reassemble file"""
        with self._lock:
            if file_id not in self._file_index:
                return None
            
            file_info = self._file_index[file_id]
        
        chunks_data = []
        
        for chunk_info in file_info.chunks:
            chunk_path = self._chunk_path(chunk_info.chunk_id)
            
            if not chunk_path.exists():
                logger.error(f"Missing chunk: {chunk_info.chunk_id}")
                return None
            
            with open(chunk_path, "rb") as f:
                chunk_data = f.read()
            
            if self.enable_integrity:
                if not self.verify_checksum(chunk_data, chunk_info.checksum):
                    logger.error(f"Chunk integrity check failed: {chunk_info.chunk_id}")
                    return None
            
            chunks_data.append(chunk_data)
        
        return b"".join(chunks_data)
    
    def retrieve_partial(
        self,
        file_id: str,
        start_offset: int,
        length: int
    ) -> Optional[bytes]:
        """Retrieve partial data from chunks"""
        with self._lock:
            if file_id not in self._file_index:
                return None
            
            file_info = self._file_index[file_id]
        
        result = bytearray()
        remaining = length
        current_offset = start_offset
        
        for chunk_info in file_info.chunks:
            if current_offset >= chunk_info.offset + chunk_info.size:
                continue
            
            chunk_start = max(0, current_offset - chunk_info.offset)
            chunk_end = min(chunk_info.size, chunk_start + remaining)
            
            chunk_path = self._chunk_path(chunk_info.chunk_id)
            
            if not chunk_path.exists():
                return None
            
            with open(chunk_path, "rb") as f:
                f.seek(chunk_start)
                chunk_data = f.read(chunk_end - chunk_start)
            
            result.extend(chunk_data)
            remaining -= len(chunk_data)
            
            if remaining <= 0:
                break
            
            current_offset += len(chunk_data)
        
        return bytes(result) if len(result) > 0 else None
    
    def delete(self, file_id: str) -> bool:
        """Delete all chunks for a file"""
        with self._lock:
            if file_id not in self._file_index:
                return False
            
            file_info = self._file_index[file_id]
        
        deleted_chunks = 0
        for chunk_info in file_info.chunks:
            chunk_path = self._chunk_path(chunk_info.chunk_id)
            if chunk_path.exists():
                try:
                    chunk_path.unlink()
                    deleted_chunks += 1
                except Exception as e:
                    logger.error(f"Failed to delete chunk: {e}")
        
        del self._file_index[file_id]
        
        with self._lock:
            self._stats.total_files -= 1
            self._stats.total_chunks -= deleted_chunks
            self._save_index()
        
        logger.info(f"Deleted {file_id} ({deleted_chunks} chunks)")
        
        return True
    
    def verify_integrity(self, file_id: str) -> bool:
        """Verify integrity of all chunks"""
        with self._lock:
            if file_id not in self._file_index:
                return False
            
            file_info = self._file_index[file_id]
        
        for chunk_info in file_info.chunks:
            chunk_path = self._chunk_path(chunk_info.chunk_id)
            
            if not chunk_path.exists():
                return False
            
            with open(chunk_path, "rb") as f:
                chunk_data = f.read()
            
            if not self.verify_checksum(chunk_data, chunk_info.checksum):
                return False
        
        return True
    
    def get_file_info(self, file_id: str) -> Optional[ChunkedFileInfo]:
        """Get file info without loading data"""
        with self._lock:
            return self._file_index.get(file_id)
    
    def get_stats(self) -> ChunkStats:
        """Get chunk storage statistics"""
        with self._lock:
            return ChunkStats(
                total_files=self._stats.total_files,
                total_chunks=self._stats.total_chunks,
                total_size_bytes=self._stats.total_size_bytes,
                chunk_size_bytes=self._stats.chunk_size_bytes,
                parallel_operations=self._stats.parallel_operations,
                failed_operations=self._stats.failed_operations
            )
    
    def _load_index(self):
        """Load chunk index from disk"""
        import json
        index_file = self.storage_root / "index" / "chunked_index.json"
        
        if index_file.exists():
            try:
                with open(index_file, "r") as f:
                    data = json.load(f)
                    for item in data.get("files", []):
                        file_info = ChunkedFileInfo(
                            file_id=item["file_id"],
                            original_size=item["original_size"],
                            chunk_size=item["chunk_size"],
                            chunks=[ChunkInfo(**c) for c in item["chunks"]],
                            created_at=item.get("created_at", time.time()),
                            is_complete=item.get("is_complete", False)
                        )
                        self._file_index[file_info.file_id] = file_info
                logger.info(f"Loaded {len(self._file_index)} chunked files")
            except Exception as e:
                logger.error(f"Failed to load chunk index: {e}")
    
    def _save_index(self):
        """Save chunk index to disk"""
        import json
        index_file = self.storage_root / "index" / "chunked_index.json"
        
        try:
            data = {
                "files": [
                    {
                        "file_id": f.file_id,
                        "original_size": f.original_size,
                        "chunk_size": f.chunk_size,
                        "chunks": [
                            {
                                "chunk_id": c.chunk_id,
                                "offset": c.offset,
                                "size": c.size,
                                "checksum": c.checksum,
                                "integrity_method": c.integrity_method.value
                            }
                            for c in f.chunks
                        ],
                        "created_at": f.created_at,
                        "is_complete": f.is_complete
                    }
                    for f in self._file_index.values()
                ],
                "updated_at": time.time()
            }
            
            with open(index_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save chunk index: {e}")


chunked_storage = ChunkedStorageManager()