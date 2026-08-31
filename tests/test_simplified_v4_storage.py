import json

import pytest

from coding_books.simplified_v4.models import TranscriptSpan
from domain import simplified_coding_service as service
from storage import simplified_coding_repo as repo


def test_v4_service_never_reads_or_writes_legacy_store(tmp_path, monkeypatch) -> None:
    legacy_path = tmp_path / "codings.json"
    legacy_bytes = b'{"schema_version":3,"codings":[{"legacy":"sentinel"}]}\n'
    legacy_path.write_bytes(legacy_bytes)
    v4_path = tmp_path / "codings_v4.json"
    monkeypatch.setattr(repo, "CODINGS_V4_JSON", v4_path)

    created = service.create_object_entry(
        analysis_id="analysis-1",
        interview_file="interview.srt",
        object_type="differentiation",
        created_by=" coder ",
    )

    assert created.created_by == "coder"
    assert legacy_path.read_bytes() == legacy_bytes
    stored = json.loads(v4_path.read_text(encoding="utf-8"))
    assert stored["storage_format_version"] == 1
    assert stored["coding_book_version"] == 4
    assert stored["codings"][0]["coding"]["code_type"] == "differentiation"


def test_v4_create_update_read_and_delete_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(repo, "CODINGS_V4_JSON", tmp_path / "codings_v4.json")
    created = service.create_object_entry(
        analysis_id="analysis-1",
        interview_file="interview.srt",
        object_type="comparison",
        created_by="coder",
    )
    coding = created.coding.model_copy(deep=True)
    coding.fields.thing_a = "før"
    span = TranscriptSpan(
        start_segment_id="segment-1",
        start_char_offset=0,
        end_segment_id="segment-1",
        end_char_offset=3,
        selected_text="før",
    )
    updated = service.update_entry_payload(
        analysis_id="analysis-1",
        coding_id=created.coding_id,
        coding=coding,
        field_spans={"comparison.thing_a": [span]},
    )

    loaded = repo.list_codings()
    assert loaded == [updated]
    assert loaded[0].coding.fields.thing_a == "før"
    assert loaded[0].field_spans["comparison.thing_a"] == [span]
    assert service.delete_entry(analysis_id="analysis-1", coding_id=created.coding_id)
    assert repo.list_codings() == []


def test_wrong_book_version_is_rejected_without_rewrite(tmp_path, monkeypatch) -> None:
    path = tmp_path / "codings_v4.json"
    original = b'{"storage_format_version":1,"coding_book_version":3,"codings":[]}\n'
    path.write_bytes(original)
    monkeypatch.setattr(repo, "CODINGS_V4_JSON", path)

    with pytest.raises(ValueError, match="different coding book"):
        repo.list_codings()
    assert path.read_bytes() == original


def test_unknown_fields_cannot_silently_disappear_from_v4_store(tmp_path, monkeypatch) -> None:
    path = tmp_path / "codings_v4.json"
    payload = {
        "storage_format_version": 1,
        "coding_book_version": 4,
        "codings": [
            {
                "coding_book_version": 4,
                "coding_id": "coding-1",
                "analysis_id": "analysis-1",
                "interview_file": "interview.srt",
                "coding": {
                    "code_type": "nuance",
                    "fields": {"legacy_condition": "must not be dropped"},
                },
                "field_spans": {},
                "created_by": "coder",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    original = path.read_bytes()
    monkeypatch.setattr(repo, "CODINGS_V4_JSON", path)

    with pytest.raises(ValueError):
        repo.list_codings()
    assert path.read_bytes() == original
