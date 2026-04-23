from __future__ import annotations

from typing import Optional

from config import CODINGS_JSON
from models import CodingEntry
from storage.fs_store import read_json, write_json


def list_codings() -> list[CodingEntry]:
    payload = read_json(CODINGS_JSON, default={"codings": []})
    return [CodingEntry.model_validate(c) for c in payload.get("codings", [])]


def save_codings(codings: list[CodingEntry]) -> None:
    payload = {"codings": [c.model_dump(mode="json") for c in codings]}
    write_json(CODINGS_JSON, payload)


def list_codings_for_analysis(analysis_id: str) -> list[CodingEntry]:
    if not analysis_id:
        raise ValueError("analysis_id is required")
    return [c for c in list_codings() if c.analysis_id == analysis_id]


def get_coding_by_id(coding_id: str) -> Optional[CodingEntry]:
    for coding in list_codings():
        if coding.coding_id == coding_id:
            return coding
    return None
