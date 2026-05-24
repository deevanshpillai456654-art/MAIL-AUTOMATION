"""
Zstd Compression Engine - High-performance compression for attachments

Features:
- Zstandard compression (level 1-22)
- Auto-detection of already-compressed formats
- Streaming compression for large files
- Compression ratio tracking
"""

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("storage.compression")

COMPRESSION_EXTENSIONS = {
    ".zip", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".mp3", ".mp4", ".avi", ".mkv", ".pdf",
    ".docx", ".xlsx", ".pptx"
}


class CompressionLevel(Enum):
    """Compression level presets"""
    FAST = 1
    BALANCED = 6
    MAXIMUM = 19


@dataclass
class CompressionResult:
    """Result of compression operation"""
    original_size: int
    compressed_size: int
    ratio: float
    duration_ms: float
    was_compressed: bool


@dataclass
class CompressionStats:
    """Compression statistics"""
    total_files: int = 0
    compressed_files: int = 0
    original_size_bytes: int = 0
    compressed_size_bytes: int = 0
    saved_bytes: int = 0
    skipped_already_compressed: int = 0


class ZstdCompressionEngine:
    """
    Zstandard compression engine for attachments.
    
    Features:
    - Streaming compression for large files
    - Auto-skip for already-compressed formats
    - Configurable compression levels
    - Decompression fallback
    """

    def __init__(
        self,
        storage_root: str = "./data/storage/compression",
        compression_level: int = 6,
        min_size_to_compress: int = 1024,
        skip_compressed_formats: bool = True,
        stream_threshold: int = 10 * 1024 * 1024  # 10MB
    ):
        self.storage_root = Path(storage_root)
        self.compression_level = compression_level
        self.min_size_to_compress = min_size_to_compress
        self.skip_compressed_formats = skip_compressed_formats
        self.stream_threshold = stream_threshold

        self._ensure_directories()

        self._zstd_available = False
        self._try_import_zstd()

        self._stats = CompressionStats()
        self._lock = threading.Lock()

        logger.info(f"Compression engine initialized (level={compression_level})")

    def _ensure_directories(self):
        """Create storage directories"""
        dirs = ["compressed", "temp"]
        for d in dirs:
            (self.storage_root / d).mkdir(parents=True, exist_ok=True)

    def _try_import_zstd(self):
        """Try to import zstandard library"""
        try:
            import zstandard as zstd
            self._zstd = zstd
            self._zstd_available = True
            logger.info("Zstandard library available")
        except ImportError:
            logger.warning("Zstandard not available, using fallback")
            self._zstd = None

    def should_compress(self, filename: str, data: bytes) -> bool:
        """Check if file should be compressed"""
        if len(data) < self.min_size_to_compress:
            return False

        if self.skip_compressed_formats:
            ext = Path(filename).suffix.lower()
            if ext in COMPRESSION_EXTENSIONS:
                logger.debug(f"Skipping already-compressed format: {ext}")
                return False

        return True

    def compress(
        self,
        data: bytes,
        filename: Optional[str] = None
    ) -> Tuple[bytes, CompressionResult]:
        """
        Compress data using Zstandard.
        
        Returns:
            Tuple of (compressed_data, CompressionResult)
        """
        start_time = time.time()

        if filename and not self.should_compress(filename, data):
            with self._lock:
                self._stats.skipped_already_compressed += 1
            return data, CompressionResult(
                original_size=len(data),
                compressed_size=len(data),
                ratio=1.0,
                duration_ms=0,
                was_compressed=False
            )

        if self._zstd_available:
            return self._compress_zstd(data, start_time)
        else:
            return self._compress_fallback(data, start_time)

    def _compress_zstd(self, data: bytes, start_time: float) -> Tuple[bytes, CompressionResult]:
        """Compress using zstandard library"""
        try:
            cctx = self._zstd.ZstdCompressor(level=self.compression_level)
            compressed = cctx.compress(data)

            duration_ms = (time.time() - start_time) * 1000

            result = CompressionResult(
                original_size=len(data),
                compressed_size=len(compressed),
                ratio=len(compressed) / len(data) if len(data) > 0 else 1.0,
                duration_ms=duration_ms,
                was_compressed=True
            )

            with self._lock:
                self._stats.total_files += 1
                self._stats.compressed_files += 1
                self._stats.original_size_bytes += len(data)
                self._stats.compressed_size_bytes += len(compressed)
                self._stats.saved_bytes += len(data) - len(compressed)

            logger.debug(f"Compressed {len(data)} -> {len(compressed)} ({result.ratio:.2%})")
            return compressed, result

        except Exception as e:
            logger.error(f"Zstd compression failed: {e}")
            return self._compress_fallback(data, start_time)

    def _compress_fallback(self, data: bytes, start_time: float) -> Tuple[bytes, CompressionResult]:
        """Fallback to gzip compression"""
        import gzip

        compressed = gzip.compress(data, compresslevel=6)
        duration_ms = (time.time() - start_time) * 1000

        result = CompressionResult(
            original_size=len(data),
            compressed_size=len(compressed),
            ratio=len(compressed) / len(data) if len(data) > 0 else 1.0,
            duration_ms=duration_ms,
            was_compressed=True
        )

        with self._lock:
            self._stats.total_files += 1
            self._stats.compressed_files += 1
            self._stats.original_size_bytes += len(data)
            self._stats.compressed_size_bytes += len(compressed)
            self._stats.saved_bytes += len(data) - len(compressed)

        return compressed, result

    def decompress(self, data: bytes) -> bytes:
        """Decompress data"""
        if self._zstd_available:
            try:
                dctx = self._zstd.ZstdDecompressor()
                return dctx.decompress(data)
            except Exception as e:
                logger.error(f"Zstd decompression failed: {e}")

        import gzip
        return gzip.decompress(data)

    def compress_file(
        self,
        source_path: Path,
        dest_path: Optional[Path] = None
    ) -> Tuple[Path, CompressionResult]:
        """Compress a file (streaming for large files)"""
        file_size = source_path.stat().st_size

        if dest_path is None:
            dest_path = self.storage_root / "compressed" / f"{source_path.stem}.zst"

        start_time = time.time()

        if self._zstd_available and file_size > self.stream_threshold:
            result = self._compress_file_streaming(source_path, dest_path, start_time)
        else:
            result = self._compress_file_simple(source_path, dest_path, start_time)

        return dest_path, result

    def _compress_file_streaming(
        self,
        source_path: Path,
        dest_path: Path,
        start_time: float
    ) -> CompressionResult:
        """Streaming compression for large files"""
        cctx = self._zstd.ZstdCompressor(level=self.compression_level)

        original_size = 0
        compressed_size = 0

        dest_path.parent.mkdir(parents=True, exist_ok=True)

        with open(source_path, "rb") as f_in:
            with open(dest_path, "wb") as f_out:
                with cctx.stream_writer(f_out) as writer:
                    while True:
                        chunk = f_in.read(65536)
                        if not chunk:
                            break
                        original_size += len(chunk)
                        writer.write(chunk)
                        compressed_size = dest_path.stat().st_size

        duration_ms = (time.time() - start_time) * 1000

        result = CompressionResult(
            original_size=original_size,
            compressed_size=compressed_size,
            ratio=compressed_size / original_size if original_size > 0 else 1.0,
            duration_ms=duration_ms,
            was_compressed=True
        )

        return result

    def _compress_file_simple(
        self,
        source_path: Path,
        dest_path: Path,
        start_time: float
    ) -> CompressionResult:
        """Simple compression for small files"""
        with open(source_path, "rb") as f:
            data = f.read()

        compressed, result = self.compress(data, source_path.name)

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(compressed)

        result.compressed_size = len(compressed)
        return result

    def decompress_file(
        self,
        source_path: Path,
        dest_path: Optional[Path] = None
    ) -> Path:
        """Decompress a file"""
        if dest_path is None:
            dest_path = source_path.with_suffix("")

        with open(source_path, "rb") as f:
            compressed = f.read()

        decompressed = self.decompress(compressed)

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(decompressed)

        return dest_path

    def get_stats(self) -> CompressionStats:
        """Get compression statistics"""
        with self._lock:
            return CompressionStats(
                total_files=self._stats.total_files,
                compressed_files=self._stats.compressed_files,
                original_size_bytes=self._stats.original_size_bytes,
                compressed_size_bytes=self._stats.compressed_size_bytes,
                saved_bytes=self._stats.saved_bytes,
                skipped_already_compressed=self._stats.skipped_already_compressed
            )


compression_engine = ZstdCompressionEngine()
