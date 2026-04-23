from __future__ import annotations

from typing import Optional

from config import USERS_JSON
from models import User
from storage.fs_store import read_json, write_json


def list_users() -> list[User]:
    payload = read_json(USERS_JSON, default={"users": []})
    return [User.model_validate(u) for u in payload.get("users", [])]


def get_user_by_username(username: str) -> Optional[User]:
    for user in list_users():
        if user.username == username:
            return user
    return None


def save_users(users: list[User]) -> None:
    payload = {"users": [user.model_dump(mode="json") for user in users]}
    write_json(USERS_JSON, payload)

