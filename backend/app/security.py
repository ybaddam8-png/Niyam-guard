"""
Real password hashing (bcrypt, called directly — not via passlib) and JWT
issuing/verification (python-jose).

Note on the bcrypt dependency: passlib's bcrypt backend was dropped in favor of calling
the `bcrypt` package directly after hitting a real, reproducible bug — passlib 1.7.4's
version-detection code reads `bcrypt.__about__.__version__`, which the `bcrypt` package
removed in 4.1+. passlib is effectively unmaintained (last release 2020) and this is an
open, unresolved compatibility issue, not a one-off fluke — so rather than pin bcrypt to
an old version and carry that constraint forward, we call bcrypt's own API directly.
"""
from datetime import datetime, timedelta, timezone
import bcrypt
from jose import jwt, JWTError
from app import config

BCRYPT_MAX_BYTES = 72  # bcrypt silently ignores anything past this — truncate explicitly


def hash_password(plain_password: str) -> str:
    pw_bytes = plain_password.encode("utf-8")[:BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    pw_bytes = plain_password.encode("utf-8")[:BCRYPT_MAX_BYTES]
    return bcrypt.checkpw(pw_bytes, hashed_password.encode("utf-8"))


def create_access_token(user_id: str, username: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "username": username, "role": role, "exp": expire}
    return jwt.encode(payload, config.JWT_SECRET_KEY, algorithm=config.JWT_ALGORITHM)


class TokenError(Exception):
    pass


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, config.JWT_SECRET_KEY, algorithms=[config.JWT_ALGORITHM])
    except JWTError as e:
        raise TokenError(str(e))
