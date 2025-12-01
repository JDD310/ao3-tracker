"""Password encryption utilities for secure password handling."""

from __future__ import annotations

import base64
import os
from typing import Optional

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.backends import default_backend
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False
    Fernet = None
    PBKDF2HMAC = None
    default_backend = None

# Fixed salt for key derivation (must be consistent)
_KEY_SALT = b'ao3tracker_pw_salt_v1'
_KEY_ITERATIONS = 100000


def _get_fernet_key() -> bytes:
    """
    Get or create Fernet encryption key for password encryption.
    
    Uses a key derived from a master key stored in environment variable
    or generates a default one. In production, set AO3TRACKER_ENCRYPTION_KEY.
    """
    if not CRYPTOGRAPHY_AVAILABLE:
        raise ImportError("cryptography library is required for password encryption. Install with: pip install cryptography")
    
    # Try to get master key from environment
    master_key = os.environ.get("AO3TRACKER_ENCRYPTION_KEY")
    
    if not master_key:
        # Use default key for development (not secure for production!)
        master_key = "ao3tracker_default_key_change_in_production"
    
    # Derive a consistent Fernet key from the master key
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_KEY_SALT,
        iterations=_KEY_ITERATIONS,
        backend=default_backend()
    )
    derived_key = kdf.derive(master_key.encode('utf-8'))
    # Fernet requires a base64-encoded 32-byte key
    fernet_key = base64.urlsafe_b64encode(derived_key)
    return fernet_key


def encrypt_password(password: str) -> str:
    """
    Encrypt a password for temporary storage in memory.
    
    Args:
        password: Plaintext password to encrypt
        
    Returns:
        Base64-encoded encrypted password string
        
    Note:
        This is for encrypting passwords in memory only.
        Passwords should never be stored persistently.
    """
    if not password:
        return ""
    
    if not CRYPTOGRAPHY_AVAILABLE:
        raise ImportError("cryptography library is required for password encryption")
    
    try:
        fernet_key = _get_fernet_key()
        f = Fernet(fernet_key)
        encrypted = f.encrypt(password.encode('utf-8'))
        return encrypted.decode('utf-8')
    except Exception as e:
        raise ValueError(f"Failed to encrypt password: {str(e)}")


def decrypt_password(encrypted_password: str) -> str:
    """
    Decrypt a password from encrypted string.
    
    Args:
        encrypted_password: Base64-encoded encrypted password string
        
    Returns:
        Plaintext password
        
    Note:
        This is for decrypting passwords from memory only.
    """
    if not encrypted_password:
        return ""
    
    if not CRYPTOGRAPHY_AVAILABLE:
        raise ImportError("cryptography library is required for password decryption")
    
    try:
        fernet_key = _get_fernet_key()
        f = Fernet(fernet_key)
        decrypted = f.decrypt(encrypted_password.encode('utf-8'))
        return decrypted.decode('utf-8')
    except Exception as e:
        raise ValueError(f"Failed to decrypt password: {str(e)}")


def clear_password(password: Optional[str]) -> None:
    """
    Attempt to clear password from memory.
    
    Note: Python strings are immutable, so this is best-effort.
    The password may still exist in memory until garbage collected.
    """
    if password:
        # For strings, we can't really clear them, but we can at least
        # remove the reference. The caller should set the variable to None.
        pass

