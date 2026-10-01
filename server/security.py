import base64
import hashlib
import bcrypt


def _prepare_password(password: str) -> bytes:
    """Pre-hashes passwords longer than 72 bytes with SHA-256 to stay within bcrypt limits."""
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        digest = hashlib.sha256(password_bytes).digest()
        return base64.b64encode(digest)
    return password_bytes


def hash_password(password: str) -> str:
    prepared = _prepare_password(password)
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(prepared, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    prepared = _prepare_password(plain_password)
    # Convert stored string hash back to bytes for verification
    return bcrypt.checkpw(prepared, hashed_password.encode("utf-8"))