from __future__ import annotations

import hashlib
import json

import pytest

from coding_books.simplified_v4.models import (
    DifferentiationCoding,
    DifferentiationFields,
    NuanceCoding,
    NuanceFields,
    NuanceRelationType,
    PerspectiveType,
    SimplifiedCodingEntry,
    TranscriptSpan,
)
from coding_books.simplified_v5.models import SimplifiedCodingEntry as V5Entry
from domain.simplified_schema_migration import (
    SimplifiedMigrationError,
    ensure_current_simplified_schema,
    migrate_store_payload,
)
from domain import simplified_schema_migration as migration


def _span(text: str = "perspektiv") -> TranscriptSpan:
    return TranscriptSpan(
        start_segment_id="seg-00001",
        start_char_offset=0,
        end_segment_id="seg-00001",
        end_char_offset=len(text),
        selected_text=text,
    )


def _entry(coding_id: str, coding, spans=None) -> dict:
    return SimplifiedCodingEntry(
        coding_id=coding_id,
        analysis_id="analysis-1",
        interview_file="test.srt",
        coding=coding,
        field_spans=spans or {},
        created_by="coder",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-02T00:00:00+00:00",
    ).model_dump(mode="json")


def _store(codings: list[dict]) -> dict:
    return {"storage_format_version": 1, "coding_book_version": 4, "codings": codings}


def test_migration_nests_and_copies_perspective_types_and_rekeys_spans() -> None:
    source = _store(
        [
            _entry(
                "diff-1",
                DifferentiationCoding(
                    fields=DifferentiationFields(
                        thing_being_considered="emnet",
                        perspectives=["ledelsen", "medarbejderne"],
                        perspective_types=[PerspectiveType.ACTORS_ROLES, PerspectiveType.GOALS],
                        coder_note="bevar mig",
                    )
                ),
                {
                    "differentiation.perspectives[0]": [_span("ledelsen")],
                    "differentiation.perspective_types": [_span("type")],
                },
            )
        ]
    )
    migrated = migrate_store_payload(source)
    entry = V5Entry.model_validate(migrated["codings"][0])
    rows = entry.coding.fields.perspectives
    assert [row.text for row in rows] == ["ledelsen", "medarbejderne"]
    assert all(
        row.perspective_types == [PerspectiveType.ACTORS_ROLES, PerspectiveType.GOALS]
        for row in rows
    )
    assert entry.coding.fields.coder_note == "bevar mig"
    assert "differentiation.perspectives[0].text" in entry.field_spans
    assert "differentiation.perspective_types" not in entry.field_spans
    assert entry.migration_metadata is not None
    assert entry.migration_metadata.legacy_differentiation_perspective_types == [
        PerspectiveType.ACTORS_ROLES,
        PerspectiveType.GOALS,
    ]
    assert "differentiation.perspective_types" in entry.migration_metadata.legacy_field_spans
    assert migrated == migrate_store_payload(migrated)


def test_types_without_perspective_create_one_empty_typed_row() -> None:
    source = _store(
        [
            _entry(
                "diff-empty",
                DifferentiationCoding(
                    fields=DifferentiationFields(
                        perspective_types=[PerspectiveType.CONSEQUENCES]
                    )
                ),
            )
        ]
    )
    entry = V5Entry.model_validate(migrate_store_payload(source)["codings"][0])
    assert len(entry.coding.fields.perspectives) == 1
    assert entry.coding.fields.perspectives[0].text is None
    assert entry.coding.fields.perspectives[0].perspective_types == [
        PerspectiveType.CONSEQUENCES
    ]


def test_span_path_collision_merges_without_losing_either_span() -> None:
    source = _store(
        [
            _entry(
                "diff-collision",
                DifferentiationCoding(
                    fields=DifferentiationFields(perspectives=["staff"])
                ),
                {
                    "differentiation.perspectives[0]": [_span("legacy")],
                    "differentiation.perspectives[0].text": [_span("unexpected")],
                    "differentiation.perspective_types[0]": [_span("type evidence")],
                },
            )
        ]
    )
    entry = V5Entry.model_validate(migrate_store_payload(source)["codings"][0])
    assert [
        span.selected_text
        for span in entry.field_spans["differentiation.perspectives[0].text"]
    ] == ["legacy", "unexpected"]
    assert entry.migration_metadata is not None
    assert (
        entry.migration_metadata.legacy_field_spans[
            "differentiation.perspective_types[0]"
        ][0].selected_text
        == "type evidence"
    )


def test_ambition_is_recoded_without_combining_or_changing_other_data() -> None:
    source_entry = _entry(
        "nuance-1",
        NuanceCoding(
            fields=NuanceFields(
                relation_type=NuanceRelationType.AMBITION_INTENTION,
                influence_or_action_x="X",
                outcome_or_goal_y="Y",
                x_y_connection="fører til",
                expressed_certainty="qualified",
                limitation="kun nu",
                coder_note="note",
            )
        ),
        {"nuance.x_y_connection": [_span("fører til")]},
    )
    migrated = migrate_store_payload(_store([source_entry]))
    result = migrated["codings"][0]
    fields = result["coding"]["fields"]
    assert result["coding_id"] == "nuance-1"
    assert fields["relation_type"] == "expected_effect"
    for name in (
        "influence_or_action_x",
        "outcome_or_goal_y",
        "x_y_connection",
        "expressed_certainty",
        "limitation",
        "coder_note",
    ):
        assert fields[name] == source_entry["coding"]["fields"][name]
    migrated_spans = result["field_spans"]["nuance.x_y_connection"]
    source_spans = source_entry["field_spans"]["nuance.x_y_connection"]
    assert [{key: value for key, value in span.items() if key != "comment"} for span in migrated_spans] == source_spans
    assert migrated_spans[0]["comment"] is None
    assert result["created_at"] == source_entry["created_at"]
    assert result["updated_at"] == source_entry["updated_at"]


def test_disk_migration_backs_up_exact_sources_and_leaves_them_unchanged(tmp_path) -> None:
    analyses = tmp_path / "analyses.json"
    v4 = tmp_path / "codings_v4.json"
    target = tmp_path / "codings_simplified.json"
    backups = tmp_path / "old_schema_analyses"
    analyses_bytes = b'{"analyses":[]}\n'
    codings_bytes = (json.dumps(_store([]), indent=2) + "\n").encode()
    analyses.write_bytes(analyses_bytes)
    v4.write_bytes(codings_bytes)

    result = ensure_current_simplified_schema(
        analyses_path=analyses,
        v4_path=v4,
        target_path=target,
        backup_root=backups,
    )

    assert result.status == "migrated"
    assert result.backup_dir is not None
    assert analyses.read_bytes() == analyses_bytes
    assert v4.read_bytes() == codings_bytes
    assert (result.backup_dir / "analyses.json").read_bytes() == analyses_bytes
    assert (result.backup_dir / "codings_v4.json").read_bytes() == codings_bytes
    manifest = json.loads((result.backup_dir / "migration_manifest.json").read_text())
    assert manifest["status"] == "completed"
    assert manifest["source_coding_book_version"] == 4
    assert manifest["target_coding_book_version"] == 5
    assert manifest["sha256"]["codings_v4.json"]["source"] == hashlib.sha256(
        codings_bytes
    ).hexdigest()
    assert json.loads(target.read_text())["coding_book_version"] == 5


def test_future_version_is_rejected_before_backup_or_target_write(tmp_path) -> None:
    analyses = tmp_path / "analyses.json"
    v4 = tmp_path / "codings_v4.json"
    target = tmp_path / "codings_simplified.json"
    backups = tmp_path / "old_schema_analyses"
    analyses.write_text('{"analyses":[]}')
    v4.write_text(
        json.dumps({"storage_format_version": 1, "coding_book_version": 6, "codings": []})
    )
    with pytest.raises(SimplifiedMigrationError, match="future"):
        ensure_current_simplified_schema(
            analyses_path=analyses,
            v4_path=v4,
            target_path=target,
            backup_root=backups,
        )
    assert not target.exists()
    assert not backups.exists()


def test_valid_v5_neutral_store_is_a_no_op_without_backup(tmp_path) -> None:
    target = tmp_path / "codings_simplified.json"
    original = json.dumps(
        {"storage_format_version": 1, "coding_book_version": 5, "codings": []}
    ).encode()
    target.write_bytes(original)
    result = ensure_current_simplified_schema(
        analyses_path=tmp_path / "analyses.json",
        v4_path=tmp_path / "codings_v4.json",
        target_path=target,
        backup_root=tmp_path / "old_schema_analyses",
    )
    assert result.status == "current"
    assert target.read_bytes() == original
    assert not (tmp_path / "old_schema_analyses").exists()


def test_inconsistent_neutral_store_fails_before_backup_and_is_unchanged(tmp_path) -> None:
    target = tmp_path / "codings_simplified.json"
    payload = _store([])
    original = json.dumps(payload).encode()
    target.write_bytes(original)
    with pytest.raises(SimplifiedMigrationError, match="inconsistent"):
        ensure_current_simplified_schema(
            analyses_path=tmp_path / "analyses.json",
            v4_path=tmp_path / "codings_v4.json",
            target_path=target,
            backup_root=tmp_path / "old_schema_analyses",
        )
    assert target.read_bytes() == original
    assert not (tmp_path / "old_schema_analyses").exists()


def test_partial_hybrid_v4_entry_is_rejected_without_losing_new_comment_data() -> None:
    entry = _entry("hybrid", NuanceCoding())
    entry["coding"]["fields"]["relation_type_comment"] = "must survive"
    with pytest.raises(Exception):
        migrate_store_payload(_store([entry]))


def test_manifest_records_source_and_target_content_and_span_counts(tmp_path) -> None:
    analyses = tmp_path / "analyses.json"
    v4 = tmp_path / "codings_v4.json"
    target = tmp_path / "codings_simplified.json"
    analyses.write_text('{"analyses":[]}', encoding="utf-8")
    v4.write_text(
        json.dumps(
            _store(
                [
                    _entry(
                        "nuance-count",
                        NuanceCoding(fields=NuanceFields(x_y_connection="causes")),
                        {"nuance.x_y_connection": [_span("causes")]},
                    )
                ]
            )
        ),
        encoding="utf-8",
    )
    result = ensure_current_simplified_schema(
        analyses_path=analyses,
        v4_path=v4,
        target_path=target,
        backup_root=tmp_path / "old_schema_analyses",
    )
    manifest = json.loads((result.backup_dir / "migration_manifest.json").read_text())
    assert manifest["source_counts"]["coding_objects"] == 1
    assert manifest["source_counts"]["transcript_spans_including_audit_metadata"] == 1
    assert manifest["target_counts"]["coding_objects"] == 1
    assert manifest["target_counts"]["transcript_spans_including_audit_metadata"] == 1


def _disk_paths(tmp_path):
    analyses = tmp_path / "analyses.json"
    v4 = tmp_path / "codings_v4.json"
    target = tmp_path / "codings_simplified.json"
    backups = tmp_path / "old_schema_analyses"
    analyses.write_text('{"analyses":[]}', encoding="utf-8")
    v4.write_text(json.dumps(_store([])), encoding="utf-8")
    return analyses, v4, target, backups


def test_backup_checksum_failure_never_publishes_target(tmp_path, monkeypatch) -> None:
    analyses, v4, target, backups = _disk_paths(tmp_path)
    real_copy = migration.shutil.copy2

    def corrupt_copy(source, destination):
        result = real_copy(source, destination)
        if str(destination).endswith("codings_v4.json"):
            with open(destination, "ab") as handle:
                handle.write(b"corrupt")
        return result

    monkeypatch.setattr(migration.shutil, "copy2", corrupt_copy)
    with pytest.raises(SimplifiedMigrationError) as caught:
        ensure_current_simplified_schema(
            analyses_path=analyses,
            v4_path=v4,
            target_path=target,
            backup_root=backups,
        )
    assert caught.value.phase == "backup_verification"
    assert not target.exists()
    assert json.loads(v4.read_text())["coding_book_version"] == 4


def test_temporary_validation_failure_cleans_temp_and_does_not_publish(
    tmp_path, monkeypatch
) -> None:
    analyses, v4, target, backups = _disk_paths(tmp_path)
    real_validate = migration._validate_current_store
    calls = {"count": 0}

    def fail_second(payload):
        calls["count"] += 1
        if calls["count"] == 2:
            raise ValueError("synthetic temporary validation failure")
        return real_validate(payload)

    monkeypatch.setattr(migration, "_validate_current_store", fail_second)
    with pytest.raises(SimplifiedMigrationError) as caught:
        ensure_current_simplified_schema(
            analyses_path=analyses,
            v4_path=v4,
            target_path=target,
            backup_root=backups,
        )
    assert caught.value.phase == "temporary_file_validation"
    assert not target.exists()
    assert not list(tmp_path.glob("tmp*"))


def test_post_publish_failure_removes_new_target_and_retains_backup(
    tmp_path, monkeypatch
) -> None:
    analyses, v4, target, backups = _disk_paths(tmp_path)
    real_validate = migration._validate_current_store
    calls = {"count": 0}

    def fail_third(payload):
        calls["count"] += 1
        if calls["count"] == 3:
            raise ValueError("synthetic post-publish failure")
        return real_validate(payload)

    monkeypatch.setattr(migration, "_validate_current_store", fail_third)
    with pytest.raises(SimplifiedMigrationError) as caught:
        ensure_current_simplified_schema(
            analyses_path=analyses,
            v4_path=v4,
            target_path=target,
            backup_root=backups,
        )
    assert caught.value.phase == "post_publish_validation"
    assert caught.value.target_state == "removed_new_target"
    assert not target.exists()
    assert caught.value.backup_verified
    assert (caught.value.backup_dir / "codings_v4.json").exists()


def test_lock_contention_fails_before_backup_or_target(tmp_path, monkeypatch) -> None:
    analyses, v4, target, backups = _disk_paths(tmp_path)
    monkeypatch.setattr(
        migration,
        "_acquire_lock",
        lambda _path: (_ for _ in ()).throw(TimeoutError("busy")),
    )
    with pytest.raises(SimplifiedMigrationError) as caught:
        ensure_current_simplified_schema(
            analyses_path=analyses,
            v4_path=v4,
            target_path=target,
            backup_root=backups,
        )
    assert caught.value.phase == "migration_lock"
    assert not backups.exists()
    assert not target.exists()


def test_malformed_source_fails_safely_before_backup(tmp_path) -> None:
    v4 = tmp_path / "codings_v4.json"
    v4.write_text("{not-json", encoding="utf-8")
    with pytest.raises(SimplifiedMigrationError) as caught:
        ensure_current_simplified_schema(
            analyses_path=tmp_path / "analyses.json",
            v4_path=v4,
            target_path=tmp_path / "codings_simplified.json",
            backup_root=tmp_path / "old_schema_analyses",
        )
    assert caught.value.phase == "schema_detection"
    assert not (tmp_path / "old_schema_analyses").exists()
