from __future__ import annotations

from typing import Optional

from config import CODINGS_JSON
from domain.differentiation_migration import CODING_SCHEMA_VERSION, coding_payload_uses_legacy_schema
from models import CodingEntry
from storage.fs_store import read_json, write_json


def list_codings() -> list[CodingEntry]:
    payload = read_json(CODINGS_JSON, default={"codings": []})
    raw_codings = payload.get("codings", [])
    version = payload.get("schema_version")
    version_is_legacy = version not in {None, CODING_SCHEMA_VERSION} or (
        version is None and bool(raw_codings)
    )
    if version_is_legacy or any(
        isinstance(coding, dict) and coding_payload_uses_legacy_schema(coding) for coding in raw_codings
    ):
        raise RuntimeError(
            "Legacy coding-schema data reached the repository before startup migration. "
            "Stop the server and send the full error message to Arthur."
        )
    return [CodingEntry.model_validate(c) for c in raw_codings]


def save_codings(codings: list[CodingEntry]) -> None:
    payload = {
        "schema_version": CODING_SCHEMA_VERSION,
        "codings": [c.model_dump(mode="json") for c in codings],
    }
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
