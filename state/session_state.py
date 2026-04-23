from __future__ import annotations

from typing import Optional


def _storage_user() -> dict:
    from nicegui import app
    return app.storage.user


def set_selected_interview_file(filename: str | None) -> None:
    if filename:
        _storage_user()["selected_interview_file"] = filename
    else:
        _storage_user().pop("selected_interview_file", None)


def get_selected_interview_file() -> Optional[str]:
    return _storage_user().get("selected_interview_file")


def set_selected_analysis_id(analysis_id: str | None) -> None:
    if analysis_id:
        _storage_user()["selected_analysis_id"] = analysis_id
    else:
        _storage_user().pop("selected_analysis_id", None)


def get_selected_analysis_id() -> Optional[str]:
    return _storage_user().get("selected_analysis_id")
