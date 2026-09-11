from __future__ import annotations

from copy import deepcopy
import json

import pytest

from coding_books.simplified_v4.models import (
    NuanceCoding as V4NuanceCoding,
    NuanceFields as V4NuanceFields,
    NuanceRelationType as V4RelationType,
    SimplifiedCodingEntry as V4Entry,
)
from coding_books.simplified_v5.models import ComparisonCoding, SimplifiedCodingEntry
from core_models import Analysis, User
from domain import simplified_analysis_exchange_service_v5 as exchange


def _v5_entry() -> SimplifiedCodingEntry:
    return SimplifiedCodingEntry(
        coding_id="coding-1",
        analysis_id="analysis-1",
        interview_file="interview.srt",
        coding=ComparisonCoding(),
        created_by="coder",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def test_export_writes_v5_to_the_neutral_export_folder(tmp_path, monkeypatch) -> None:
    analysis = Analysis(
        analysis_id="analysis-1",
        owner_username="coder",
        interview_file="interview.srt",
        name="Analysis",
    )
    coding = _v5_entry()
    monkeypatch.setattr(exchange, "SIMPLIFIED_EXPORTS_DIR", tmp_path)
    monkeypatch.setattr(exchange, "list_analyses", lambda: [analysis])
    monkeypatch.setattr(exchange, "list_codings", lambda: [coding])
    monkeypatch.setattr(exchange, "list_users", lambda: [User(username="coder")])

    output = exchange.export_analysis_to_file(analysis_id="analysis-1")
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["coding_book_version"] == 5
    assert payload["codings"] == [coding.model_dump(mode="json")]


def test_v4_import_migrates_in_memory_without_mutating_input(monkeypatch) -> None:
    v4_entry = V4Entry(
        coding_id="old-coding",
        analysis_id="old-analysis",
        interview_file="interview.srt",
        coding=V4NuanceCoding(
            fields=V4NuanceFields(
                relation_type=V4RelationType.AMBITION_INTENTION,
                outcome_or_goal_y="a result",
            )
        ),
        created_by="coder",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    payload = {
        "export_format_version": 1,
        "coding_book_version": 4,
        "analyses": [
            Analysis(
                analysis_id="old-analysis",
                owner_username="coder",
                interview_file="interview.srt",
                name="Imported",
            ).model_dump(mode="json")
        ],
        "codings": [v4_entry.model_dump(mode="json")],
        "users": [],
    }
    original = deepcopy(payload)
    saved: dict[str, list] = {}
    monkeypatch.setattr(exchange, "list_interview_files", lambda: ["interview.srt"])
    monkeypatch.setattr(exchange, "list_users", lambda: [])
    monkeypatch.setattr(exchange, "list_analyses", lambda: [])
    monkeypatch.setattr(exchange, "list_codings", lambda: [])
    monkeypatch.setattr(exchange, "save_users", lambda values: saved.setdefault("users", values))
    monkeypatch.setattr(exchange, "save_analyses", lambda values: saved.setdefault("analyses", values))
    monkeypatch.setattr(exchange, "save_codings", lambda values: saved.setdefault("codings", values))

    report = exchange.import_analyses_from_payload(payload)

    assert payload == original
    assert report["imported_codings"] == 1
    assert saved["codings"][0].coding.fields.relation_type.value == "expected_effect"


def test_hierarchical_v3_import_is_rejected_before_store_reads(monkeypatch) -> None:
    touched: list[str] = []
    monkeypatch.setattr(exchange, "list_users", lambda: touched.append("users") or [])
    with pytest.raises(ValueError, match="v4 or v5"):
        exchange.import_analyses_from_payload(
            {
                "export_format_version": 1,
                "coding_book_version": 3,
                "analyses": [],
                "codings": [],
                "users": [],
            }
        )
    assert touched == []
