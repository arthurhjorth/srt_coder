from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class User(BaseModel):
    username: Optional[str] = None
    username_comment: Optional[str] = None

    password_hash: Optional[str] = None
    password_hash_comment: Optional[str] = None

    role: Optional[str] = None
    role_comment: Optional[str] = None

    is_active: Optional[bool] = None
    is_active_comment: Optional[str] = None

    created_at: Optional[str] = None
    created_at_comment: Optional[str] = None

    updated_at: Optional[str] = None
    updated_at_comment: Optional[str] = None


class Analysis(BaseModel):
    analysis_id: Optional[str] = None
    analysis_id_comment: Optional[str] = None

    owner_username: Optional[str] = None
    owner_username_comment: Optional[str] = None

    interview_file: Optional[str] = None
    interview_file_comment: Optional[str] = None

    name: Optional[str] = None
    name_comment: Optional[str] = None

    description: Optional[str] = None
    description_comment: Optional[str] = None

    created_at: Optional[str] = None
    created_at_comment: Optional[str] = None

    updated_at: Optional[str] = None
    updated_at_comment: Optional[str] = None
