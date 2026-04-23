from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional

from models import User
from storage.users_repo import get_user_by_username


PBKDF2_ALGO = "sha256"
PBKDF2_ITERATIONS = 200_000
SALT_BYTES = 16


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = os.urandom(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        PBKDF2_ALGO,
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return "pbkdf2_sha256${iterations}${salt}${digest}".format(
        iterations=iterations,
        salt=salt.hex(),
        digest=digest.hex(),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, iter_str, salt_hex, digest_hex = password_hash.split("$", 3)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    try:
        iterations = int(iter_str, 10)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, TypeError):
        return False
    candidate = hashlib.pbkdf2_hmac(
        PBKDF2_ALGO,
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(candidate, expected)


def authenticate(username: str, password: str) -> Optional[User]:
    user = get_user_by_username(username.strip())
    if user is None:
        return None
    if user.is_active is False:
        return None
    if not user.password_hash:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def _storage_user() -> dict:
    from nicegui import app
    return app.storage.user


def login(username: str) -> None:
    _storage_user()["username"] = username


def logout() -> None:
    _storage_user().pop("username", None)


def current_username() -> Optional[str]:
    return _storage_user().get("username")


def is_authenticated() -> bool:
    return bool(current_username())


def require_auth_or_redirect() -> bool:
    if is_authenticated():
        return True
    from nicegui import ui
    ui.navigate.to("/login")
    return False
