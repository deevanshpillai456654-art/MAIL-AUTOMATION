"""
WAL (Write-Ahead Log) Hardening Manager

Features:
- WAL mode enforcement
- Checkpoint intervals
- WAL archiving
- Recovery from WAL
- WAL size management
"""

import os
import json
import shutil
import threading
import time
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Dict
from datetime import datetime
from enum import Enum

logger = logging.getLogger("storage.wal")


class WALMode(Enum):
    """Write-ahead log modes"""
    DELETE = "delete"
    TRUNCATE = "truncate"
    PERSIST = "persist"


@dataclass
class CheckpointResult:
    """Result of checkpoint operation"""
    success: bool
    pages_written: int
    duration_ms: float
    wal_size_before: int
    wal_size_after: int


@dataclass
class WALStats:
    """WAL statistics"""
    total_checkpoints: int = 0
    total_archives: int = 0
    total_recoveries: int = 0
    last_checkpoint_time: float = 0
    current_wal_size_bytes: int = 0


class WALHardeningManager:
    """
    WAL (Write-Ahead Log) hardening manager.
    
    Features:
    - WAL mode configuration
    - Automatic checkpoints
    - WAL archiving
    - Crash recovery
    - Size management
    """
    
    def __init__(
        self,
        db_path: str = "./data/database.db",
        storage_root: str = "./data/storage/wal",
        checkpoint_interval_seconds: int = 300,
        wal_mode: WALMode = WALMode.PERSIST,
        max_wal_size_mb: int = 100,
        archive_wal: bool = True
    ):
        self.db_path = Path(db_path)
        self.storage_root = Path(storage_root)
        self.checkpoint_interval_seconds = checkpoint_interval_seconds
        self.wal_mode = wal_mode
        self.max_wal_size_bytes = max_wal_size_mb * 1024 * 1024
        self.archive_wal = archive_wal
        
        self._ensure_directories()
        
        self._lock = threading.Lock()
        self._checkpoint_thread = None
        self._running = False
        
        self._stats = WALStats()
        
        self._load_config()
        
        logger.info(f"WAL manager initialized (mode={wal_mode.value})")
    
    def _ensure_directories(self):
        """Create storage directories"""
        dirs = ["archive", "temp"]
        for d in dirs:
            (self.storage_root / d).mkdir(parents=True, exist_ok=True)
    
    def _load_config(self):
        """Load WAL configuration"""
        config_file = self.storage_root / "config.json"
        
        if config_file.exists():
            try:
                with open(config_file, "r") as f:
                    config = json.load(f)
                    self.wal_mode = WALMode(config.get("wal_mode", "persist"))
            except Exception as e:
                logger.error(f"Failed to load WAL config: {e}")
    
    def _save_config(self):
        """Save WAL configuration"""
        config_file = self.storage_root / "config.json"
        
        try:
            config = {
                "wal_mode": self.wal_mode.value,
                "checkpoint_interval_seconds": self.checkpoint_interval_seconds,
                "max_wal_size_mb": self.max_wal_size_bytes // (1024 * 1024),
                "archive_wal": self.archive_wal
            }
            
            with open(config_file, "w") as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save WAL config: {e}")
    
    def configure_database(self, conn) -> bool:
        """Configure WAL mode on database connection"""
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA wal_autocheckpoint = 0")
            
            logger.info("Database configured for WAL mode")
            return True
            
        except Exception as e:
            logger.error(f"Failed to configure WAL: {e}")
            return False
    
    def checkpoint(self, database: any = None) -> CheckpointResult:
        """Perform database checkpoint"""
        import sqlite3
        
        wal_path = self.db_path.with_suffix(".db-wal")
        shm_path = self.db_path.with_suffix(".db-shm")
        
        wal_size_before = wal_path.stat().st_size if wal_path.exists() else 0
        
        start_time = time.time()
        
        try:
            if database:
                if hasattr(database, '_get_connection'):
                    conn = database._get_connection()
                else:
                    conn = database
            else:
                conn = sqlite3.connect(str(self.db_path))
            
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
            
            wal_size_after = wal_path.stat().st_size if wal_path.exists() else 0
            
            duration_ms = (time.time() - start_time) * 1000
            
            with self._lock:
                self._stats.total_checkpoints += 1
                self._stats.last_checkpoint_time = time.time()
                self._stats.current_wal_size_bytes = wal_size_after
            
            result = CheckpointResult(
                success=True,
                pages_written=0,
                duration_ms=duration_ms,
                wal_size_before=wal_size_before,
                wal_size_after=wal_size_after
            )
            
            logger.info(f"Checkpoint completed in {duration_ms:.2f}ms")
            
            return result
            
        except Exception as e:
            logger.error(f"Checkpoint failed: {e}")
            
            return CheckpointResult(
                success=False,
                pages_written=0,
                duration_ms=0,
                wal_size_before=wal_size_before,
                wal_size_after=0
            )
    
    def archive_wal(self) -> bool:
        """Archive current WAL file"""
        wal_path = self.db_path.with_suffix(".db-wal")
        
        if not wal_path.exists():
            return False
        
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_name = f"wal_{timestamp}.gz"
            archive_path = self.storage_root / "archive" / archive_name
            
            import gzip
            with open(wal_path, "rb") as f_in:
                with gzip.open(archive_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            wal_path.unlink()
            
            with self._lock:
                self._stats.total_archives += 1
            
            logger.info(f"Archived WAL to {archive_name}")
            return True
            
        except Exception as e:
            logger.error(f"WAL archive failed: {e}")
            return False
    
    def recover_from_wal(self) -> bool:
        """Attempt recovery from WAL file"""
        wal_path = self.db_path.with_suffix(".db-wal")
        
        if not wal_path.exists():
            logger.warning("No WAL file for recovery")
            return False
        
        try:
            import sqlite3
            
            conn = sqlite3.connect(str(self.db_path))
            
            conn.execute("PRAGMA wal_checkpoint(FULL)")
            
            conn.execute("SELECT COUNT(*) FROM sqlite_master")
            
            conn.close()
            
            with self._lock:
                self._stats.total_recoveries += 1
            
            logger.info("Recovery from WAL completed")
            return True
            
        except Exception as e:
            logger.error(f"Recovery failed: {e}")
            
            backup_path = self.db_path.with_suffix(".db.corrupted")
            try:
                shutil.copy2(self.db_path, backup_path)
                logger.info(f"Created backup at {backup_path}")
            except Exception as copy_err:
                logger.warning("Could not copy corrupted db to backup: %s", copy_err)
            
            return False
    
    def enforce_wal_mode(self, conn) -> bool:
        """Ensure WAL mode is enforced"""
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode")
            mode = cursor.fetchone()[0]
            
            if mode.lower() != "wal":
                cursor.execute("PRAGMA journal_mode = WAL")
                logger.warning(f"Changed journal mode to WAL from {mode}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to enforce WAL mode: {e}")
            return False
    
    def get_wal_size(self) -> int:
        """Get current WAL file size"""
        wal_path = self.db_path.with_suffix(".db-wal")
        
        if wal_path.exists():
            return wal_path.stat().st_size
        return 0
    
    def manage_wal_size(self) -> bool:
        """Manage WAL size based on configuration"""
        current_size = self.get_wal_size()
        
        if current_size > self.max_wal_size_bytes:
            logger.warning(f"WAL size {current_size} exceeds max {self.max_wal_size_bytes}")
            
            self.checkpoint()
            
            if self.archive_wal:
                self.archive_wal()
            elif self.wal_mode == WALMode.TRUNCATE:
                wal_path = self.db_path.with_suffix(".db-wal")
                if wal_path.exists():
                    wal_path.unlink()
            
            return True
        
        return False
    
    def start_auto_checkpoint(self, database):
        """Start automatic checkpoint thread"""
        if self._running:
            return
        
        self._running = True
        
        def checkpoint_loop():
            while self._running:
                time.sleep(self.checkpoint_interval_seconds)
                
                try:
                    self.manage_wal_size()
                    self.checkpoint(database)
                except Exception as e:
                    logger.error(f"Auto checkpoint error: {e}")
        
        self._checkpoint_thread = threading.Thread(target=checkpoint_loop, daemon=True)
        self._checkpoint_thread.start()
        
        logger.info("Auto checkpoint started")
    
    def stop_auto_checkpoint(self):
        """Stop automatic checkpoint thread"""
        self._running = False
        
        if self._checkpoint_thread:
            self._checkpoint_thread.join(timeout=5)
        
        logger.info("Auto checkpoint stopped")
    
    def list_archives(self) -> List[Dict]:
        """List WAL archives"""
        archives = []
        
        archive_dir = self.storage_root / "archive"
        
        for archive_file in sorted(archive_dir.glob("wal_*.gz"), reverse=True):
            archives.append({
                "name": archive_file.name,
                "size_bytes": archive_file.stat().st_size,
                "created_at": archive_file.stat().st_ctime
            })
        
        return archives
    
    def restore_archive(self, archive_name: str) -> bool:
        """Restore WAL from archive"""
        archive_path = self.storage_root / "archive" / archive_name
        wal_path = self.db_path.with_suffix(".db-wal")
        
        if not archive_path.exists():
            return False
        
        try:
            import gzip
            
            with gzip.open(archive_path, "rb") as f_in:
                with open(wal_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            logger.info(f"Restored WAL from {archive_name}")
            return True
            
        except Exception as e:
            logger.error(f"Archive restore failed: {e}")
            return False
    
    def get_stats(self) -> WALStats:
        """Get WAL statistics"""
        with self._lock:
            stats = WALStats(
                total_checkpoints=self._stats.total_checkpoints,
                total_archives=self._stats.total_archives,
                total_recoveries=self._stats.total_recoveries,
                last_checkpoint_time=self._stats.last_checkpoint_time,
                current_wal_size_bytes=self.get_wal_size()
            )
        
        return stats


wal_manager = WALHardeningManager()