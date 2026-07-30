from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "differentiation_migration_legacy.json"

OLD_WHY = "why_is_this_a_thing_or_how_did_it_happen_extract"
TARGET_WHY = "why_is_it_important_extract"
OLD_UNITARY = "what_is_wrong_with_taking_a_unitary_perspective_extract"
TARGET_PERSPECTIVES = "why_is_it_important_to_take_different_perspectives_extract"
OLD_COMPLEXITY = (
    "how_does_this_particular_perspective_add_complexity_or_difficulty_to_the_thing_being_considered_extract"
)
TARGET_IMPLICATIONS = "what_are_the_implications_extract"


def _load_legacy_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _migrate(payload: dict) -> dict:
    """Import locally so this contract test fails clearly until migration exists."""
    from domain.differentiation_migration import migrate_coding_entry_payload

    return migrate_coding_entry_payload(payload)


def test_fixture_reproduces_the_real_analysis_shape() -> None:
    """Characterize the sanitized fixture before exercising future migration code."""
    coding = _load_legacy_fixture()
    perspectives = coding["differentiation"]["perspectives_extract"]
    spans = coding["field_spans"]

    assert len(perspectives) == 2
    assert perspectives[0][OLD_COMPLEXITY]
    assert perspectives[0][TARGET_IMPLICATIONS]
    assert perspectives[1][OLD_COMPLEXITY]
    assert perspectives[1][TARGET_IMPLICATIONS] is None
    assert len(spans[f"differentiation.perspectives_extract[0].{OLD_COMPLEXITY}"]) == 3
    assert len(spans[f"differentiation.perspectives_extract[0].{TARGET_IMPLICATIONS}"]) == 1
    assert len(spans[f"differentiation.perspectives_extract[1].{OLD_COMPLEXITY}"]) == 2


def test_migration_collapses_all_three_field_pairs_without_data_loss() -> None:
    original = _load_legacy_fixture()
    original_snapshot = deepcopy(original)

    migrated = _migrate(original)
    differentiation = migrated["differentiation"]
    perspectives = differentiation["perspectives_extract"]

    # Migration is pure: loading/migrating must not mutate the caller's old data.
    assert original == original_snapshot
    assert migrated is not original

    assert differentiation[TARGET_WHY] == (
        "existing important text\nlegacy why-considered text"
    )
    assert differentiation[f"{TARGET_WHY}_comment"] == (
        "existing important comment\nlegacy why-considered comment"
    )
    assert OLD_WHY not in differentiation
    assert f"{OLD_WHY}_comment" not in differentiation

    assert differentiation[TARGET_PERSPECTIVES] == (
        "existing perspectives reason\nlegacy unitary-perspective text"
    )
    assert differentiation[f"{TARGET_PERSPECTIVES}_comment"] == (
        "existing perspectives comment\nlegacy unitary-perspective comment"
    )
    assert OLD_UNITARY not in differentiation
    assert f"{OLD_UNITARY}_comment" not in differentiation

    assert perspectives[0][TARGET_IMPLICATIONS] == (
        "existing implications zero\nlegacy complexity zero"
    )
    assert perspectives[0][f"{TARGET_IMPLICATIONS}_comment"] == (
        "existing implications comment zero\nlegacy complexity comment zero"
    )
    assert perspectives[1][TARGET_IMPLICATIONS] == "legacy complexity one"
    assert perspectives[1][f"{TARGET_IMPLICATIONS}_comment"] is None
    for perspective in perspectives:
        assert OLD_COMPLEXITY not in perspective
        assert f"{OLD_COMPLEXITY}_comment" not in perspective


def test_migration_rekeys_and_appends_legacy_spans_in_existing_then_old_order() -> None:
    migrated = _migrate(_load_legacy_fixture())
    spans = migrated["field_spans"]

    why_target = f"differentiation.{TARGET_WHY}"
    why_source = f"differentiation.{OLD_WHY}"
    perspectives_target = f"differentiation.{TARGET_PERSPECTIVES}"
    perspectives_source = f"differentiation.{OLD_UNITARY}"
    implications_0_target = f"differentiation.perspectives_extract[0].{TARGET_IMPLICATIONS}"
    complexity_0_source = f"differentiation.perspectives_extract[0].{OLD_COMPLEXITY}"
    implications_1_target = f"differentiation.perspectives_extract[1].{TARGET_IMPLICATIONS}"
    complexity_1_source = f"differentiation.perspectives_extract[1].{OLD_COMPLEXITY}"

    assert [span["selected_text"] for span in spans[why_target]] == [
        "important-target-span",
        "why-source-span",
    ]
    assert why_source not in spans
    assert [span["selected_text"] for span in spans[perspectives_target]] == [
        "perspectives-target-span",
        "unitary-source-span",
    ]
    assert perspectives_source not in spans
    assert [span["selected_text"] for span in spans[implications_0_target]] == [
        "implications-target-span",
        "complexity-source-span-zero-a",
        "complexity-source-span-zero-b",
        "complexity-source-span-zero-c",
    ]
    assert complexity_0_source not in spans
    assert [span["selected_text"] for span in spans[implications_1_target]] == [
        "complexity-source-span-one-a",
        "complexity-source-span-one-b",
    ]
    assert complexity_1_source not in spans

    # A migration must not disturb field spans belonging to other schema paths.
    assert spans["comparison.comparand"][0]["selected_text"] == "unrelated-span-must-survive"


def test_migration_rekeys_comment_spans_too() -> None:
    coding = _load_legacy_fixture()
    spans = coding["field_spans"]

    def marker(text: str) -> dict:
        return {
            "start_segment_id": "seg-00100",
            "start_char_offset": 0,
            "end_segment_id": "seg-00100",
            "end_char_offset": 1,
            "selected_text": text,
        }

    mappings = [
        (f"differentiation.{OLD_WHY}_comment", f"differentiation.{TARGET_WHY}_comment"),
        (
            f"differentiation.{OLD_UNITARY}_comment",
            f"differentiation.{TARGET_PERSPECTIVES}_comment",
        ),
        (
            f"differentiation.perspectives_extract[0].{OLD_COMPLEXITY}_comment",
            f"differentiation.perspectives_extract[0].{TARGET_IMPLICATIONS}_comment",
        ),
    ]
    for index, (source_key, target_key) in enumerate(mappings):
        spans[target_key] = [marker(f"target-comment-{index}")]
        spans[source_key] = [marker(f"source-comment-{index}")]

    migrated_spans = _migrate(coding)["field_spans"]
    for index, (source_key, target_key) in enumerate(mappings):
        assert source_key not in migrated_spans
        assert [span["selected_text"] for span in migrated_spans[target_key]] == [
            f"target-comment-{index}",
            f"source-comment-{index}",
        ]


def test_migration_is_idempotent_and_preserves_unrelated_data() -> None:
    original = _load_legacy_fixture()
    migrated_once = _migrate(original)
    migrated_twice = _migrate(migrated_once)

    assert migrated_twice == migrated_once
    assert migrated_once["coding_id"] == original["coding_id"]
    assert migrated_once["analysis_id"] == original["analysis_id"]
    assert migrated_once["interview_file"] == original["interview_file"]
    assert migrated_once["note"] == original["note"]
    assert (
        migrated_once["differentiation"]["thing_being_considered_extract"]
        == original["differentiation"]["thing_being_considered_extract"]
    )
    assert (
        migrated_once["differentiation"][
            "context_why_is_this_thing_being_considered_or_talked_about_extract"
        ]
        == original["differentiation"][
            "context_why_is_this_thing_being_considered_or_talked_about_extract"
        ]
    )


def test_startup_migration_creates_verified_backup_before_atomic_replacement() -> None:
    from domain.differentiation_migration import ensure_current_coding_schema

    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        analyses_path = root / "analyses.json"
        codings_path = root / "codings.json"
        backup_root = root / "old_schema_analyses"
        analyses_bytes = b'{\n  "analyses": [{"analysis_id": "fixture-analysis"}]\n}\n'
        codings_bytes = (
            json.dumps({"codings": [_load_legacy_fixture()]}, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        analyses_path.write_bytes(analyses_bytes)
        codings_path.write_bytes(codings_bytes)

        result = ensure_current_coding_schema(
            analyses_path=analyses_path,
            codings_path=codings_path,
            backup_root=backup_root,
        )

        assert result.status == "migrated"
        assert result.migrated_codings == 1
        assert result.backup_dir is not None
        assert (result.backup_dir / "analyses.json").read_bytes() == analyses_bytes
        assert (result.backup_dir / "codings.json").read_bytes() == codings_bytes
        manifest = json.loads((result.backup_dir / "migration_manifest.json").read_text())
        assert manifest["target_schema_version"] == 2
        assert manifest["status"] == "completed"
        assert manifest["coding_count"] == 1
        assert manifest["legacy_coding_ids"] == ["fixture-from-anders-bjaeldager-analysis"]
        assert manifest["migration_counts"] == {
            "values_with_content": 4,
            "comments_with_content": 3,
            "legacy_span_paths": 4,
            "legacy_spans": 7,
        }
        assert manifest["post_migration_codings_sha256"]
        assert manifest["sha256"]["analyses.json"]["source"] == manifest["sha256"]["analyses.json"]["backup"]
        assert manifest["sha256"]["codings.json"]["source"] == manifest["sha256"]["codings.json"]["backup"]
        assert analyses_path.read_bytes() == analyses_bytes
        migrated_store = json.loads(codings_path.read_text())
        assert migrated_store["schema_version"] == 2
        assert not any(OLD_COMPLEXITY in key for key in migrated_store["codings"][0]["field_spans"])

        backup_count = len(list(backup_root.iterdir()))
        second = ensure_current_coding_schema(
            analyses_path=analyses_path,
            codings_path=codings_path,
            backup_root=backup_root,
        )
        assert second.status == "current"
        assert len(list(backup_root.iterdir())) == backup_count


def test_startup_migration_aborts_without_touching_codings_when_analysis_store_is_missing() -> None:
    from domain.differentiation_migration import MigrationStartupError, ensure_current_coding_schema

    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        analyses_path = root / "analyses.json"
        codings_path = root / "codings.json"
        original = (json.dumps({"codings": [_load_legacy_fixture()]}, indent=2) + "\n").encode()
        codings_path.write_bytes(original)

        try:
            ensure_current_coding_schema(
                analyses_path=analyses_path,
                codings_path=codings_path,
                backup_root=root / "old_schema_analyses",
            )
        except MigrationStartupError as exc:
            assert exc.phase == "schema_recheck"
            assert exc.originals_state == "untouched"
        else:
            raise AssertionError("Expected migration to abort")
        assert codings_path.read_bytes() == original


def test_startup_migration_restores_verified_backup_after_post_replace_failure() -> None:
    from domain import differentiation_migration as migration

    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        analyses_path = root / "analyses.json"
        codings_path = root / "codings.json"
        analyses_path.write_text('{"analyses": []}\n')
        original = (json.dumps({"codings": [_load_legacy_fixture()]}, indent=2) + "\n").encode()
        codings_path.write_bytes(original)

        original_validator = migration._validate_version_two_store
        calls = {"count": 0}

        def fail_after_replace(payload: dict) -> None:
            calls["count"] += 1
            original_validator(payload)
            if calls["count"] == 3:
                raise ValueError("simulated post-replace validation failure")

        migration._validate_version_two_store = fail_after_replace
        try:
            try:
                migration.ensure_current_coding_schema(
                    analyses_path=analyses_path,
                    codings_path=codings_path,
                    backup_root=root / "old_schema_analyses",
                )
            except migration.MigrationStartupError as exc:
                assert exc.phase == "post_replace_validation"
                assert exc.originals_state == "restored"
            else:
                raise AssertionError("Expected simulated validation failure")
        finally:
            migration._validate_version_two_store = original_validator

        assert codings_path.read_bytes() == original


def test_future_schema_version_is_rejected_without_creating_a_backup() -> None:
    from domain.differentiation_migration import MigrationStartupError, ensure_current_coding_schema

    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        codings_path = root / "codings.json"
        codings_path.write_text(json.dumps({"schema_version": 999, "codings": []}) + "\n")
        try:
            ensure_current_coding_schema(
                analyses_path=root / "analyses.json",
                codings_path=codings_path,
                backup_root=root / "old_schema_analyses",
            )
        except MigrationStartupError as exc:
            assert exc.phase == "schema_detection"
        else:
            raise AssertionError("Expected unsupported schema failure")
        assert not (root / "old_schema_analyses").exists()


def test_backup_failure_aborts_before_live_replacement() -> None:
    from domain import differentiation_migration as migration

    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        analyses_path = root / "analyses.json"
        codings_path = root / "codings.json"
        analyses_path.write_text('{"analyses": []}\n')
        original = (json.dumps({"codings": [_load_legacy_fixture()]}, indent=2) + "\n").encode()
        codings_path.write_bytes(original)
        original_copy = migration.shutil.copy2

        def fail_copy(_source, _target):
            raise OSError("simulated backup failure")

        migration.shutil.copy2 = fail_copy
        try:
            try:
                migration.ensure_current_coding_schema(
                    analyses_path=analyses_path,
                    codings_path=codings_path,
                    backup_root=root / "old_schema_analyses",
                )
            except migration.MigrationStartupError as exc:
                assert exc.phase == "backup_creation"
                assert exc.originals_state == "untouched"
            else:
                raise AssertionError("Expected simulated backup failure")
        finally:
            migration.shutil.copy2 = original_copy
        assert codings_path.read_bytes() == original


def test_old_export_is_migrated_in_memory_for_agreement_loading() -> None:
    from domain.agreement_service import load_agreement_export

    coding = _load_legacy_fixture()
    source_payload = {
        "export_version": "1",
        "analyses": [
            {
                "analysis_id": coding["analysis_id"],
                "owner_username": "fixture-owner",
                "interview_file": coding["interview_file"],
                "name": "Legacy fixture",
            }
        ],
        "codings": [coding],
        "users": [],
    }
    source_snapshot = deepcopy(source_payload)
    source = load_agreement_export(
        json.dumps(source_payload),
        source_name="legacy.json",
        source_index=0,
    )

    assert source_payload == source_snapshot
    assert source.codings[0].differentiation is not None
    assert source.codings[0].differentiation.why_is_it_important_extract == (
        "existing important text\nlegacy why-considered text"
    )
    assert all(OLD_WHY not in annotation.field_path for annotation in source.annotations)
    assert all(OLD_UNITARY not in annotation.field_path for annotation in source.annotations)
    assert all(OLD_COMPLEXITY not in annotation.field_path for annotation in source.annotations)


def test_new_differentiation_objects_start_with_two_empty_perspectives() -> None:
    from domain import coding_service

    saved = {"codings": None}
    original_list = coding_service.list_codings
    original_save = coding_service.save_codings
    coding_service.list_codings = lambda: []
    coding_service.save_codings = lambda codings: saved.__setitem__("codings", codings)
    try:
        created = coding_service.create_object_entry(
            analysis_id="fixture-analysis",
            interview_file="fixture.srt",
            object_type="differentiation",
            created_by="fixture-user",
        )
    finally:
        coding_service.list_codings = original_list
        coding_service.save_codings = original_save

    assert created.differentiation is not None
    assert created.differentiation.perspectives_extract is not None
    assert len(created.differentiation.perspectives_extract) == 2
    assert saved["codings"] == [created]


def test_failure_message_is_plain_technical_and_copyable() -> None:
    from domain.differentiation_migration import MigrationStartupError, format_migration_failure

    error = MigrationStartupError(
        "simulated failure",
        phase="backup_verification",
        analyses_path=Path("coded_data/analyses.json"),
        codings_path=Path("coded_data/codings.json"),
        backup_dir=Path("coded_data/old_schema_analyses/example"),
        backup_verified=True,
        originals_state="untouched",
    )
    message = format_migration_failure(error)
    assert "server was not started" in message
    assert "live files were not replaced" in message
    assert "Verified backup folder" in message
    assert "phase: backup_verification" in message
    assert "MigrationStartupError: simulated failure" in message
    assert "copy this entire message and send it to Arthur" in message


def test_version_two_store_with_legacy_keys_is_still_migrated() -> None:
    from domain.differentiation_migration import ensure_current_coding_schema

    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        analyses_path = root / "analyses.json"
        codings_path = root / "codings.json"
        analyses_path.write_text('{"analyses": []}\n')
        codings_path.write_text(
            json.dumps(
                {"schema_version": 2, "codings": [_load_legacy_fixture()]},
                indent=2,
            )
            + "\n"
        )
        result = ensure_current_coding_schema(
            analyses_path=analyses_path,
            codings_path=codings_path,
            backup_root=root / "old_schema_analyses",
        )
        assert result.status == "migrated"
        migrated = json.loads(codings_path.read_text())
        assert migrated["schema_version"] == 2
        assert not any(
            OLD_COMPLEXITY in key
            for key in migrated["codings"][0]["field_spans"]
        )
