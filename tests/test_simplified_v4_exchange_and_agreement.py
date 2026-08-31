import json

import pytest

from coding_books.simplified_v4.models import (
    ComparisonCoding,
    ComparisonFields,
    SimplifiedCodingEntry,
    TranscriptSpan,
)
from core_models import Analysis, User
from domain import simplified_analysis_exchange_service as exchange
from domain.simplified_agreement_service import (
    AgreementRules,
    build_agreement_report,
    load_agreement_export,
)


def _entry(*, coding_id: str, analysis_id: str, field_path: str, start: int) -> SimplifiedCodingEntry:
    return SimplifiedCodingEntry(
        coding_id=coding_id,
        analysis_id=analysis_id,
        interview_file="interview.srt",
        coding=ComparisonCoding(fields=ComparisonFields(thing_a="før")),
        field_spans={
            field_path: [
                TranscriptSpan(
                    start_segment_id="segment-1",
                    start_char_offset=start,
                    end_segment_id="segment-1",
                    end_char_offset=start + 3,
                    selected_text="før",
                )
            ]
        },
        created_by="coder",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def _payload(entry: SimplifiedCodingEntry, *, owner: str = "coder") -> dict:
    return {
        "export_format_version": 1,
        "coding_book_version": 4,
        "analyses": [
            Analysis(
                analysis_id=entry.analysis_id,
                owner_username=owner,
                interview_file="interview.srt",
                name="Analysis",
            ).model_dump(mode="json")
        ],
        "codings": [entry.model_dump(mode="json")],
        "users": [],
    }


def test_export_writes_only_v4_codings_and_version_metadata(tmp_path, monkeypatch) -> None:
    analysis = Analysis(
        analysis_id="analysis-1",
        owner_username="coder",
        interview_file="interview.srt",
        name="Analysis",
    )
    coding = _entry(
        coding_id="coding-1",
        analysis_id="analysis-1",
        field_path="comparison.thing_a",
        start=0,
    )
    monkeypatch.setattr(exchange, "EXPORTS_V4_DIR", tmp_path)
    monkeypatch.setattr(exchange, "list_analyses", lambda: [analysis])
    monkeypatch.setattr(exchange, "list_codings", lambda: [coding])
    monkeypatch.setattr(exchange, "list_users", lambda: [User(username="coder")])

    output = exchange.export_analysis_to_file(analysis_id="analysis-1")
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["export_format_version"] == 1
    assert payload["coding_book_version"] == 4
    assert payload["codings"] == [coding.model_dump(mode="json")]


def test_import_rejects_legacy_export_before_touching_stores(monkeypatch) -> None:
    touched = []
    monkeypatch.setattr(exchange, "list_users", lambda: touched.append("users") or [])
    with pytest.raises(ValueError, match="another coding book"):
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


def test_agreement_accepts_v4_and_matches_overlapping_spans() -> None:
    left = load_agreement_export(
        json.dumps(
            _payload(
                _entry(
                    coding_id="left",
                    analysis_id="analysis-left",
                    field_path="comparison.thing_a",
                    start=0,
                ),
                owner="left-coder",
            )
        ),
        source_name="left.json",
        source_index=0,
    )
    right = load_agreement_export(
        json.dumps(
            _payload(
                _entry(
                    coding_id="right",
                    analysis_id="analysis-right",
                    field_path="comparison.thing_a",
                    start=1,
                ),
                owner="right-coder",
            )
        ),
        source_name="right.json",
        source_index=1,
    )

    partial = build_agreement_report(
        [left, right],
        AgreementRules(span_mode="partial", field_mode="normalized"),
    )
    exact = build_agreement_report(
        [left, right],
        AgreementRules(span_mode="exact", field_mode="normalized"),
    )
    assert partial.pair_agreements[0].true_positives == 1
    assert partial.full_agreement_clusters == 1
    assert exact.pair_agreements[0].true_positives == 0


def test_agreement_rejects_legacy_export() -> None:
    with pytest.raises(ValueError, match="v4 exports only"):
        load_agreement_export(
            json.dumps(
                {
                    "export_format_version": 1,
                    "coding_book_version": 3,
                    "analyses": [{}],
                    "codings": [],
                }
            ),
            source_name="legacy.json",
            source_index=0,
        )
