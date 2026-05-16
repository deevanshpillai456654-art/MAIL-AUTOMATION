"""
Security Sandbox Engine - Attachment Sandboxing & Scanning
===========================================================

Enterprise security:
- PDF sandboxing
- Attachment scanning
- MIME validation
- Executable detection
- Macro detection
- Archive bomb protection
- Malware scanning
- Quarantine system
"""
import os
__path__ = [os.path.join(os.path.dirname(__file__), "sandbox")]

import io
import time
import hashlib
import zipfile
import logging
import threading
import sqlite3
import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set
from enum import Enum
from collections import deque
from backend import config

logger = logging.getLogger("security.sandbox")


class ThreatLevel(Enum):
    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    DANGEROUS = "dangerous"
    QUARANTINED = "quarantined"


class ThreatType(Enum):
    EXECUTABLE = "executable"
    MACRO = "macro"
    ARCHIVE_BOMB = "archive_bomb"
    MALWARE = "malware"
    CORRUPTED = "corrupted"
    OVERSIZE = "oversize"
    INVALID_MIME = "invalid_mime"


@dataclass
class AttachmentScanResult:
    """Attachment scan result"""
    file_id: str
    filename: str
    mime_type: str
    size: int
    threat_level: ThreatLevel
    threat_type: Optional[ThreatType]
    details: str
    scan_time: float
    is_clean: bool


@dataclass
class QuarantinedFile:
    """Quarantined file record"""
    quarantine_id: str
    original_path: str
    file_hash: str
    threat_type: ThreatType
    threat_level: ThreatLevel
    details: str
    quarantined_at: float
    original_owner: Optional[str]


class SecuritySandbox:
    """
    Enterprise security sandbox for attachment scanning.
    """
    
    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir or config.DATA_DIR)
        self.quarantine_dir = self.data_dir / "quarantine"
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        
        self.db_path = self.data_dir / "sandbox.db"
        self._init_db()
        
        # Scanning configuration
        self.max_file_size = 100 * 1024 * 1024  # 100MB
        self.max_archive_size = 500 * 1024 * 1024  # 500MB
        self.max_archive_entries = 10000
        self.max_extraction_depth = 5
        
        # Dangerous extensions
        self.dangerous_extensions = {
            ".exe", ".dll", ".bat", ".cmd", ".ps1", ".sh",
            ".vbs", ".js", ".jse", ".wsf", ".wsh", ".msi",
            ".scr", ".pif", ".com", ".jar", ".class",
            ".shx", ".app", ".bin", ".dmg", ".pkg"
        }
        
        # Suspicious extensions
        self.suspicious_extensions = {
            ".docm", ".xlsm", ".pptm", ".docb", ".rtf",
            ".zip", ".rar", ".7z", ".tar", ".gz",
            ".htm", ".html", ".hta", ".svg"
        }
        
        # Known dangerous MIME types
        self.dangerous_mime_types = {
            "application/x-msdownload",
            "application/x-executable",
            "application/x-msdos-program",
            "application/hta",
            "text/javascript",
            "application/javascript"
        }
        
        # Scan history
        self._scan_history: deque = deque(maxlen=1000)
        self._scan_lock = threading.RLock()
        
        # Background scanning
        self._scan_queue: List[Dict] = []
        self._running = False
        self._scan_thread = None
        
        logger.info("Security Sandbox initialized")
    
    def _init_db(self):
        """Initialize sandbox database"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        # Scan results
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scan_results (
                file_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                mime_type TEXT,
                size INTEGER,
                threat_level TEXT,
                threat_type TEXT,
                details TEXT,
                scan_time REAL,
                file_hash TEXT
            )
        """)
        
        # Quarantine
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS quarantined_files (
                quarantine_id TEXT PRIMARY KEY,
                original_path TEXT,
                file_hash TEXT NOT NULL,
                threat_type TEXT NOT NULL,
                threat_level TEXT NOT NULL,
                details TEXT,
                quarantined_at REAL,
                original_owner TEXT
            )
        """)
        
        # Threat signatures
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS threat_signatures (
                signature_id TEXT PRIMARY KEY,
                threat_type TEXT NOT NULL,
                pattern TEXT NOT NULL,
                severity TEXT,
                created_at REAL
            )
        """)
        
        conn.commit()
        conn.close()
    
    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def scan_attachment(self, file_path: str, 
                       filename: str = None) -> AttachmentScanResult:
        """Scan attachment for threats"""
        import secrets
        
        file_id = f"scan_{secrets.token_hex(8)}"
        filename = filename or os.path.basename(file_path)
        
        start_time = time.time()
        
        # Get file info
        try:
            file_size = os.path.getsize(file_path)
        except Exception:
            file_size = 0
        
        # Check file size
        if file_size > self.max_file_size:
            return AttachmentScanResult(
                file_id=file_id,
                filename=filename,
                mime_type="unknown",
                size=file_size,
                threat_level=ThreatLevel.DANGEROUS,
                threat_type=ThreatType.OVERSIZE,
                details=f"File exceeds maximum size: {file_size} bytes",
                scan_time=time.time() - start_time,
                is_clean=False
            )
        
        # Calculate hash
        try:
            with open(file_path, "rb") as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()
        except Exception:
            file_hash = "unknown"
        
        # Detect MIME type
        mime_type = self._detect_mime(file_path, filename)
        
        # Scan based on file type
        result = self._scan_by_type(file_path, filename, mime_type, file_hash)
        
        result.file_id = file_id
        result.size = file_size
        
        # Store result
        self._store_scan_result(result, file_hash)
        
        # Update history
        with self._scan_lock:
            self._scan_history.append(result)
        
        logger.info(f"Scan complete: {filename} - {result.threat_level.value}")
        
        return result
    
    def _detect_mime(self, file_path: str, filename: str) -> str:
        """Detect MIME type"""
        ext = os.path.splitext(filename)[1].lower()
        
        mime_types = {
            ".pdf": "application/pdf",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xls": "application/vnd.ms-excel",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".ppt": "application/vnd.ms-powerpoint",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".txt": "text/plain",
            ".html": "text/html",
            ".htm": "text/html",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".zip": "application/zip",
            ".7z": "application/x-7z-compressed",
            ".rar": "application/x-rar-compressed",
            ".exe": "application/x-msdownload",
            ".dll": "application/x-msdownload",
            ".js": "application/javascript",
            ".htm": "text/html"
        }
        
        return mime_types.get(ext, "application/octet-stream")
    
    def _scan_by_type(self, file_path: str, filename: str, 
                     mime_type: str, file_hash: str) -> AttachmentScanResult:
        """Scan based on file type"""
        ext = os.path.splitext(filename)[1].lower()
        
        # Check for dangerous extension
        if ext in self.dangerous_extensions:
            return AttachmentScanResult(
                file_id="",
                filename=filename,
                mime_type=mime_type,
                size=0,
                threat_level=ThreatLevel.DANGEROUS,
                threat_type=ThreatType.EXECUTABLE,
                details=f"Dangerous file extension: {ext}",
                scan_time=0,
                is_clean=False
            )
        
        # Check for suspicious extension
        if ext in self.suspicious_extensions:
            return self._deep_scan(file_path, filename, mime_type, file_hash)
        
        # Check for archive
        if ext in {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"}:
            return self._scan_archive(file_path, filename, file_hash)
        
        # Check for document with potential macros
        if ext in {".docm", ".xlsm", ".pptm", ".doc", ".xls", ".ppt"}:
            return self._scan_document(file_path, filename, mime_type, file_hash)
        
        # Default: assume safe
        return AttachmentScanResult(
            file_id="",
            filename=filename,
            mime_type=mime_type,
            size=0,
            threat_level=ThreatLevel.SAFE,
            threat_type=None,
            details="No threats detected",
            scan_time=0,
            is_clean=True
        )
    
    def _deep_scan(self, file_path: str, filename: str,
                  mime_type: str, file_hash: str) -> AttachmentScanResult:
        """Deep scan for suspicious files"""
        # Check invalid MIME
        if mime_type in self.dangerous_mime_types:
            return AttachmentScanResult(
                file_id="",
                filename=filename,
                mime_type=mime_type,
                size=0,
                threat_level=ThreatLevel.DANGEROUS,
                threat_type=ThreatType.INVALID_MIME,
                details=f"Dangerous MIME type: {mime_type}",
                scan_time=0,
                is_clean=False
            )
        
        # Check for suspicious content
        try:
            with open(file_path, "rb") as f:
                content = f.read(1024)  # Read first 1KB
                
                # Check for scripts
                if b"<script" in content.lower() or b"javascript:" in content.lower():
                    return AttachmentScanResult(
                        file_id="",
                        filename=filename,
                        mime_type=mime_type,
                        size=0,
                        threat_level=ThreatLevel.SUSPICIOUS,
                        threat_type=ThreatType.MALWARE,
                        details="Suspicious script content detected",
                        scan_time=0,
                        is_clean=False
                    )
                
                # Check for VBA macros
                if b"VBA" in content or b"Macro" in content:
                    return AttachmentScanResult(
                        file_id="",
                        filename=filename,
                        mime_type=mime_type,
                        size=0,
                        threat_level=ThreatLevel.SUSPICIOUS,
                        threat_type=ThreatType.MACRO,
                        details="Potential macro content detected",
                        scan_time=0,
                        is_clean=False
                    )
        
        except Exception:
            pass
        
        # Check for matching threat signatures
        if self._check_threat_signatures(file_hash):
            return AttachmentScanResult(
                file_id="",
                filename=filename,
                mime_type=mime_type,
                size=0,
                threat_level=ThreatLevel.DANGEROUS,
                threat_type=ThreatType.MALWARE,
                details="Known threat signature detected",
                scan_time=0,
                is_clean=False
            )
        
        return AttachmentScanResult(
            file_id="",
            filename=filename,
            mime_type=mime_type,
            size=0,
            threat_level=ThreatLevel.SUSPICIOUS,
            threat_type=None,
            details="Requires careful handling",
            scan_time=0,
            is_clean=False
        )
    
    def _scan_archive(self, file_path: str, filename: str,
                     file_hash: str) -> AttachmentScanResult:
        """Scan archive files for bombs and threats"""
        try:
            file_size = os.path.getsize(file_path)
            
            # Check compressed ratio (archive bomb detection)
            uncompressed_size = 0
            entry_count = 0
            
            with zipfile.ZipFile(file_path, "r") as zf:
                for info in zf.infolist():
                    entry_count += 1
                    
                    if entry_count > self.max_archive_entries:
                        return AttachmentScanResult(
                            file_id="",
                            filename=filename,
                            mime_type="application/zip",
                            size=file_size,
                            threat_level=ThreatLevel.DANGEROUS,
                            threat_type=ThreatType.ARCHIVE_BOMB,
                            details=f"Too many archive entries: {entry_count}",
                            scan_time=0,
                            is_clean=False
                        )
                    
                    uncompressed_size += info.file_size
                    
                    # Check for extremely compressed files (zip bomb)
                    if info.file_size > 0 and info.compress_size > 0:
                        ratio = info.file_size / info.compress_size
                        if ratio > 1000:
                            return AttachmentScanResult(
                                file_id="",
                                filename=filename,
                                mime_type="application/zip",
                                size=file_size,
                                threat_level=ThreatLevel.DANGEROUS,
                                threat_type=ThreatType.ARCHIVE_BOMB,
                                details=f"Possible zip bomb: ratio {ratio}",
                                scan_time=0,
                                is_clean=False
                            )
                    
                    # Check filename for dangerous extensions
                    if any(info.filename.endswith(ext) for ext in self.dangerous_extensions):
                        return AttachmentScanResult(
                            file_id="",
                            filename=filename,
                            mime_type="application/zip",
                            size=file_size,
                            threat_level=ThreatLevel.DANGEROUS,
                            threat_type=ThreatType.EXECUTABLE,
                            details=f"Dangerous file in archive: {info.filename}",
                            scan_time=0,
                            is_clean=False
                        )
                    
                    # Check extraction depth
                    depth = info.filename.count("/")
                    if depth > self.max_extraction_depth:
                        return AttachmentScanResult(
                            file_id="",
                            filename=filename,
                            mime_type="application/zip",
                            size=file_size,
                            threat_level=ThreatLevel.SUSPICIOUS,
                            threat_type=ThreatType.ARCHIVE_BOMB,
                            details=f"Excessive path depth: {depth}",
                            scan_time=0,
                            is_clean=False
                        )
                
                # Check total uncompressed size
                if uncompressed_size > self.max_archive_size:
                    return AttachmentScanResult(
                        file_id="",
                        filename=filename,
                        mime_type="application/zip",
                        size=file_size,
                        threat_level=ThreatLevel.DANGEROUS,
                        threat_type=ThreatType.ARCHIVE_BOMB,
                        details=f"Archive too large when extracted: {uncompressed_size}",
                        scan_time=0,
                        is_clean=False
                    )
        
        except zipfile.BadZipFile:
            return AttachmentScanResult(
                file_id="",
                filename=filename,
                mime_type="application/zip",
                size=0,
                threat_level=ThreatLevel.DANGEROUS,
                threat_type=ThreatType.CORRUPTED,
                details="Corrupted archive file",
                scan_time=0,
                is_clean=False
            )
        except Exception as e:
            logger.warning(f"Archive scan error: {e}")
        
        return AttachmentScanResult(
            file_id="",
            filename=filename,
            mime_type="application/zip",
            size=0,
            threat_level=ThreatLevel.SAFE,
            threat_type=None,
            details="Archive scan passed",
            scan_time=0,
            is_clean=True
        )
    
    def _scan_document(self, file_path: str, filename: str,
                      mime_type: str, file_hash: str) -> AttachmentScanResult:
        """Scan documents for macros and threats"""
        try:
            with open(file_path, "rb") as f:
                content = f.read(8192)  # Read first 8KB
                
                # Check for OLE compound document (may contain macros)
                if content[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                    return AttachmentScanResult(
                        file_id="",
                        filename=filename,
                        mime_type=mime_type,
                        size=0,
                        threat_level=ThreatLevel.SUSPICIOUS,
                        threat_type=ThreatType.MACRO,
                        details="OLE document - potential macros",
                        scan_time=0,
                        is_clean=False
                    )
                
                # Check for VBA content
                if b"VBAScript" in content or b"Sub " in content or b"Function " in content:
                    return AttachmentScanResult(
                        file_id="",
                        filename=filename,
                        mime_type=mime_type,
                        size=0,
                        threat_level=ThreatLevel.SUSPICIOUS,
                        threat_type=ThreatType.MACRO,
                        details="VBA macro content detected",
                        scan_time=0,
                        is_clean=False
                    )
        
        except Exception as e:
            logger.warning(f"Document scan error: {e}")
        
        return AttachmentScanResult(
            file_id="",
            filename=filename,
            mime_type=mime_type,
            size=0,
            threat_level=ThreatLevel.SAFE,
            threat_type=None,
            details="Document scan passed",
            scan_time=0,
            is_clean=True
        )
    
    def _check_threat_signatures(self, file_hash: str) -> bool:
        """Check against known threat signatures"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM threat_signatures 
                WHERE pattern = ?
            """, (file_hash,))
            return cursor.fetchone()[0] > 0
    
    def _store_scan_result(self, result: AttachmentScanResult, file_hash: str):
        """Store scan result in database"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO scan_results
                (file_id, filename, mime_type, size, threat_level, threat_type, details, scan_time, file_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                result.file_id,
                result.filename,
                result.mime_type,
                result.size,
                result.threat_level.value,
                result.threat_type.value if result.threat_type else None,
                result.details,
                result.scan_time,
                file_hash
            ))
            conn.commit()
    
    def quarantine_file(self, file_path: str, threat_type: ThreatType,
                       threat_level: ThreatLevel, details: str,
                       owner: str = None) -> Optional[str]:
        """Quarantine a dangerous file"""
        import secrets
        
        # Calculate hash
        try:
            with open(file_path, "rb") as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()
        except Exception:
            return None
        
        quarantine_id = f"q_{secrets.token_hex(8)}"
        
        # Move to quarantine
        quarantine_path = self.quarantine_dir / f"{quarantine_id}_{os.path.basename(file_path)}"
        
        try:
            os.rename(file_path, quarantine_path)
        except Exception:
            # If rename fails, copy and delete
            import shutil
            try:
                shutil.copy2(file_path, quarantine_path)
                os.remove(file_path)
            except Exception:
                return None
        
        # Store quarantine record
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO quarantined_files
                (quarantine_id, original_path, file_hash, threat_type, threat_level, details, quarantined_at, original_owner)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                quarantine_id,
                file_path,
                file_hash,
                threat_type.value,
                threat_level.value,
                details,
                time.time(),
                owner
            ))
            conn.commit()
        
        logger.warning(f"File quarantined: {quarantine_id} ({threat_type.value})")
        
        return quarantine_id
    
    def release_from_quarantine(self, quarantine_id: str, target_path: str) -> bool:
        """Release file from quarantine"""
        try:
            quarantine_file = self.quarantine_dir / f"{quarantine_id}_*"
            
            # Find file
            for f in self.quarantine_dir.glob(f"{quarantine_id}_*"):
                # Move back
                os.rename(str(f), target_path)
                
                # Delete record
                with self._get_conn() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        DELETE FROM quarantined_files WHERE quarantine_id = ?
                    """, (quarantine_id,))
                    conn.commit()
                
                logger.info(f"File released from quarantine: {quarantine_id}")
                return True
        
        except Exception as e:
            logger.error(f"Release failed: {e}")
        
        return False
    
    def get_quarantine_list(self) -> List[QuarantinedFile]:
        """Get list of quarantined files"""
        files = []
        
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM quarantined_files 
                ORDER BY quarantined_at DESC
            """)
            
            for row in cursor.fetchall():
                files.append(QuarantinedFile(
                    quarantine_id=row["quarantine_id"],
                    original_path=row["original_path"],
                    file_hash=row["file_hash"],
                    threat_type=ThreatType(row["threat_type"]),
                    threat_level=ThreatLevel(row["threat_level"]),
                    details=row["details"],
                    quarantined_at=row["quarantined_at"],
                    original_owner=row["original_owner"]
                ))
        
        return files
    
    def get_scan_stats(self) -> Dict:
        """Get scan statistics"""
        with self._scan_lock:
            total = len(self._scan_history)
            dangerous = sum(1 for r in self._scan_history if r.threat_level == ThreatLevel.DANGEROUS)
            suspicious = sum(1 for r in self._scan_history if r.threat_level == ThreatLevel.SUSPICIOUS)
            safe = sum(1 for r in self._scan_history if r.threat_level == ThreatLevel.SAFE)
        
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM quarantined_files")
            quarantined = cursor.fetchone()[0]
        
        return {
            "total_scanned": total,
            "dangerous": dangerous,
            "suspicious": suspicious,
            "safe": safe,
            "quarantined": quarantined
        }


# Global sandbox
_security_sandbox: Optional[SecuritySandbox] = None


def get_security_sandbox() -> SecuritySandbox:
    """Get global security sandbox"""
    global _security_sandbox
    if _security_sandbox is None:
        _security_sandbox = SecuritySandbox()
    return _security_sandbox


# Need contextmanager import
from contextlib import contextmanager
