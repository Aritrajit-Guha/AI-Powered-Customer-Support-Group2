"""Password hashing and login tokens.

Passwords use scrypt from Python's standard library (no extra package, nothing to compile on Windows).
Tokens are standard JWTs (PyJWT).
"""
import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt

from . import config

_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt$%s$%s" % (base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def verify_password(password: str, stored) -> bool:
    if not stored or not password:
        return False
    try:
        scheme, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def create_token(user) -> tuple:
    """Returns (token, expires_in_seconds)."""
    expires = timedelta(minutes=config.JWT_EXPIRE_MINUTES)
    payload = {
        "sub": str(user.user_id),
        "role": user.role,
        "exp": datetime.now(timezone.utc) + expires,
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM), int(expires.total_seconds())


def decode_token(token: str):
    """Returns the payload, or None if the token is wrong or expired."""
    try:
        return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
