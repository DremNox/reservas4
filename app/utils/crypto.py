# app/utils/crypto.py

import os
from cryptography.fernet import Fernet

def _fernet() -> Fernet:
    key = os.getenv("FERNET_KEY")
    if not key:
        raise RuntimeError("Falta FERNET_KEY en variables de entorno")
    return Fernet(key.encode() if isinstance(key, str) else key)

def encrypt_str(value: str) -> bytes:
    return _fernet().encrypt(value.encode("utf-8"))

def decrypt_str(token: bytes) -> str:
    return _fernet().decrypt(token).decode("utf-8")
