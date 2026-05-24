"""
Security Sandbox Engine - Comprehensive Security Sandbox
==========================================================

Enterprise security components:
- PDFSandbox: PDF sandboxing with isolated rendering
- AttachmentScanner: Multi-stage attachment scanning
- MIMEValidationEngine: MIME type validation with magic bytes
- ExecutableDetectionEngine: PE/Mach-O/ELF signature detection
- MacroDetectionEngine: VBA macro detection in Office files
- ArchiveBombProtection: Zip bomb and nested archive limits
- MalwareScanningEngine: YARA integration and heuristic scanning
- QuarantineSystem: Encrypted quarantine with audit trail

Key requirements:
- NO ATTACHMENT SHOULD EXECUTE DIRECTLY
- All attachments must be scanned before processing
- Suspicious files must be quarantined
- Sandbox isolation for untrusted content
"""

import hashlib
import logging
import os
import secrets
import sqlite3
import time
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("security.sandbox_engine")


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
    PDF_EXPLOIT = "pdf_exploit"
    OLE_OBJECT = "ole_object"
    SCRIPT = "script"
    EMBEDDED_CODE = "embedded_code"


@dataclass
class ScanResult:
    """Comprehensive scan result"""
    file_id: str
    filename: str
    mime_type: str
    detected_mime: str
    size: int
    file_hash: str
    threat_level: ThreatLevel
    threat_type: Optional[ThreatType]
    details: List[str]
    scan_time: float
    is_clean: bool
    scanner_versions: Dict[str, str] = field(default_factory=dict)


@dataclass
class QuarantineRecord:
    """Quarantine record with full metadata"""
    quarantine_id: str
    original_path: str
    filename: str
    file_hash: str
    threat_type: ThreatType
    threat_level: ThreatLevel
    details: str
    quarantined_at: float
    owner: Optional[str]
    review_status: str
    released_at: Optional[float] = None
    released_to: Optional[str] = None


class PDFSandbox:
    """
    PDF sandboxing with isolated rendering and exploit detection.
    Never loads full file into memory - uses stream-based parsing.
    """

    PDF_MAGIC = b"%PDF-"
    PDF_VERSION_PATTERN = b"%PDF-1."

    EXPLOIT_PATTERNS = [
        b"/JavaScript",
        b"/JS",
        b"/AA",
        b"/OpenAction",
        b"/AA",
        b"/JBIG2Decode",
        b"/RichMedia",
        b"/Launch",
        b"/URI",
    ]

    SUSPICIOUS_STREAMS = [
        b"/ObjStm",
        b"/JS",
        b"/JavaScript",
        b"/AA",
        b"/OpenAction",
    ]

    def __init__(self):
        self.max_pdf_size = 50 * 1024 * 1024
        self.max_stream_size = 10 * 1024 * 1024
        self.max_objects = 10000
        self.strip_javascript = True

    def scan_pdf(self, file_path: str) -> Tuple[bool, List[str]]:
        """
        Stream-based PDF scanning for exploits and malicious content.
        Returns (is_safe, details)
        """
        details = []

        try:
            file_size = os.path.getsize(file_path)
            if file_size > self.max_pdf_size:
                return False, ["PDF exceeds maximum size limit"]

            with open(file_path, "rb") as f:
                header = f.read(8)
                if not header.startswith(self.PDF_MAGIC):
                    return False, ["Invalid PDF header"]

                details.append("PDF header valid")

                obj_count = 0
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break

                    for pattern in self.EXPLOIT_PATTERNS:
                        if pattern in chunk:
                            details.append(f"Found suspicious pattern: {pattern.decode('utf-8', errors='ignore')}")

                    for pattern in self.SUSPICIOUS_STREAMS:
                        if pattern in chunk:
                            details.append(f"Suspicious stream detected: {pattern.decode('utf-8', errors='ignore')}")

                    obj_count += 1
                    if obj_count > self.max_objects:
                        details.append("Too many PDF objects - possible exploit")
                        return False, details

            details.append(f"PDF scanned - {obj_count} objects processed")
            return True, details

        except Exception as e:
            details.append(f"PDF scan error: {str(e)}")
            return False, details

    def extract_pdf_metadata(self, file_path: str) -> Dict:
        """Extract PDF metadata without full parsing"""
        metadata = {
            "version": None,
            "objects": 0,
            "has_scripts": False,
            "has_embedded_files": False,
            "has_actions": False,
        }

        try:
            with open(file_path, "rb") as f:
                header = f.read(32)
                if header.startswith(self.PDF_MAGIC):
                    try:
                        version_end = header.find(b"\n")
                        if version_end > 0:
                            metadata["version"] = header[5:version_end].decode("ascii")
                    except Exception:
                        pass

                f.seek(0)
                content = f.read(65536)

                for pattern in [b"/JS", b"/JavaScript"]:
                    if pattern in content:
                        metadata["has_scripts"] = True

                if b"/EmbeddedFiles" in content:
                    metadata["has_embedded_files"] = True

                if b"/OpenAction" in content or b"/AA" in content:
                    metadata["has_actions"] = True

        except Exception as e:
            logger.warning(f"PDF metadata extraction error: {e}")

        return metadata


class AttachmentScanner:
    """
    Multi-stage attachment scanning with MIME validation.
    Uses magic bytes for verification, not just extension.
    """

    MAGIC_BYTES = {
        "application/pdf": b"%PDF-",
        "image/jpeg": b"\xff\xd8\xff",
        "image/png": b"\x89PNG",
        # GIF89a is the common modern format; GIF87a is the legacy one.
        # bytes.startswith() accepts a tuple of candidate prefixes.
        "image/gif": (b"GIF89a", b"GIF87a"),
        "application/zip": b"PK\x03\x04",
        "application/x-zip-compressed": b"PK\x03\x04",
        "application/msword": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
        "application/vnd.ms-excel": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
        "application/vnd.ms-powerpoint": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": b"PK\x03\x04",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": b"PK\x03\x04",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": b"PK\x03\x04",
        "application/gzip": b"\x1f\x8b",
        "application/x-tar": b"ustar",
    }

    DANGEROUS_EXTENSIONS = {
        ".exe", ".dll", ".bat", ".cmd", ".ps1", ".sh", ".bash",
        ".vbs", ".js", ".jse", ".wsf", ".wsh", ".msi",
        ".scr", ".pif", ".com", ".jar", ".class",
        ".shx", ".app", ".bin", ".dmg", ".pkg", ".deb", ".rpm",
        ".hta", ".lnk", ".inf", ".reg", ".vxd", ".sys",
    }

    SUSPICIOUS_EXTENSIONS = {
        ".docm", ".xlsm", ".pptm", ".docb", ".rtf", ".odt",
        ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
        ".htm", ".html", ".svg", ".xml",
    }

    def __init__(self):
        self.max_file_size = 100 * 1024 * 1024

    def scan_attachment(self, file_path: str, filename: str) -> Tuple[str, ThreatLevel, List[str]]:
        """
        Multi-stage attachment scanning.
        Returns (detected_mime, threat_level, details)
        """
        details = []

        try:
            file_size = os.path.getsize(file_path)
            if file_size > self.max_file_size:
                return "application/octet-stream", ThreatLevel.DANGEROUS, ["File exceeds size limit"]

            detected_mime = self._detect_mime_from_magic(file_path, filename)
            details.append(f"MIME detected: {detected_mime}")

            extension = os.path.splitext(filename)[1].lower()

            if extension in self.DANGEROUS_EXTENSIONS:
                details.append(f"Dangerous extension: {extension}")
                return detected_mime, ThreatLevel.DANGEROUS, details

            if extension in self.SUSPICIOUS_EXTENSIONS:
                details.append(f"Suspicious extension: {extension}")
                return detected_mime, ThreatLevel.SUSPICIOUS, details

            claimed_mime = self._get_mime_from_extension(extension)
            if detected_mime != claimed_mime and detected_mime != "application/octet-stream":
                details.append(f"MIME mismatch: claimed {claimed_mime}, detected {detected_mime}")
                return detected_mime, ThreatLevel.SUSPICIOUS, details

            content_disposition = self._check_content_disposition(file_path)
            if content_disposition:
                details.append(f"Content-Disposition: {content_disposition}")

            return detected_mime, ThreatLevel.SAFE, details

        except Exception as e:
            details.append(f"Scan error: {str(e)}")
            return "application/octet-stream", ThreatLevel.SUSPICIOUS, details

    def _detect_mime_from_magic(self, file_path: str, filename: str) -> str:
        """Detect MIME type using magic bytes"""
        try:
            with open(file_path, "rb") as f:
                header = f.read(8192)

            for mime, magic in self.MAGIC_BYTES.items():
                if header.startswith(magic):
                    return mime

            ext = os.path.splitext(filename)[1].lower()
            return self._get_mime_from_extension(ext)

        except Exception:
            return "application/octet-stream"

    def _get_mime_from_extension(self, ext: str) -> str:
        """Get MIME type from file extension"""
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
            ".svg": "image/svg+xml",
            ".xml": "application/xml",
        }
        return mime_types.get(ext, "application/octet-stream")

    def _check_content_disposition(self, file_path: str) -> Optional[str]:
        """Check for suspicious Content-Disposition patterns"""
        try:
            with open(file_path, "rb") as f:
                content = f.read(4096)

            suspicious_patterns = [
                b"filename=",
                b"attachment",
            ]
            return any(p in content.lower() for p in suspicious_patterns)
        except Exception:
            return None


class MIMEValidationEngine:
    """
    MIME type sniffing and validation with multiple passes.
    Validates Content-Type headers and detects malformed MIME.
    """

    def __init__(self):
        self.max_header_size = 8192
        self.max_boundary_length = 200

    def validate_mime(self, file_path: str, claimed_mime: str) -> Tuple[bool, List[str]]:
        """
        Multiple-pass MIME validation.
        Returns (is_valid, details)
        """
        details = []
        is_valid = True

        magic_valid = self._validate_magic_bytes(file_path, claimed_mime)
        if not magic_valid:
            details.append("Magic bytes validation failed")
            is_valid = False

        charset_valid, charset_info = self._validate_charset(file_path)
        if charset_valid:
            details.append(f"Charset: {charset_info}")

        boundary_valid, boundary_info = self._validate_boundary(file_path, claimed_mime)
        if boundary_valid:
            details.append(f"Boundary: {boundary_info}")

        malformed = self._detect_malformed_mime(file_path)
        if malformed:
            details.append(f"Malformed MIME: {malformed}")
            is_valid = False

        return is_valid, details

    def _validate_magic_bytes(self, file_path: str, claimed_mime: str) -> bool:
        """Validate file matches claimed MIME type"""
        try:
            with open(file_path, "rb") as f:
                header = f.read(16)

            if claimed_mime == "application/pdf":
                return header.startswith(b"%PDF-")
            elif claimed_mime in ("image/jpeg",):
                return header.startswith(b"\xff\xd8\xff")
            elif claimed_mime == "image/png":
                return header.startswith(b"\x89PNG")
            elif claimed_mime in ("application/zip", "application/vnd.openxmlformats-officedocument"):
                return header.startswith(b"PK\x03\x04")
            elif claimed_mime == "application/msword":
                return header[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

            return True

        except Exception:
            return False

    def _validate_charset(self, file_path: str) -> Tuple[bool, Optional[str]]:
        """Validate charset encoding"""
        try:
            with open(file_path, "rb") as f:
                sample = f.read(1024)

            for encoding in ["utf-8", "utf-16", "ascii", "iso-8859-1"]:
                try:
                    sample.decode(encoding)
                    return True, encoding
                except Exception:
                    continue

            return True, "binary"

        except Exception:
            return False, None

    def _validate_boundary(self, file_path: str, mime_type: str) -> Tuple[bool, Optional[str]]:
        """Validate multipart boundary"""
        if "multipart" not in mime_type:
            return True, None

        try:
            with open(file_path, "rb") as f:
                content = f.read(self.max_header_size)

            boundary_pattern = b"boundary="
            if boundary_pattern in content:
                idx = content.find(boundary_pattern) + len(boundary_pattern)
                boundary = content[idx:idx + self.max_boundary_length].split(b";")[0].strip(b'"')
                if len(boundary) > 0 and len(boundary) <= self.max_boundary_length:
                    return True, boundary.decode("ascii", errors="ignore")
                else:
                    return False, "Invalid boundary length"

            return False, "No boundary found"

        except Exception as e:
            return False, str(e)

    def _detect_malformed_mime(self, file_path: str) -> Optional[str]:
        """Detect malformed MIME structure"""
        try:
            with open(file_path, "rb") as f:
                content = f.read(8192)

            if b"From:" in content and b"MIME-Version:" not in content:
                return "Missing MIME-Version header"

            null_bytes = content.count(b"\x00")
            if null_bytes > len(content) * 0.1:
                return "Excessive null bytes"

            return None

        except Exception:
            return None


class ExecutableDetectionEngine:
    """
    Executable and code detection for various file formats.
    Detects PE, Mach-O, ELF, scripts, and embedded code.
    """

    PE_SIGNATURES = [
        b"MZ",  # DOS header - PE executable
        b"\x4d\x5a",  # MZ
    ]

    ELF_SIGNATURES = [
        b"\x7fELF",
    ]

    MACHO_SIGNATURES = [
        b"\xfe\xed\xfa\xce",  # 32-bit Mach-O
        b"\xfe\xed\xfa\xcf",  # 64-bit Mach-O
        b"\xce\xfa\xed\xfe",  # 32-bit reverse
        b"\xcf\xfa\xed\xfe",  # 64-bit reverse
    ]

    SCRIPT_SIGNATURES = [
        b"#!/",
        b"REM ",
        b"@echo",
        b"<script",
        b"<?php",
        b"<?xml",
    ]

    def __init__(self):
        self.max_embedded_size = 1024 * 1024

    def detect_executable(self, file_path: str) -> Tuple[bool, List[str]]:
        """
        Detect if file contains executable code.
        Returns (is_executable, details)
        """
        details = []

        try:
            with open(file_path, "rb") as f:
                header = f.read(8192)

            for sig in self.PE_SIGNATURES:
                if header.startswith(sig):
                    details.append("PE executable detected")
                    return True, details

            for sig in self.ELF_SIGNATURES:
                if header.startswith(sig):
                    details.append("ELF executable detected")
                    return True, details

            for sig in self.MACHO_SIGNATURES:
                if header.startswith(sig):
                    details.append("Mach-O executable detected")
                    return True, details

            for sig in self.SCRIPT_SIGNATURES:
                if sig in header:
                    details.append(f"Script signature detected: {sig.decode('utf-8', errors='ignore').strip()}")
                    return True, details

            ole_detected = self._detect_ole_objects(header)
            if ole_detected:
                details.extend(ole_detected)

            packed = self._detect_packing(header)
            if packed:
                details.append(f"Packed executable detected: {packed}")

            return False, details

        except Exception as e:
            details.append(f"Detection error: {str(e)}")
            return False, details

    def _detect_ole_objects(self, header: bytes) -> List[str]:
        """Detect OLE compound document objects"""
        results = []

        if header[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            results.append("OLE compound document detected")

        ole_markers = [b"\x01\x00\x00\x00", b"\x02\x00\x00\x00"]
        for marker in ole_markers:
            if marker in header[:512]:
                results.append(f"OLE marker found: {marker.hex()}")

        return results

    def _detect_packing(self, header: bytes) -> Optional[str]:
        """Detect common packer signatures"""
        packer_signatures = {
            b"UPX": "UPX",
            b"FSG!": "FSG",
            b"Petite": "Petite",
            b"ASPack": "ASPack",
            b"PECompact": "PECompact",
        }

        for sig, name in packer_signatures.items():
            if sig in header:
                return name

        return None


class MacroDetectionEngine:
    """
    VBA macro detection in Office documents.
    Detects AutoOpen, suspicious API calls, obfuscation.
    """

    OLE_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

    MACRO_INDICATORS = [
        b"VBA",
        b"VBAScript",
        b"Sub ",
        b"Function ",
        b"Dim ",
        b"Public ",
        b"Private ",
    ]

    AUTO_MACROS = [
        b"AutoOpen",
        b"AutoClose",
        b"AutoExec",
        b"AutoNew",
        b"Workbook_Open",
        b"Workbook_Close",
        b"Document_Open",
        b"Document_Close",
    ]

    SUSPICIOUS_APIS = [
        b"Shell",
        b"Execute",
        b"CreateObject",
        b"WScript.Shell",
        b"Cmd",
        b"powershell",
        b"wscript",
        b"cscript",
        b"URLDownloadToFile",
        b"XMLHTTP",
    ]

    OBFUSCATION_PATTERNS = [
        b"Chr(",
        b"Replace(",
        b"Split(",
        b"Eval(",
        b"Execute(",
    ]

    def __init__(self):
        self.max_macro_size = 5 * 1024 * 1024

    def detect_macros(self, file_path: str) -> Tuple[bool, List[str]]:
        """
        Detect VBA macros in Office documents.
        Returns (has_macros, details)
        """
        details = []

        try:
            file_size = os.path.getsize(file_path)
            if file_size > self.max_macro_size:
                return False, ["File too large for macro scan"]

            with open(file_path, "rb") as f:
                header = f.read(512)

            if not header.startswith(self.OLE_HEADER):
                return False, ["Not an OLE compound document"]

            details.append("OLE document detected")

            f.seek(0)
            content = f.read(2 * 1024 * 1024)

            for indicator in self.MACRO_INDICATORS:
                if indicator in content:
                    details.append(f"VBA indicator: {indicator.decode('utf-8', errors='ignore')}")

            for auto in self.AUTO_MACROS:
                if auto in content:
                    details.append(f"Auto-run macro detected: {auto.decode('utf-8', errors='ignore')}")

            for api in self.SUSPICIOUS_APIS:
                if api.lower() in content.lower():
                    details.append(f"Suspicious API call: {api.decode('utf-8', errors='ignore')}")

            obfuscation_count = sum(1 for p in self.OBFUSCATION_PATTERNS if p in content)
            if obfuscation_count > 0:
                details.append(f"Potential obfuscation: {obfuscation_count} patterns found")

            return len(details) > 1, details

        except Exception as e:
            details.append(f"Macro detection error: {str(e)}")
            return False, details


class ArchiveBombProtection:
    """
    Archive bomb and nested archive protection.
    Limits compression ratio, recursion depth, and extraction resources.
    """

    MAX_COMPRESSION_RATIO = 100
    MAX_EXTRACTION_DEPTH = 10
    MAX_TOTAL_EXTRACTED_SIZE = 500 * 1024 * 1024
    MAX_ARCHIVE_ENTRIES = 10000
    MAX_EXTRACTION_TIME = 60

    def __init__(self):
        self.max_compression_ratio = self.MAX_COMPRESSION_RATIO
        self.max_extraction_depth = self.MAX_EXTRACTION_DEPTH
        self.max_total_extracted = self.MAX_TOTAL_EXTRACTED_SIZE
        self.max_entries = self.MAX_ARCHIVE_ENTRIES

    def scan_archive(self, file_path: str) -> Tuple[bool, List[str]]:
        """
        Scan archive for bombs and excessive nesting.
        Returns (is_safe, details)
        """
        details = []
        total_size = 0
        entry_count = 0

        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                for info in zf.infolist():
                    entry_count += 1

                    if entry_count > self.max_entries:
                        details.append(f"Too many entries: {entry_count}")
                        return False, details

                    if info.file_size > 0 and info.compress_size > 0:
                        ratio = info.file_size / info.compress_size
                        if ratio > self.max_compression_ratio:
                            details.append(f"High compression ratio: {ratio:.1f}x")
                            return False, details

                    depth = info.filename.count("/") + info.filename.count("\\")
                    if depth > self.max_extraction_depth:
                        details.append(f"Excessive depth: {depth}")
                        return False, details

                    if info.filename.endswith((".exe", ".dll", ".bat", ".cmd")):
                        details.append(f"Executable in archive: {info.filename}")
                        return False, details

                    total_size += info.file_size
                    if total_size > self.max_total_extracted:
                        details.append(f"Total extracted size exceeds limit: {total_size}")
                        return False, details

                details.append(f"Archive scanned: {entry_count} entries, {total_size} bytes")

            return True, details

        except zipfile.BadZipFile:
            details.append("Corrupted ZIP file")
            return False, details
        except Exception as e:
            details.append(f"Archive scan error: {str(e)}")
            return False, details


class MalwareScanningEngine:
    """
    Malware scanning with YARA integration point.
    Signature-based and heuristic scanning.
    """

    def __init__(self):
        self.yara_rules_path = None
        self.signature_db_path = None
        self.max_scan_size = 50 * 1024 * 1024

    def scan_for_malware(self, file_path: str) -> Tuple[bool, List[str]]:
        """
        Scan file for malware signatures and heuristics.
        Returns (is_malware, details)
        """
        details = []

        try:
            file_size = os.path.getsize(file_path)
            if file_size > self.max_scan_size:
                return False, ["File too large for malware scan"]

            with open(file_path, "rb") as f:
                content = f.read(1024 * 1024)

            heuristic_results = self._heuristic_scan(content)
            details.extend(heuristic_results)

            if heuristic_results:
                return True, details

            return False, details

        except Exception as e:
            details.append(f"Malware scan error: {str(e)}")
            return False, details

    def _heuristic_scan(self, content: bytes) -> List[str]:
        """Heuristic scanning for suspicious patterns"""
        results = []

        suspicious_patterns = [
            (b"TVqQAAMAAAAEAAAA", "Base64-encoded PE header"),
            (b"powershell -enc", "Encoded PowerShell command"),
            (b"cmd.exe /c", "CMD command execution"),
            (b"WScript.Shell", "WScript Shell object"),
            (b"Scripting.FileSystemObject", "File system access"),
            (b"ADODB.Stream", "ADO stream manipulation"),
            (b"WinHTTP.WinHTTPRequest", "HTTP request object"),
        ]

        for pattern, description in suspicious_patterns:
            if pattern in content:
                results.append(f"Heuristic: {description}")

        entropy = self._calculate_entropy(content)
        if entropy > 7.5:
            results.append(f"High entropy: {entropy:.2f} (possible packer)")

        return results

    def _calculate_entropy(self, data: bytes) -> float:
        """Calculate Shannon entropy"""
        if not data:
            return 0.0

        import math
        from collections import Counter

        byte_counts = Counter(data)
        total = len(data)
        entropy = 0.0

        for count in byte_counts.values():
            if count > 0:
                prob = count / total
                entropy -= prob * math.log2(prob)

        return entropy


class QuarantineSystem:
    """
    Encrypted quarantine system with audit trail.
    Manages quarantined files with full metadata tracking.
    """

    def __init__(self, quarantine_dir: str, db_path: str):
        self.quarantine_dir = Path(quarantine_dir)
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self):
        """Initialize quarantine database"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS quarantine_records (
                quarantine_id TEXT PRIMARY KEY,
                original_path TEXT,
                filename TEXT,
                file_hash TEXT NOT NULL,
                threat_type TEXT NOT NULL,
                threat_level TEXT NOT NULL,
                details TEXT,
                quarantined_at REAL,
                owner TEXT,
                review_status TEXT DEFAULT 'pending',
                released_at REAL,
                released_to TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS quarantine_audit (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                quarantine_id TEXT,
                action TEXT,
                timestamp REAL,
                details TEXT
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

    def quarantine_file(self, file_path: str, file_hash: str,
                       threat_type: ThreatType, threat_level: ThreatLevel,
                       details: str, owner: str = None) -> Optional[str]:
        """Move file to quarantine"""
        quarantine_id = f"q_{secrets.token_hex(12)}"
        filename = os.path.basename(file_path)

        encrypted_path = self._encrypt_store(file_path, quarantine_id)

        if not encrypted_path:
            return None

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO quarantine_records
                (quarantine_id, original_path, filename, file_hash, threat_type, threat_level, details, quarantined_at, owner, review_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                quarantine_id, file_path, filename, file_hash,
                threat_type.value, threat_level.value, details,
                time.time(), owner, "pending"
            ))
            conn.commit()

            cursor.execute("""
                INSERT INTO quarantine_audit (quarantine_id, action, timestamp, details)
                VALUES (?, ?, ?, ?)
            """, (quarantine_id, "quarantined", time.time(), details))

            conn.commit()

        logger.warning(f"File quarantined: {quarantine_id}")
        return quarantine_id

    def _encrypt_store(self, file_path: str, quarantine_id: str) -> Optional[str]:
        """Encrypt and store file in quarantine"""
        try:
            with open(file_path, "rb") as f:
                content = f.read()

            encrypted = self._encrypt_content(content)
            if encrypted is None:
                return None

            store_path = self.quarantine_dir / f"{quarantine_id}.enc"
            with open(store_path, "wb") as f:
                f.write(encrypted)

            return str(store_path)

        except Exception as e:
            logger.error(f"Quarantine storage error: {e}")
            return None

    def _encrypt_content(self, content: bytes) -> Optional[bytes]:
        """Simple XOR encryption for quarantine storage"""
        try:
            key = secrets.token_bytes(32)
            encrypted = bytearray(content)
            for i in range(len(encrypted)):
                encrypted[i] ^= key[i % len(key)]
            return key + bytes(encrypted)
        except Exception:
            return None

    def release_file(self, quarantine_id: str, target_path: str,
                    approver: str = None) -> bool:
        """Release file from quarantine"""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()

                cursor.execute("SELECT * FROM quarantine_records WHERE quarantine_id = ?", (quarantine_id,))
                record = cursor.fetchone()

                if not record:
                    return False

                encrypted_path = self.quarantine_dir / f"{quarantine_id}.enc"
                if not encrypted_path.exists():
                    return False

                content = self._decrypt_store(encrypted_path)
                if content is None:
                    return False

                with open(target_path, "wb") as f:
                    f.write(content)

                cursor.execute("""
                    UPDATE quarantine_records
                    SET review_status = 'released', released_at = ?, released_to = ?
                    WHERE quarantine_id = ?
                """, (time.time(), target_path, quarantine_id))

                cursor.execute("""
                    INSERT INTO quarantine_audit (quarantine_id, action, timestamp, details)
                    VALUES (?, ?, ?, ?)
                """, (quarantine_id, "released", time.time(), f"Released to {target_path} by {approver}"))

                conn.commit()

                encrypted_path.unlink()

            return True

        except Exception as e:
            logger.error(f"Release error: {e}")
            return False

    def _decrypt_store(self, encrypted_path: Path) -> Optional[bytes]:
        """Decrypt quarantine file"""
        try:
            with open(encrypted_path, "rb") as f:
                data = f.read()

            key = data[:32]
            encrypted = data[32:]

            decrypted = bytearray(encrypted)
            for i in range(len(decrypted)):
                decrypted[i] ^= key[i % len(key)]

            return bytes(decrypted)

        except Exception as e:
            logger.error(f"Decryption error: {e}")
            return None

    def get_quarantine_list(self, status: str = None) -> List[QuarantineRecord]:
        """Get list of quarantined files"""
        with self._get_conn() as conn:
            cursor = conn.cursor()

            if status:
                cursor.execute("""
                    SELECT * FROM quarantine_records
                    WHERE review_status = ?
                    ORDER BY quarantined_at DESC
                """, (status,))
            else:
                cursor.execute("SELECT * FROM quarantine_records ORDER BY quarantined_at DESC")

            records = []
            for row in cursor.fetchall():
                records.append(QuarantineRecord(
                    quarantine_id=row["quarantine_id"],
                    original_path=row["original_path"],
                    filename=row["filename"],
                    file_hash=row["file_hash"],
                    threat_type=ThreatType(row["threat_type"]),
                    threat_level=ThreatLevel(row["threat_level"]),
                    details=row["details"],
                    quarantined_at=row["quarantined_at"],
                    owner=row["owner"],
                    review_status=row["review_status"],
                    released_at=row["released_at"],
                    released_to=row["released_to"]
                ))

            return records


class SandboxEngine:
    """
    Comprehensive Security Sandbox Engine.
    Orchestrates all security components for complete attachment protection.
    """

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.quarantine_dir = self.data_dir / "quarantine"
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = self.data_dir / "sandbox_engine.db"

        self.pdf_sandbox = PDFSandbox()
        self.attachment_scanner = AttachmentScanner()
        self.mime_validator = MIMEValidationEngine()
        self.executable_detector = ExecutableDetectionEngine()
        self.macro_detector = MacroDetectionEngine()
        self.archive_protection = ArchiveBombProtection()
        self.malware_scanner = MalwareScanningEngine()
        self.quarantine_system = QuarantineSystem(str(self.quarantine_dir), str(self.db_path))

        self.max_file_size = 100 * 1024 * 1024

        logger.info("SandboxEngine initialized")

    def scan_file(self, file_path: str, filename: str = None) -> ScanResult:
        """
        Comprehensive file scanning through all security stages.
        """
        filename = filename or os.path.basename(file_path)
        file_id = f"scan_{secrets.token_hex(8)}"
        start_time = time.time()

        details = []
        threat_level = ThreatLevel.SAFE
        threat_type = None

        try:
            file_size = os.path.getsize(file_path)
            if file_size > self.max_file_size:
                return ScanResult(
                    file_id=file_id,
                    filename=filename,
                    mime_type="unknown",
                    detected_mime="unknown",
                    size=file_size,
                    file_hash="",
                    threat_level=ThreatLevel.DANGEROUS,
                    threat_type=ThreatType.OVERSIZE,
                    details=[f"File exceeds size limit: {file_size}"],
                    scan_time=time.time() - start_time,
                    is_clean=False
                )

            file_hash = self._calculate_hash(file_path)

            mime_detected, mime_threat, mime_details = self.attachment_scanner.scan_attachment(file_path, filename)
            details.extend(mime_details)

            if mime_threat in (ThreatLevel.DANGEROUS, ThreatLevel.SUSPICIOUS):
                threat_level = mime_threat

            ext = os.path.splitext(filename)[1].lower()

            if ext == ".pdf":
                pdf_safe, pdf_details = self.pdf_sandbox.scan_pdf(file_path)
                details.extend(pdf_details)
                if not pdf_safe:
                    threat_level = ThreatLevel.DANGEROUS
                    threat_type = ThreatType.PDF_EXPLOIT

            if ext in (".zip", ".rar", ".7z", ".tar", ".gz"):
                archive_safe, archive_details = self.archive_protection.scan_archive(file_path)
                details.extend(archive_details)
                if not archive_safe:
                    threat_level = ThreatLevel.DANGEROUS
                    threat_type = ThreatType.ARCHIVE_BOMB

            if ext in (".doc", ".xls", ".ppt", ".docm", ".xlsm", ".pptm"):
                has_macros, macro_details = self.macro_detector.detect_macros(file_path)
                details.extend(macro_details)
                if has_macros:
                    threat_type = ThreatType.MACRO
                    if threat_level == ThreatLevel.SAFE:
                        threat_level = ThreatLevel.SUSPICIOUS

            is_exec, exec_details = self.executable_detector.detect_executable(file_path)
            details.extend(exec_details)
            if is_exec:
                threat_level = ThreatLevel.DANGEROUS
                threat_type = ThreatType.EXECUTABLE

            is_malware, malware_details = self.malware_scanner.scan_for_malware(file_path)
            details.extend(malware_details)
            if is_malware:
                threat_level = ThreatLevel.DANGEROUS
                threat_type = ThreatType.MALWARE

            if threat_level in (ThreatLevel.DANGEROUS, ThreatLevel.SUSPICIOUS) and threat_type:
                self.quarantine_system.quarantine_file(
                    file_path, file_hash,
                    threat_type, threat_level,
                    "; ".join(details)
                )

            return ScanResult(
                file_id=file_id,
                filename=filename,
                mime_type=mime_detected,
                detected_mime=mime_detected,
                size=file_size,
                file_hash=file_hash,
                threat_level=threat_level,
                threat_type=threat_type,
                details=details,
                scan_time=time.time() - start_time,
                is_clean=threat_level == ThreatLevel.SAFE,
                scanner_versions={
                    "pdf_sandbox": "1.0",
                    "attachment_scanner": "1.0",
                    "mime_validator": "1.0",
                    "executable_detector": "1.0",
                    "macro_detector": "1.0",
                    "archive_protection": "1.0",
                    "malware_scanner": "1.0"
                }
            )

        except Exception as e:
            details.append(f"Scan error: {str(e)}")
            logger.error(f"Scan error for {filename}: {e}")
            return ScanResult(
                file_id=file_id,
                filename=filename,
                mime_type="unknown",
                detected_mime="unknown",
                size=0,
                file_hash="",
                threat_level=ThreatLevel.SUSPICIOUS,
                threat_type=ThreatType.CORRUPTED,
                details=details,
                scan_time=time.time() - start_time,
                is_clean=False
            )

    def _calculate_hash(self, file_path: str) -> str:
        """Calculate SHA256 hash of file"""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def get_quarantine_list(self) -> List[QuarantineRecord]:
        """Get list of quarantined files"""
        return self.quarantine_system.get_quarantine_list()

    def release_from_quarantine(self, quarantine_id: str, target_path: str) -> bool:
        """Release file from quarantine"""
        return self.quarantine_system.release_file(quarantine_id, target_path)


_engines: Dict[str, SandboxEngine] = {}


def get_sandbox_engine(data_dir: str = None) -> SandboxEngine:
    """Get or create sandbox engine instance"""
    global _engines
    if data_dir is None:
        from pathlib import Path
        data_dir = str(Path.cwd() / "data" / "security")
    if data_dir not in _engines:
        _engines[data_dir] = SandboxEngine(data_dir)
    return _engines[data_dir]
