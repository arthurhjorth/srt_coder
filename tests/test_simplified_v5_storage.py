from __future__ import annotations

import json

import pytest

from coding_books.simplified_v5.models import Perspective, TranscriptSpan
from domain import simplified_coding_service_v5 as service
from storage import simplified_coding_repo_v5 as repo


def _span(text: str) -> TranscriptSpan:
    return TranscriptSpan(
        start_segment_id="seg-00001",
        start_char_offset=0,
        end_segment_id="seg-00001",
        end_char_offset=len(text),
        selected_text=text,
    )


def test_v5_service_uses_only_the_neutral_store(tmp_path, monkeypatch) -> None:
    neutral = tmp_path / "codings_simplified.json"
    v4 = tmp_path / "codings_v4.json"
    legacy = tmp_path / "codings.json"
    v4_bytes = b'{"sentinel":"v4"}\n'
    legacy_bytes = b'{"sentinel":"legacy"}\n'
    v4.write_bytes(v4_bytes)
    legacy.write_bytes(legacy_bytes)
    monkeypatch.setattr(repo, "SIMPLIFIED_CODINGS_JSON", neutral)

    created = service.create_object_entry(
        analysis_id="analysis-1",
        interview_file="interview.srt",
        object_type="differentiation",
        created_by=" coder ",
    )

    assert created.created_by == "coder"
    assert v4.read_bytes() == v4_bytes
    assert legacy.read_bytes() == legacy_bytes
    payload = json.loads(neutral.read_text(encoding="utf-8"))
    assert payload["coding_book_version"] == 5


def test_remove_perspective_deletes_its_spans_and_reindexes_later_paths(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(repo, "SIMPLIFIED_CODINGS_JSON", tmp_path / "codings_simplified.json")
    created = service.create_object_entry(
        analysis_id="analysis-1",
        interview_file="interview.srt",
        object_type="differentiation",
        created_by="coder",
    )
    coding = created.coding.model_copy(deep=True)
    coding.fields.perspectives = [
        Perspective(text="first"),
        Perspective(text="second", perspective_types=["goals"]),
    ]
    updated = service.update_entry_payload(
        analysis_id="analysis-1",
        coding_id=created.coding_id,
        coding=coding,
        field_spans={
            "differentiation.perspectives[0].text": [_span("first")],
            "differentiation.perspectives[1].text": [_span("second")],
            "differentiation.thing_being_considered": [_span("topic")],
        },
    )
    removed = service.remove_perspective(
        analysis_id="analysis-1", coding_id=updated.coding_id, perspective_index=0
    )

    assert [item.text for item in removed.coding.fields.perspectives] == ["second"]
    assert removed.field_spans["differentiation.perspectives[0].text"][0].selected_text == "second"
    assert "differentiation.perspectives[1].text" not in removed.field_spans
    assert "differentiation.thing_being_considered" in removed.field_spans


def test_confirmed_object_delete_removes_persisted_entry(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(repo, "SIMPLIFIED_CODINGS_JSON", tmp_path / "codings_simplified.json")
    created = service.create_object_entry(
        analysis_id="analysis-1",
        interview_file="interview.srt",
        object_type="nuance",
        created_by="coder",
    )
    assert service.delete_entry(analysis_id="analysis-1", coding_id=created.coding_id)
    assert repo.list_codings() == []
    assert not service.delete_entry(analysis_id="analysis-1", coding_id=created.coding_id)


def test_span_comment_round_trips_with_its_exact_span(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(repo, "SIMPLIFIED_CODINGS_JSON", tmp_path / "codings_simplified.json")
    created = service.create_object_entry(
        analysis_id="analysis-1",
        interview_file="interview.srt",
        object_type="comparison",
        created_by="coder",
    )
    coding = created.coding.model_copy(deep=True)
    coding.fields.thing_a = "first"
    span = _span("first").model_copy(update={"comment": "  comparison rationale  "})
    service.update_entry_payload(
        analysis_id="analysis-1",
        coding_id=created.coding_id,
        coding=coding,
        field_spans={"comparison.thing_a": [span]},
    )
    loaded = repo.list_codings()[0]
    saved_span = loaded.field_spans["comparison.thing_a"][0]
    assert saved_span.selected_text == "first"
    assert saved_span.comment == "comparison rationale"


def test_invalid_neutral_store_is_rejected_without_rewrite(tmp_path, monkeypatch) -> None:
    path = tmp_path / "codings_simplified.json"
    original = b'{"storage_format_version":1,"coding_book_version":4,"codings":[]}\n'
    path.write_bytes(original)
    monkeypatch.setattr(repo, "SIMPLIFIED_CODINGS_JSON", path)
    with pytest.raises(ValueError, match="not coding book v5"):
        repo.list_codings()
    assert path.read_bytes() == original


def test_nuance_rewrite_round_trips_without_changing_original_evidence(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(repo, "SIMPLIFIED_CODINGS_JSON", tmp_path / "codings_simplified.json")
    created = service.create_object_entry(
        analysis_id="analysis-1", interview_file="interview.srt",
        object_type="nuance", created_by="coder",
    )
    coding = created.coding.model_copy(deep=True)
    coding.fields.x_y_connection = "original wording"
    coding.fields.x_y_connection_rewritten = True
    coding.fields.x_y_connection_rewrite = "More training reduces mistakes."
    coding.fields.x_y_connection_rewrite_comment = "The causal connection is implicit here."
    evidence = {"nuance.x_y_connection": [_span("original wording")]}
    service.update_entry_payload(
        analysis_id="analysis-1", coding_id=created.coding_id,
        coding=coding, field_spans=evidence,
    )
    loaded = repo.list_codings()[0]
    assert loaded.coding.fields.x_y_connection_rewritten is True
    assert loaded.coding.fields.x_y_connection_rewrite == "More training reduces mistakes."
    assert loaded.coding.fields.x_y_connection_rewrite_comment == "The causal connection is implicit here."
    assert loaded.coding.fields.x_y_connection == "original wording"
    assert loaded.field_spans == evidence
    coding = loaded.coding.model_copy(deep=True)
    coding.fields.x_y_connection_rewritten = False
    service.update_entry_payload(
        analysis_id="analysis-1", coding_id=created.coding_id, coding=coding,
    )
    loaded = repo.list_codings()[0]
    assert loaded.coding.fields.x_y_connection_rewrite == "More training reduces mistakes."
    assert loaded.coding.fields.x_y_connection_rewrite_comment == "The causal connection is implicit here."
    assert loaded.field_spans == evidence


@pytest.mark.parametrize("include_comment,comment", [
    (False, None), (True, None), (True, ""), (True, "  "),
])
def test_old_entries_with_missing_or_empty_rewrite_comments_load_without_file_changes(
    tmp_path, monkeypatch, include_comment, comment
) -> None:
    path = tmp_path / "codings_simplified.json"
    monkeypatch.setattr(repo, "SIMPLIFIED_CODINGS_JSON", path)
    created = service.create_object_entry(
        analysis_id="analysis-1", interview_file="interview.srt",
        object_type="nuance", created_by="coder",
    )
    payload = json.loads(path.read_bytes())
    fields = payload["codings"][0]["coding"]["fields"]
    fields.pop("x_y_connection_rewrite_comment")
    if include_comment:
        fields["x_y_connection_rewrite_comment"] = comment
    original = (json.dumps(payload) + "\n").encode("utf-8")
    path.write_bytes(original)

    loaded = repo.list_codings()[0]
    assert loaded.coding_id == created.coding_id
    assert loaded.coding.fields.x_y_connection_rewrite_comment in (None, "")
    assert path.read_bytes() == original
