from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from domain.differentiation_migration import ensure_current_coding_schema
from domain.migration_review_service import build_migration_review, list_migration_backups


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "differentiation_migration_legacy.json"
V2_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "nuance_migration_v2.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _migrated_temp_store(root: Path):
    coding = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    analyses_path = root / "analyses.json"
    codings_path = root / "codings.json"
    analyses_path.write_text(
        json.dumps(
            {
                "analyses": [
                    {
                        "analysis_id": coding["analysis_id"],
                        "name": "Sanitized migration fixture",
                        "owner_username": "fixture-owner",
                        "interview_file": coding["interview_file"],
                    }
                ]
            },
            indent=2,
        )
        + "\n"
    )
    codings_path.write_text(json.dumps({"codings": [coding]}, indent=2) + "\n")
    result = ensure_current_coding_schema(
        analyses_path=analyses_path,
        codings_path=codings_path,
        backup_root=root / "old_schema_analyses",
    )
    assert result.backup_dir is not None
    return result.backup_dir, codings_path


def _migrated_v2_temp_store(root: Path):
    coding = json.loads(V2_FIXTURE_PATH.read_text(encoding="utf-8"))
    analyses_path = root / "analyses.json"
    codings_path = root / "codings.json"
    analyses_path.write_text(
        json.dumps(
            {
                "analyses": [
                    {
                        "analysis_id": coding["analysis_id"],
                        "name": "Nuance v2 fixture",
                        "owner_username": "fixture-owner",
                        "interview_file": coding["interview_file"],
                    }
                ]
            },
            indent=2,
        )
        + "\n"
    )
    codings_path.write_text(json.dumps({"schema_version": 2, "codings": [coding]}, indent=2) + "\n")
    result = ensure_current_coding_schema(
        analyses_path=analyses_path,
        codings_path=codings_path,
        backup_root=root / "old_schema_analyses",
    )
    assert result.backup_dir is not None
    return result.backup_dir, codings_path


def test_review_reconstructs_before_expected_and_current_without_writes() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        backup_dir, codings_path = _migrated_temp_store(root)
        hashes_before = {
            "backup": _sha(backup_dir / "codings.json"),
            "live": _sha(codings_path),
        }

        review = build_migration_review(backup_dir, codings_path)

        assert review.live_store_matches_migration_checksum is True
        assert len(review.analyses) == 1
        assert review.changed_coding_count == 1
        assert review.changed_field_count == 7
        assert review.moved_span_count == 7
        assert all(
            change.current_matches_expected
            for analysis in review.analyses
            for change in analysis.changes
        )
        assert review.analyses[0].name == "Sanitized migration fixture"
        assert hashes_before == {
            "backup": _sha(backup_dir / "codings.json"),
            "live": _sha(codings_path),
        }


def test_review_distinguishes_later_live_edits_from_expected_migration() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        backup_dir, codings_path = _migrated_temp_store(root)
        store = json.loads(codings_path.read_text())
        store["codings"][0]["differentiation"]["why_is_it_important_extract"] = "edited later"
        codings_path.write_text(json.dumps(store, indent=2) + "\n")

        review = build_migration_review(backup_dir, codings_path)
        changes = [change for analysis in review.analyses for change in analysis.changes]

        assert review.live_store_matches_migration_checksum is False
        why_change = next(change for change in changes if change.target_path.endswith("why_is_it_important_extract"))
        assert why_change.expected_after == "existing important text\nlegacy why-considered text"
        assert why_change.current_after == "edited later"
        assert why_change.current_matches_expected is False


def test_backup_listing_ignores_incomplete_directories_and_orders_newest_first() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        first, _codings_path = _migrated_temp_store(root)
        incomplete = root / "old_schema_analyses" / "99999999-incomplete"
        incomplete.mkdir()
        (incomplete / "analyses.json").write_text('{"analyses": []}\n')

        backups = list_migration_backups(root / "old_schema_analyses")
        assert [backup.directory for backup in backups] == [first]


def test_review_shows_v2_uncertainty_merge_and_appended_condition() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        backup_dir, codings_path = _migrated_v2_temp_store(root)

        review = build_migration_review(backup_dir, codings_path)
        changes = [change for analysis in review.analyses for change in analysis.changes]

        assert review.live_store_matches_migration_checksum is True
        assert review.live_store_is_later_schema is False
        assert review.applied_steps == ("v2_to_v3",)
        assert review.changed_coding_count == 1
        assert review.changed_field_count == 6
        assert review.moved_span_count == 7
        assert all(change.current_matches_expected for change in changes)
        assert sum(change.target_path.endswith("uncertainty_about_causality_extract") for change in changes) == 2
        assert any("condition_antecedent_reason[1]" in change.target_path for change in changes)


def test_review_identifies_historical_backup_followed_by_later_schema_migration() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        backup_dir, codings_path = _migrated_temp_store(root)
        manifest_path = backup_dir / "migration_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["target_schema_version"] = 2
        manifest.pop("applied_steps", None)
        manifest["post_migration_codings_sha256"] = "historical-v2-checksum"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

        review = build_migration_review(backup_dir, codings_path)

        assert review.live_schema_version == 3
        assert review.backup_target_schema_version == 2
        assert review.live_store_matches_migration_checksum is False
        assert review.live_store_is_later_schema is True
        assert review.applied_steps == ("v1_to_v2",)


def test_review_infers_v2_step_for_transitional_schema_three_manifest() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        backup_dir, codings_path = _migrated_v2_temp_store(root)
        manifest_path = backup_dir / "migration_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest.pop("applied_steps", None)
        manifest.pop("source_schema_version", None)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

        review = build_migration_review(backup_dir, codings_path)

        assert review.applied_steps == ("v2_to_v3",)
        assert review.live_store_matches_migration_checksum is True
