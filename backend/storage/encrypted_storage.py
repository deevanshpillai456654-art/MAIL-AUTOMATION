"""
Encrypted Storage Manager - AES-256-GCM encryption for attachments

Features:
- Per-attachment encryption keys
- Streaming encryption/decryption
- Key derivation from master key
- Integrity verification (AEAD)
"""

import hashlib
import logging
import secrets
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("storage.encryption")


class EncryptionError(Exception):
    """Encryption errors"""
    pass


class KeyDerivationFunction(Enum):
    """KDF options"""
    PBKDF2 = "pbkdf2"
    ARGON2 = "argon2"


@dataclass
class EncryptionResult:
    """Result of encryption operation"""
    ciphertext: bytes
    nonce: bytes
    key_id: str
    auth_tag: Optional[bytes] = None


@dataclass
class EncryptionStats:
    """Encryption statistics"""
    encrypted_files: int = 0
    decrypted_files: int = 0
    failed_decryptions: int = 0
    total_bytes_encrypted: int = 0
    total_bytes_decrypted: int = 0


class EncryptedStorageManager:
    """
    AES-256-GCM encrypted storage manager.
    
    Features:
    - Per-attachment encryption keys (derived from master)
    - Streaming encryption for large files
    - AEAD integrity verification
    - Key rotation support
    """

    def __init__(
        self,
        storage_root: str = "./data/storage/encrypted",
        master_key: Optional[bytes] = None,
        kdf: KeyDerivationFunction = KeyDerivationFunction.PBKDF2,
        kdf_iterations: int = 100000,
        nonce_size: int = 12
    ):
        self.storage_root = Path(storage_root)
        self.kdf = kdf
        self.kdf_iterations = kdf_iterations
        self.nonce_size = nonce_size

        if master_key is None:
            self._master_key = self._generate_master_key()
        else:
            self._master_key = master_key

        self._ensure_directories()

        self._key_cache: dict = {}
        self._key_map: dict = {}
        self._lock = threading.Lock()

        self._stats = EncryptionStats()

        self._cryptography_available = False
        self._try_import_crypto()

        logger.info("Encrypted storage manager initialized")

    def _ensure_directories(self):
        """Create storage directories"""
        dirs = ["data", "keys", "temp"]
        for d in dirs:
            (self.storage_root / d).mkdir(parents=True, exist_ok=True)

    def _generate_master_key(self) -> bytes:
        """Generate a new master key"""
        return secrets.token_bytes(32)

    def _try_import_crypto(self):
        """Try to import cryptography library"""
        try:
            from cryptography.hazmat.backends import default_backend
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

            self._AESGCM = AESGCM
            self._PBKDF2 = PBKDF2HMAC
            self._hashes = hashes
            self._default_backend = default_backend

            self._cryptography_available = True
            logger.info("Cryptography library available")
        except ImportError:
            logger.warning("Cryptography not available - using fallback mode")

    def _derive_key(self, key_id: str) -> bytes:
        """Derive encryption key from master key"""
        if key_id in self._key_cache:
            return self._key_cache[key_id]

        if self._cryptography_available:
            kdf = self._PBKDF2(
                algorithm=self._hashes.SHA256(),
                length=32,
                salt=key_id.encode()[:16],
                iterations=self.kdf_iterations,
                backend=self._default_backend()
            )
            derived_key = kdf.derive(self._master_key)
        else:
            derived_key = hashlib.pbkdf2_hmac(
                'sha256',
                self._master_key,
                key_id.encode()[:16],
                self.kdf_iterations
            )

        self._key_cache[key_id] = derived_key
        return derived_key

    def generate_key_id(self) -> str:
        """Generate a unique key ID"""
        return secrets.token_hex(16)

    def encrypt(
        self,
        data: bytes,
        key_id: Optional[str] = None
    ) -> EncryptionResult:
        """
        Encrypt data using AES-256-GCM.
        
        Returns:
            EncryptionResult with ciphertext, nonce, and key_id
        """
        if key_id is None:
            key_id = self.generate_key_id()

        key = self._derive_key(key_id)
        nonce = secrets.token_bytes(self.nonce_size)

        if self._cryptography_available:
            aesgcm = self._AESGCM(key)
            ciphertext = aesgcm.encrypt(nonce, data, None)
        else:
            ciphertext = self._encrypt_fallback(key, nonce, data)

        with self._lock:
            self._stats.encrypted_files += 1
            self._stats.total_bytes_encrypted += len(data)

        return EncryptionResult(
            ciphertext=ciphertext,
            nonce=nonce,
            key_id=key_id,
            auth_tag=None
        )

    def _encrypt_fallback(self, key: bytes, nonce: bytes, data: bytes) -> bytes:
        """Fallback encryption using CBC (less secure)"""
        import padding
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        padder = padding.Padder()
        padded_data = padder.add(data, 16)

        cipher = Cipher(
            algorithms.AES(key),
            modes.CBC(nonce[:16]),
            backend=default_backend()
        )
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(padded_data) + encryptor.finalize()

        return nonce + ciphertext

    def decrypt(
        self,
        ciphertext: bytes,
        key_id: str,
        nonce: Optional[bytes] = None
    ) -> bytes:
        """
        Decrypt data using AES-256-GCM.
        
        Returns:
            Decrypted plaintext
        """
        if nonce is None:
            nonce = ciphertext[:self.nonce_size]
            ciphertext = ciphertext[self.nonce_size:]

        key = self._derive_key(key_id)

        if self._cryptography_available:
            aesgcm = self._AESGCM(key)
            try:
                plaintext = aesgcm.decrypt(nonce, ciphertext, None)

                with self._lock:
                    self._stats.decrypted_files += 1
                    self._stats.total_bytes_decrypted += len(plaintext)

                return plaintext
            except Exception as e:
                logger.error(f"Decryption failed: {e}")
                with self._lock:
                    self._stats.failed_decryptions += 1
                raise EncryptionError("Decryption failed")
        else:
            return self._decrypt_fallback(key, nonce, ciphertext)

    def _decrypt_fallback(self, key: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
        """Fallback decryption using CBC"""
        import padding
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        cipher = Cipher(
            algorithms.AES(key),
            modes.CBC(nonce[:16]),
            backend=default_backend()
        )
        decryptor = cipher.decryptor()
        padded_data = decryptor.update(ciphertext) + decryptor.finalize()

        unpadder = padding.Unpadder()
        plaintext = unpadder.remove(padded_data, 16)

        with self._lock:
            self._stats.decrypted_files += 1
            self._stats.total_bytes_decrypted += len(plaintext)

        return plaintext

    def encrypt_file(
        self,
        source_path: Path,
        dest_path: Optional[Path] = None,
        key_id: Optional[str] = None
    ) -> Tuple[Path, str]:
        """Encrypt a file"""
        if key_id is None:
            key_id = self.generate_key_id()

        if dest_path is None:
            dest_path = self.storage_root / "data" / f"{source_path.stem}.enc"

        with open(source_path, "rb") as f:
            data = f.read()

        result = self.encrypt(data, key_id)

        dest_path.parent.mkdir(parents=True, exist_ok=True)

        with open(dest_path, "wb") as f:
            f.write(result.nonce)
            f.write(result.ciphertext)

        return dest_path, key_id

    def decrypt_file(
        self,
        source_path: Path,
        key_id: str,
        dest_path: Optional[Path] = None
    ) -> Path:
        """Decrypt a file"""
        with open(source_path, "rb") as f:
            file_data = f.read()

        nonce = file_data[:self.nonce_size]
        ciphertext = file_data[self.nonce_size:]

        plaintext = self.decrypt(ciphertext, key_id, nonce)

        if dest_path is None:
            dest_path = self.storage_root / "temp" / source_path.stem

        dest_path.parent.mkdir(parents=True, exist_ok=True)

        with open(dest_path, "wb") as f:
            f.write(plaintext)

        return dest_path

    def encrypt_stream(
        self,
        input_stream,
        output_path: Path,
        key_id: Optional[str] = None,
        chunk_size: int = 65536
    ) -> str:
        """Encrypt streaming data"""
        if key_id is None:
            key_id = self.generate_key_id()

        key = self._derive_key(key_id)
        nonce = secrets.token_bytes(self.nonce_size)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        if self._cryptography_available:
            aesgcm = self._AESGCM(key)
            with open(output_path, "wb") as f:
                f.write(nonce)

                with aesgcm.stream_writer(f) as writer:
                    while True:
                        chunk = input_stream.read(chunk_size)
                        if not chunk:
                            break
                        writer.write(chunk)
        else:
            with open(output_path, "wb") as f:
                f.write(nonce)
                while True:
                    chunk = input_stream.read(chunk_size)
                    if not chunk:
                        break
                    encrypted = self._encrypt_fallback(key, nonce, chunk)
                    f.write(encrypted)

        with self._lock:
            self._stats.encrypted_files += 1

        return key_id

    def set_master_key(self, master_key: bytes):
        """Update master key (for key rotation)"""
        self._master_key = master_key
        self._key_cache.clear()
        logger.info("Master key updated")

    def get_stats(self) -> EncryptionStats:
        """Get encryption statistics"""
        with self._lock:
            return EncryptionStats(
                encrypted_files=self._stats.encrypted_files,
                decrypted_files=self._stats.decrypted_files,
                failed_decryptions=self._stats.failed_decryptions,
                total_bytes_encrypted=self._stats.total_bytes_encrypted,
                total_bytes_decrypted=self._stats.total_bytes_decrypted
            )


encrypted_storage = EncryptedStorageManager()
