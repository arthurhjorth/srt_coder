from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from domain.differentiation_migration import (
    CODING_SCHEMA_VERSION,
    CONDITION_LIST,
    OLD_CERTAINTY,
    OLD_EPISTEMIC_STANCE,
    OLD_PARENT_CONDITION,
    SCHEMA_V1_TO_V2,
    SCHEMA_V2_TO_V3,
    TARGET_CONDITION_DESCRIPTION,
    TARGET_UNCERTAINTY,
    coding_payload_uses_legacy_schema,
    ensure_current_coding_schema,
    migrate_export_payload,
    migrate_v2_to_v3_coding_entry_payload,
)
from models import CodingEntry


V1_FIXTURE = Path(__file__).parent / "fixtures" / "differentiation_migration_legacy.json"
V2_FIXTURE = Path(__file__).parent / "fixtures" / "nuance_migration_v2.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _span(text: str) -> dict:
    return {
        "start_segment_id": "seg-00001",
        "start_char_offset": 0,
        "end_segment_id": "seg-00001",
        "end_char_offset": len(text),
        "selected_text": text,
    }


def _span_multiset(coding: dict) -> list[str]:
    return sorted(
        json.dumps(span, sort_keys=True)
        for spans in (coding.get("field_spans") or {}).values()
        for span in spans
    )


def test_v2_to_v3_merges_uncertainty_and_appends_parent_condition_losslessly() -> None:
    original = _load(V2_FIXTURE)
    snapshot = deepcopy(original)

    migrated = migrate_v2_to_v3_coding_entry_payload(original)
    nuance = migrated["nuance"]
    spans = migrated["field_spans"]

    assert original == snapshot
    assert nuance[TARGET_UNCERTAINTY] == (
        "existing uncertainty\nlegacy certainty\nlegacy epistemic stance"
    )
    assert nuance[f"{TARGET_UNCERTAINTY}_comment"] == (
        "existing uncertainty comment\nlegacy certainty comment\nlegacy epistemic stance comment"
    )
    for source in (OLD_CERTAINTY, OLD_EPISTEMIC_STANCE, OLD_PARENT_CONDITION):
        assert source not in nuance
        assert f"{source}_comment" not in nuance

    assert nuance["stance_does_the_person_want_this_or_does_the_person_not_want_this_extract"] == (
        "retained preference stance"
    )
    assert nuance[CONDITION_LIST][0] == original["nuance"][CONDITION_LIST][0]
    assert len(nuance[CONDITION_LIST]) == 2
    assert nuance[CONDITION_LIST][1] == {
        TARGET_CONDITION_DESCRIPTION: "legacy parent condition",
        f"{TARGET_CONDITION_DESCRIPTION}_comment": "legacy parent condition comment",
    }

    assert [span["selected_text"] for span in spans[f"nuance.{TARGET_UNCERTAINTY}"]] == [
        "target span",
        "certainty span one",
        "certainty span two",
        "epistemic span",
    ]
    condition_target = f"nuance.{CONDITION_LIST}[1].{TARGET_CONDITION_DESCRIPTION}"
    assert [span["selected_text"] for span in spans[condition_target]] == ["parent condition span"]
    assert [span["selected_text"] for span in spans[f"{condition_target}_comment"]] == [
        "parent condition comment span"
    ]
    assert f"nuance.{CONDITION_LIST}[0].{TARGET_CONDITION_DESCRIPTION}" in spans
    nested_stance_path = f"nuance.{CONDITION_LIST}[0].{OLD_EPISTEMIC_STANCE}"
    assert spans[nested_stance_path] == original["field_spans"][nested_stance_path]
    assert _span_multiset(migrated) == _span_multiset(original)
    assert not coding_payload_uses_legacy_schema(migrated)
    CodingEntry.model_validate(migrated)


def test_parent_condition_is_created_for_comment_or_span_only_data() -> None:
    source = {
        "coding_id": "comment-span-only",
        "object_type": "nuance",
        "nuance": {
            OLD_PARENT_CONDITION: None,
            f"{OLD_PARENT_CONDITION}_comment": "comment only",
            CONDITION_LIST: None,
        },
        "field_spans": {f"nuance.{OLD_PARENT_CONDITION}": [_span("span only")]},
    }

    migrated = migrate_v2_to_v3_coding_entry_payload(source)
    conditions = migrated["nuance"][CONDITION_LIST]
    assert len(conditions) == 1
    assert conditions[0].get(TARGET_CONDITION_DESCRIPTION) is None
    assert conditions[0][f"{TARGET_CONDITION_DESCRIPTION}_comment"] == "comment only"
    target = f"nuance.{CONDITION_LIST}[0].{TARGET_CONDITION_DESCRIPTION}"
    assert migrated["field_spans"][target] == [_span("span only")]


def test_migration_preserves_existing_outer_whitespace_exactly() -> None:
    source = {
        "coding_id": "whitespace-preservation",
        "object_type": "nuance",
        "nuance": {
            TARGET_UNCERTAINTY: "  retained target  ",
            OLD_CERTAINTY: "  legacy certainty  ",
            OLD_EPISTEMIC_STANCE: None,
            OLD_PARENT_CONDITION: "   ",
        },
        "field_spans": {},
    }

    migrated = migrate_v2_to_v3_coding_entry_payload(source)

    assert migrated["nuance"][TARGET_UNCERTAINTY] == "  retained target  \n  legacy certainty  "
    assert migrated["nuance"][CONDITION_LIST][-1][TARGET_CONDITION_DESCRIPTION] == "   "


def test_non_text_retiring_value_fails_instead_of_being_dropped() -> None:
    source = {
        "coding_id": "malformed-retiring-value",
        "object_type": "nuance",
        "nuance": {
            TARGET_UNCERTAINTY: "retained",
            OLD_CERTAINTY: {"unexpected": "object"},
        },
        "field_spans": {},
    }

    try:
        migrate_v2_to_v3_coding_entry_payload(source)
    except ValueError as exc:
        assert OLD_CERTAINTY in str(exc)
    else:
        raise AssertionError("Expected malformed retiring data to stop migration")


def test_v2_startup_migration_backs_up_exact_source_and_runs_only_v2_step() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        analyses_path = root / "analyses.json"
        codings_path = root / "codings.json"
        backup_root = root / "old_schema_analyses"
        analyses_bytes = b'{"analyses": [{"analysis_id": "fixture-analysis"}]}\n'
        codings_bytes = (
            json.dumps({"schema_version": 2, "codings": [_load(V2_FIXTURE)]}, indent=2) + "\n"
        ).encode()
        analyses_path.write_bytes(analyses_bytes)
        codings_path.write_bytes(codings_bytes)

        result = ensure_current_coding_schema(
            analyses_path=analyses_path,
            codings_path=codings_path,
            backup_root=backup_root,
        )

        assert result.applied_steps == (SCHEMA_V2_TO_V3,)
        assert result.backup_dir is not None
        assert (result.backup_dir / "analyses.json").read_bytes() == analyses_bytes
        assert (result.backup_dir / "codings.json").read_bytes() == codings_bytes
        assert analyses_path.read_bytes() == analyses_bytes
        manifest = json.loads((result.backup_dir / "migration_manifest.json").read_text())
        assert manifest["source_schema_version"] == 2
        assert manifest["target_schema_version"] == 3
        assert manifest["applied_steps"] == [SCHEMA_V2_TO_V3]
        assert manifest["affected_coding_ids"] == ["fixture-nuance-v2"]
        assert manifest["step_migration_counts"][SCHEMA_V2_TO_V3] == {
            "values_with_content": 3,
            "comments_with_content": 3,
            "legacy_span_paths": 6,
            "legacy_spans": 7,
            "parent_conditions_created": 1,
        }
        migrated_store = json.loads(codings_path.read_text())
        assert migrated_store["schema_version"] == CODING_SCHEMA_VERSION
        assert not coding_payload_uses_legacy_schema(migrated_store["codings"][0])


def test_unversioned_v1_store_runs_both_steps_once_and_v3_is_noop() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        analyses_path = root / "analyses.json"
        codings_path = root / "codings.json"
        backup_root = root / "old_schema_analyses"
        analyses_path.write_text('{"analyses": []}\n')
        codings_path.write_text(
            json.dumps({"codings": [_load(V1_FIXTURE), _load(V2_FIXTURE)]}, indent=2) + "\n"
        )

        result = ensure_current_coding_schema(
            analyses_path=analyses_path,
            codings_path=codings_path,
            backup_root=backup_root,
        )
        assert result.applied_steps == (SCHEMA_V1_TO_V2, SCHEMA_V2_TO_V3)
        assert json.loads(codings_path.read_text())["schema_version"] == 3

        backup_count = len(list(backup_root.iterdir()))
        second = ensure_current_coding_schema(
            analyses_path=analyses_path,
            codings_path=codings_path,
            backup_root=backup_root,
        )
        assert second.status == "current"
        assert second.applied_steps == ()
        assert len(list(backup_root.iterdir())) == backup_count


def test_declared_v3_with_raw_v2_keys_is_safely_repaired() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        analyses_path = root / "analyses.json"
        codings_path = root / "codings.json"
        analyses_path.write_text('{"analyses": []}\n')
        codings_path.write_text(
            json.dumps({"schema_version": 3, "codings": [_load(V2_FIXTURE)]}, indent=2) + "\n"
        )

        result = ensure_current_coding_schema(
            analyses_path=analyses_path,
            codings_path=codings_path,
            backup_root=root / "old_schema_analyses",
        )

        assert result.applied_steps == (SCHEMA_V2_TO_V3,)
        migrated = json.loads(codings_path.read_text())
        assert migrated["schema_version"] == 3
        assert not coding_payload_uses_legacy_schema(migrated["codings"][0])


def test_exports_migrate_in_memory_by_declared_version_without_mutating_source() -> None:
    source = {
        "coding_schema_version": 2,
        "analyses": [],
        "codings": [_load(V2_FIXTURE)],
    }
    snapshot = deepcopy(source)
    migrated = migrate_export_payload(source)

    assert source == snapshot
    assert migrated["coding_schema_version"] == 3
    assert migrated["codings"][0]["nuance"][TARGET_UNCERTAINTY].endswith(
        "legacy certainty\nlegacy epistemic stance"
    )
    assert not coding_payload_uses_legacy_schema(migrated["codings"][0])


def test_repository_rejects_version_two_before_startup_even_without_retired_keys() -> None:
    from storage import coding_repo

    with TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "codings.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "codings": [{"coding_id": "v2-comparison", "object_type": "comparison"}],
                }
            )
            + "\n"
        )
        original_path = coding_repo.CODINGS_JSON
        coding_repo.CODINGS_JSON = path
        try:
            try:
                coding_repo.list_codings()
            except RuntimeError as exc:
                assert "before startup migration" in str(exc)
            else:
                raise AssertionError("Expected version-2 repository data to be rejected")
        finally:
            coding_repo.CODINGS_JSON = original_path


def test_differentiation_context_is_retained_but_excluded_from_agreement() -> None:
    from domain.agreement_service import load_agreement_export
    from ui.pages.analysis import DIFFERENTIATION_TOP_LEVEL_FIELDS
    from ui.pages.agreement import _coding_payload

    context = "context must remain stored"
    context_path = "differentiation.context_why_is_this_thing_being_considered_or_talked_about_extract"
    thing_path = "differentiation.thing_being_considered_extract"
    payload = {
        "coding_schema_version": 3,
        "analyses": [
            {
                "analysis_id": "a-context",
                "name": "Context fixture",
                "interview_file": "fixture.srt",
            }
        ],
        "codings": [
            {
                "coding_id": "c-context",
                "analysis_id": "a-context",
                "interview_file": "fixture.srt",
                "object_type": "differentiation",
                "differentiation": {
                    "thing_being_considered_extract": "visible thing",
                    "context_why_is_this_thing_being_considered_or_talked_about_extract": context,
                    "context_why_is_this_thing_being_considered_or_talked_about_extract_comment": "hidden comment",
                },
                "field_spans": {
                    thing_path: [_span("visible thing")],
                    context_path: [_span(context)],
                    f"{context_path}_comment": [_span("hidden comment")],
                },
            }
        ],
    }

    source = load_agreement_export(json.dumps(payload), source_name="context.json", source_index=0)
    coding = source.codings[0]
    assert coding.differentiation is not None
    assert coding.differentiation.context_why_is_this_thing_being_considered_or_talked_about_extract == context
    assert [annotation.field_path for annotation in source.annotations] == [thing_path]
    object_type, visible_payload = _coding_payload(coding)
    assert object_type == "differentiation"
    assert "context_why_is_this_thing_being_considered_or_talked_about_extract" not in visible_payload
    assert "context_why_is_this_thing_being_considered_or_talked_about_extract_comment" not in visible_payload
    assert "context_why_is_this_thing_being_considered_or_talked_about_extract" not in DIFFERENTIATION_TOP_LEVEL_FIELDS


def test_nuance_coding_view_uses_only_the_new_parent_schema_fields() -> None:
    from ui.pages.analysis import NUANCE_TOP_LEVEL_FIELDS

    assert TARGET_UNCERTAINTY in NUANCE_TOP_LEVEL_FIELDS
    assert OLD_CERTAINTY not in NUANCE_TOP_LEVEL_FIELDS
    assert OLD_EPISTEMIC_STANCE not in NUANCE_TOP_LEVEL_FIELDS
    assert OLD_PARENT_CONDITION not in NUANCE_TOP_LEVEL_FIELDS


def test_export_keeps_hidden_differentiation_context_and_uses_schema_three() -> None:
    from domain import analysis_exchange_service as exchange
    from models import Analysis, Differentiation

    analysis = Analysis(
        analysis_id="a-export-context",
        owner_username="fixture-user",
        interview_file="fixture.srt",
        name="Context export",
    )
    coding = CodingEntry(
        coding_id="c-export-context",
        analysis_id=analysis.analysis_id,
        interview_file=analysis.interview_file,
        object_type="differentiation",
        differentiation=Differentiation(
            context_why_is_this_thing_being_considered_or_talked_about_extract="retained context",
            context_why_is_this_thing_being_considered_or_talked_about_extract_comment="retained comment",
        ),
        field_spans={
            "differentiation.context_why_is_this_thing_being_considered_or_talked_about_extract": [
                _span("retained context")
            ]
        },
        created_by="fixture-user",
    )

    with TemporaryDirectory() as temp_dir:
        originals = (
            exchange.EXPORTS_DIR,
            exchange.list_analyses,
            exchange.list_codings,
            exchange.list_users,
        )
        exchange.EXPORTS_DIR = Path(temp_dir)
        exchange.list_analyses = lambda: [analysis]
        exchange.list_codings = lambda: [coding]
        exchange.list_users = lambda: []
        try:
            exported_path = exchange.export_analysis_to_file(analysis_id=analysis.analysis_id or "")
            payload = json.loads(exported_path.read_text())
        finally:
            exchange.EXPORTS_DIR, exchange.list_analyses, exchange.list_codings, exchange.list_users = originals

    exported = payload["codings"][0]
    assert payload["coding_schema_version"] == 3
    assert exported["differentiation"][
        "context_why_is_this_thing_being_considered_or_talked_about_extract"
    ] == "retained context"
    assert exported["field_spans"][
        "differentiation.context_why_is_this_thing_being_considered_or_talked_about_extract"
    ] == [_span("retained context")]
