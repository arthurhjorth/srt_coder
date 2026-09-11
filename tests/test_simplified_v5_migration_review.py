from __future__ import annotations

import json

from coding_books.simplified_v4.models import (
    DifferentiationCoding,
    DifferentiationFields,
    PerspectiveType,
    SimplifiedCodingEntry,
)
from domain.simplified_migration_review_service_v5 import (
    build_v5_migration_review,
    list_simplified_migration_backups,
)
from domain.simplified_schema_migration import ensure_current_simplified_schema


def test_review_shows_perspective_restructure_and_detects_later_edits(tmp_path) -> None:
    analyses = tmp_path / "analyses.json"
    v4 = tmp_path / "codings_v4.json"
    target = tmp_path / "codings_simplified.json"
    backups = tmp_path / "old_schema_analyses"
    analyses.write_text('{"analyses":[]}', encoding="utf-8")
    entry = SimplifiedCodingEntry(
        coding_id="diff-1",
        analysis_id="analysis-1",
        interview_file="test.srt",
        coding=DifferentiationCoding(
            fields=DifferentiationFields(
                perspectives=["leaders"],
                perspective_types=[PerspectiveType.ACTORS_ROLES],
            )
        ),
        created_by="coder",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    v4.write_text(
        json.dumps(
            {
                "storage_format_version": 1,
                "coding_book_version": 4,
                "codings": [entry.model_dump(mode="json")],
            }
        ),
        encoding="utf-8",
    )
    ensure_current_simplified_schema(
        analyses_path=analyses,
        v4_path=v4,
        target_path=target,
        backup_root=backups,
    )
    summaries = list_simplified_migration_backups(backups)
    assert len(summaries) == 1
    review = build_v5_migration_review(summaries[0], target)
    change = next(
        item
        for item in review.changes
        if item.change_type == "Perspective restructuring and copied types"
    )
    assert change.expected_after[0]["perspective_types"] == ["actors_roles"]
    assert change.current_matches_expected
    assert review.live_checksum_matches

    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["codings"][0]["coding"]["fields"]["perspectives"][0]["text"] = "later edit"
    target.write_text(json.dumps(payload), encoding="utf-8")
    later = build_v5_migration_review(summaries[0], target)
    assert later.live_checksum_matches is False
    assert not later.changes[0].current_matches_expected


def test_historical_v1_v3_manifest_remains_listable_as_summary(tmp_path) -> None:
    backup = tmp_path / "20260101T000000Z"
    backup.mkdir()
    (backup / "migration_manifest.json").write_text(
        json.dumps({"status": "completed", "target_schema_version": 3}),
        encoding="utf-8",
    )
    summaries = list_simplified_migration_backups(tmp_path)
    assert len(summaries) == 1
    assert not summaries[0].is_v4_to_v5
    assert "historical" in summaries[0].label
