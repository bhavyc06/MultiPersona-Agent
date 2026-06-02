"""
Fernet symmetric encryption for MemoryEntry fields.

If MEMORY_ENCRYPTION_KEY is not set, an ephemeral dev key is generated and
a warning is logged. Data encrypted with the ephemeral key cannot be read
after a server restart — set MEMORY_ENCRYPTION_KEY in .env for persistence.
"""
import logging
import threading
import warnings

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None
_lock = threading.Lock()


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet

    with _lock:
        if _fernet is not None:
            return _fernet

        from backend.config import settings
        key = settings.memory_encryption_key

        if not key:
            key = Fernet.generate_key().decode()
            msg = (
                "MEMORY_ENCRYPTION_KEY is not set — using an ephemeral dev key. "
                "Encrypted memory entries will NOT be readable after server restart. "
                "Set MEMORY_ENCRYPTION_KEY in .env for persistence."
            )
            logger.warning(msg)
            warnings.warn(msg, UserWarning, stacklevel=3)

        _fernet = Fernet(key.encode() if isinstance(key, str) else key)

    return _fernet


def encrypt_text(text: str) -> str:
    """Encrypt a UTF-8 string. Returns a base64-encoded ciphertext string."""
    return _get_fernet().encrypt(text.encode()).decode()


def decrypt_text(encrypted: str) -> str:
    """Decrypt a ciphertext string produced by encrypt_text."""
    return _get_fernet().decrypt(encrypted.encode()).decode()
