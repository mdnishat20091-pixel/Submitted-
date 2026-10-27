"""API Hash / Session String এনক্রিপ্ট করে DB-তে রাখার জন্য।
Key আসে SECRET_KEY Environment থেকে; না থাকলে data/secret.key ফাইলে তৈরি হয়।"""
import os
from cryptography.fernet import Fernet
import config

_fernet = None


def _load_key() -> bytes:
    env = os.getenv("SECRET_KEY", "").strip()
    if env:
        return env.encode()
    path = config.DATA_DIR / "secret.key"
    if path.exists():
        return path.read_bytes().strip()
    key = Fernet.generate_key()
    path.write_bytes(key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def _f() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_key())
    return _fernet


def encrypt(text: str) -> str:
    return _f().encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    return _f().decrypt(token.encode()).decode()
