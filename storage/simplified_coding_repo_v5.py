from __future__ import annotations

from typing import Any

from coding_books.simplified_v5.models import CODING_BOOK_VERSION, SimplifiedCodingEntry
from config import SIMPLIFIED_CODINGS_JSON
from storage.fs_store import read_json, write_json


STORE_FORMAT_VERSION = 1


def empty_store() -> dict[str, Any]:
    return {
        "storage_format_version": STORE_FORMAT_VERSION,
        "coding_book_version": CODING_BOOK_VERSION,
        "codings": [],
    }


def validate_store(payload: Any) -> list[dict]:
    if not isinstance(payload, dict):
        raise ValueError("The simplified coding store must be a JSON object.")
    if payload.get("storage_format_version") != STORE_FORMAT_VERSION:
        raise ValueError("Unsupported simplified coding-store format. The file was not changed.")
    if payload.get("coding_book_version") != CODING_BOOK_VERSION:
        raise ValueError("The simplified coding store is not coding book v5. The file was not changed.")
    raw_codings = payload.get("codings")
    if not isinstance(raw_codings, list):
        raise ValueError("The simplified coding store must contain a codings list.")
    return raw_codings


def list_codings() -> list[SimplifiedCodingEntry]:
    payload = read_json(SIMPLIFIED_CODINGS_JSON, default=empty_store())
    codings = [SimplifiedCodingEntry.model_validate(raw) for raw in validate_store(payload)]
    coding_ids = [coding.coding_id for coding in codings]
    if len(coding_ids) != len(set(coding_ids)):
        raise ValueError("The simplified coding store contains duplicate coding ids.")
    return codings


def save_codings(codings: list[SimplifiedCodingEntry]) -> None:
    validated = [SimplifiedCodingEntry.model_validate(coding) for coding in codings]
    coding_ids = [coding.coding_id for coding in validated]
    if len(coding_ids) != len(set(coding_ids)):
        raise ValueError("The simplified coding store contains duplicate coding ids.")
    write_json(
        SIMPLIFIED_CODINGS_JSON,
        {
            "storage_format_version": STORE_FORMAT_VERSION,
            "coding_book_version": CODING_BOOK_VERSION,
            "codings": [coding.model_dump(mode="json") for coding in validated],
        },
    )


def list_codings_for_analysis(analysis_id: str) -> list[SimplifiedCodingEntry]:
    if not analysis_id:
        raise ValueError("analysis_id is required")
    return [coding for coding in list_codings() if coding.analysis_id == analysis_id]


def get_coding_by_id(coding_id: str) -> SimplifiedCodingEntry | None:
    if not coding_id:
        return None
    return next((coding for coding in list_codings() if coding.coding_id == coding_id), None)
