from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from tempfile import NamedTemporaryFile
import time
import uuid


CODING_SCHEMA_VERSION = 3
SCHEMA_V1_TO_V2 = "v1_to_v2"
SCHEMA_V2_TO_V3 = "v2_to_v3"

OLD_WHY = "why_is_this_a_thing_or_how_did_it_happen_extract"
TARGET_WHY = "why_is_it_important_extract"
OLD_UNITARY = "what_is_wrong_with_taking_a_unitary_perspective_extract"
TARGET_PERSPECTIVES = "why_is_it_important_to_take_different_perspectives_extract"
OLD_COMPLEXITY = (
    "how_does_this_particular_perspective_add_complexity_or_difficulty_to_the_thing_being_considered_extract"
)
TARGET_IMPLICATIONS = "what_are_the_implications_extract"

OLD_CERTAINTY = (
    "certitude_about_outcome_or_epistemic_modality_does_the_person_say_that_this_will_happen_or_could_it_happen_or_might_it_happen_extract"
)
OLD_EPISTEMIC_STANCE = "epistemic_stance_extract"
TARGET_UNCERTAINTY = "uncertainty_about_causality_extract"
OLD_PARENT_CONDITION = "condition_antecedent_reason_extract"
CONDITION_LIST = "condition_antecedent_reason"
TARGET_CONDITION_DESCRIPTION = (
    "description_an_event_or_state_that_contributes_or_contributed_towards_increasing_the_likelihood_of_the_outcome_or_towards_explaining_why_it_happened_extract"
)

_LEGACY_FIELD_NAMES = {OLD_WHY, OLD_UNITARY, OLD_COMPLEXITY}
_V2_LEGACY_FIELD_NAMES = {OLD_CERTAINTY, OLD_EPISTEMIC_STANCE, OLD_PARENT_CONDITION}
_V2_LEGACY_SPAN_PATHS = {
    f"nuance.{field_name}{suffix}"
    for field_name in _V2_LEGACY_FIELD_NAMES
    for suffix in ("", "_comment")
}
_TOP_LEVEL_MAPPINGS = (
    (OLD_WHY, TARGET_WHY),
    (OLD_UNITARY, TARGET_PERSPECTIVES),
)
_PERSPECTIVE_SPAN_RE = re.compile(
    rf"^(differentiation\.perspectives_extract\[\d+\]\.){re.escape(OLD_COMPLEXITY)}(_comment)?$"
)


@dataclass(frozen=True)
class MigrationResult:
    status: str
    migrated_codings: int = 0
    backup_dir: Path | None = None
    applied_steps: tuple[str, ...] = ()


class MigrationStartupError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        phase: str,
        analyses_path: Path,
        codings_path: Path,
        backup_dir: Path | None = None,
        backup_verified: bool = False,
        originals_state: str = "untouched",
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.analyses_path = analyses_path
        self.codings_path = codings_path
        self.backup_dir = backup_dir
        self.backup_verified = backup_verified
        self.originals_state = originals_state


def _merge_text(target, legacy):
    target_has_content = isinstance(target, str) and target != ""
    legacy_has_content = isinstance(legacy, str) and legacy != ""
    if target_has_content and legacy_has_content:
        return f"{target}\n{legacy}"
    if legacy_has_content:
        return legacy
    return target


def _merge_field(payload: dict, old_name: str, target_name: str) -> None:
    if old_name not in payload:
        return
    legacy_value = payload.pop(old_name)
    if legacy_value is not None and not isinstance(legacy_value, str):
        raise ValueError(f"Legacy field {old_name} must contain text or null")
    if target_name in payload:
        target_value = payload.get(target_name)
        if target_value is not None and not isinstance(target_value, str):
            raise ValueError(f"Target field {target_name} must contain text or null")
        payload[target_name] = _merge_text(target_value, legacy_value)
    elif legacy_value is not None:
        payload[target_name] = legacy_value


def _rekey_span_list(field_spans: dict, source_key: str, target_key: str) -> None:
    if source_key not in field_spans:
        return
    legacy_spans = field_spans.pop(source_key)
    if not isinstance(legacy_spans, list):
        raise ValueError(f"Legacy span path {source_key} must contain a list")
    target_spans = field_spans.get(target_key)
    if target_spans is None:
        target_spans = []
    elif not isinstance(target_spans, list):
        raise ValueError(f"Target span path {target_key} must contain a list")
    combined = list(target_spans) + list(legacy_spans)
    if combined or target_key in field_spans:
        field_spans[target_key] = combined


def migrate_v1_to_v2_coding_entry_payload(payload: dict) -> dict:
    """Return a version-2 coding dictionary without mutating the input."""
    migrated = deepcopy(payload)
    differentiation = migrated.get("differentiation")
    if isinstance(differentiation, dict):
        for old_name, target_name in _TOP_LEVEL_MAPPINGS:
            _merge_field(differentiation, old_name, target_name)
            _merge_field(differentiation, f"{old_name}_comment", f"{target_name}_comment")

        perspectives = differentiation.get("perspectives_extract")
        if isinstance(perspectives, list):
            for perspective in perspectives:
                if not isinstance(perspective, dict):
                    continue
                _merge_field(perspective, OLD_COMPLEXITY, TARGET_IMPLICATIONS)
                _merge_field(
                    perspective,
                    f"{OLD_COMPLEXITY}_comment",
                    f"{TARGET_IMPLICATIONS}_comment",
                )

    field_spans = migrated.get("field_spans")
    if isinstance(field_spans, dict):
        for old_name, target_name in _TOP_LEVEL_MAPPINGS:
            _rekey_span_list(
                field_spans,
                f"differentiation.{old_name}",
                f"differentiation.{target_name}",
            )
            _rekey_span_list(
                field_spans,
                f"differentiation.{old_name}_comment",
                f"differentiation.{target_name}_comment",
            )

        for source_key in list(field_spans):
            match = _PERSPECTIVE_SPAN_RE.match(str(source_key))
            if not match:
                continue
            target_key = f"{match.group(1)}{TARGET_IMPLICATIONS}{match.group(2) or ''}"
            _rekey_span_list(field_spans, source_key, target_key)

    return migrated


def coding_payload_needs_v1_to_v2(payload: dict) -> bool:
    differentiation = payload.get("differentiation")
    if isinstance(differentiation, dict):
        if any(name in differentiation for name in (OLD_WHY, f"{OLD_WHY}_comment", OLD_UNITARY, f"{OLD_UNITARY}_comment")):
            return True
        perspectives = differentiation.get("perspectives_extract")
        if isinstance(perspectives, list):
            for perspective in perspectives:
                if isinstance(perspective, dict) and (
                    OLD_COMPLEXITY in perspective or f"{OLD_COMPLEXITY}_comment" in perspective
                ):
                    return True
    field_spans = payload.get("field_spans")
    if isinstance(field_spans, dict):
        return any(any(name in str(key) for name in _LEGACY_FIELD_NAMES) for key in field_spans)
    return False


def _has_text(value) -> bool:
    return isinstance(value, str) and value != ""


def _has_span_data(field_spans: dict | None, field_path: str) -> bool:
    if not isinstance(field_spans, dict) or field_path not in field_spans:
        return False
    spans = field_spans[field_path]
    if not isinstance(spans, list):
        raise ValueError(f"Legacy span path {field_path} must contain a list")
    return bool(spans)


def migrate_v2_to_v3_coding_entry_payload(payload: dict) -> dict:
    """Return a version-3 coding dictionary without mutating the input."""
    migrated = deepcopy(payload)
    nuance = migrated.get("nuance")
    field_spans = migrated.get("field_spans")

    if isinstance(nuance, dict):
        for old_name in (OLD_CERTAINTY, OLD_EPISTEMIC_STANCE):
            _merge_field(nuance, old_name, TARGET_UNCERTAINTY)
            _merge_field(nuance, f"{old_name}_comment", f"{TARGET_UNCERTAINTY}_comment")

        if isinstance(field_spans, dict):
            for old_name in (OLD_CERTAINTY, OLD_EPISTEMIC_STANCE):
                _rekey_span_list(
                    field_spans,
                    f"nuance.{old_name}",
                    f"nuance.{TARGET_UNCERTAINTY}",
                )
                _rekey_span_list(
                    field_spans,
                    f"nuance.{old_name}_comment",
                    f"nuance.{TARGET_UNCERTAINTY}_comment",
                )

        parent_value = nuance.get(OLD_PARENT_CONDITION)
        parent_comment = nuance.get(f"{OLD_PARENT_CONDITION}_comment")
        if parent_value is not None and not isinstance(parent_value, str):
            raise ValueError(f"Legacy field {OLD_PARENT_CONDITION} must contain text or null")
        if parent_comment is not None and not isinstance(parent_comment, str):
            raise ValueError(f"Legacy field {OLD_PARENT_CONDITION}_comment must contain text or null")
        parent_value_path = f"nuance.{OLD_PARENT_CONDITION}"
        parent_comment_path = f"{parent_value_path}_comment"
        has_parent_data = (
            _has_text(parent_value)
            or _has_text(parent_comment)
            or _has_span_data(field_spans, parent_value_path)
            or _has_span_data(field_spans, parent_comment_path)
        )
        nuance.pop(OLD_PARENT_CONDITION, None)
        nuance.pop(f"{OLD_PARENT_CONDITION}_comment", None)

        if has_parent_data:
            existing_conditions = nuance.get(CONDITION_LIST)
            if existing_conditions is None:
                conditions: list[dict] = []
            elif isinstance(existing_conditions, list):
                conditions = list(existing_conditions)
            else:
                raise ValueError(f"nuance.{CONDITION_LIST} must contain a list")
            condition_index = len(conditions)
            new_condition: dict = {}
            if parent_value is not None:
                new_condition[TARGET_CONDITION_DESCRIPTION] = parent_value
            if parent_comment is not None:
                new_condition[f"{TARGET_CONDITION_DESCRIPTION}_comment"] = parent_comment
            conditions.append(new_condition)
            nuance[CONDITION_LIST] = conditions

            if isinstance(field_spans, dict):
                target_prefix = f"nuance.{CONDITION_LIST}[{condition_index}].{TARGET_CONDITION_DESCRIPTION}"
                _rekey_span_list(field_spans, parent_value_path, target_prefix)
                _rekey_span_list(field_spans, parent_comment_path, f"{target_prefix}_comment")
        elif isinstance(field_spans, dict):
            # Empty legacy span lists contain no annotations, but their retired paths
            # still need to be removed from the current schema.
            field_spans.pop(parent_value_path, None)
            field_spans.pop(parent_comment_path, None)

    return migrated


def coding_payload_needs_v2_to_v3(payload: dict) -> bool:
    nuance = payload.get("nuance")
    if isinstance(nuance, dict) and any(
        name in nuance or f"{name}_comment" in nuance
        for name in _V2_LEGACY_FIELD_NAMES
    ):
        return True
    field_spans = payload.get("field_spans")
    if isinstance(field_spans, dict):
        return any(str(key) in _V2_LEGACY_SPAN_PATHS for key in field_spans)
    return False


def coding_payload_uses_legacy_schema(payload: dict) -> bool:
    return coding_payload_needs_v1_to_v2(payload) or coding_payload_needs_v2_to_v3(payload)


def migrate_coding_entry_payload(payload: dict) -> dict:
    """Return a current-schema coding dictionary without mutating the input."""
    return migrate_v2_to_v3_coding_entry_payload(
        migrate_v1_to_v2_coding_entry_payload(payload)
    )


def _validate_declared_version(version, *, field_name: str) -> int | None:
    if version is not None and (isinstance(version, bool) or not isinstance(version, int)):
        raise ValueError(f"{field_name} must be an integer")
    if isinstance(version, int) and version > CODING_SCHEMA_VERSION:
        raise ValueError(f"Unsupported future coding schema version: {version}")
    return version


def _required_migration_steps(payload: dict, *, version_field: str) -> tuple[str, ...]:
    version = _validate_declared_version(payload.get(version_field), field_name=version_field)
    codings = payload.get("codings")
    if codings is None:
        codings = []
    if not isinstance(codings, list):
        raise ValueError("codings must be a list")
    needs_v1 = version is None or version < 2 or any(
        isinstance(coding, dict) and coding_payload_needs_v1_to_v2(coding)
        for coding in codings
    )
    needs_v2 = version is None or version < 3 or any(
        isinstance(coding, dict) and coding_payload_needs_v2_to_v3(coding)
        for coding in codings
    )
    steps: list[str] = []
    if needs_v1:
        steps.append(SCHEMA_V1_TO_V2)
    if needs_v2:
        steps.append(SCHEMA_V2_TO_V3)
    return tuple(steps)


def _migrate_codings(codings: list, steps: tuple[str, ...]) -> list:
    migrated = deepcopy(codings)
    if SCHEMA_V1_TO_V2 in steps:
        migrated = [
            migrate_v1_to_v2_coding_entry_payload(coding) if isinstance(coding, dict) else coding
            for coding in migrated
        ]
    if SCHEMA_V2_TO_V3 in steps:
        migrated = [
            migrate_v2_to_v3_coding_entry_payload(coding) if isinstance(coding, dict) else coding
            for coding in migrated
        ]
    return migrated


def migrate_export_payload(payload: dict) -> dict:
    """Migrate an import/agreement bundle in memory; never alter its source file."""
    steps = _required_migration_steps(payload, version_field="coding_schema_version")
    migrated = deepcopy(payload)
    migrated["codings"] = _migrate_codings(migrated.get("codings") or [], steps)
    migrated["coding_schema_version"] = CODING_SCHEMA_VERSION
    return migrated


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_store(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or not isinstance(payload.get("codings"), list):
        raise ValueError(f"{path} must contain a JSON object with a codings list")
    return payload


def _validate_current_store(payload: dict) -> None:
    from models import CodingEntry

    if payload.get("schema_version") != CODING_SCHEMA_VERSION:
        raise ValueError(f"Expected schema_version {CODING_SCHEMA_VERSION}")
    codings = payload.get("codings")
    if not isinstance(codings, list):
        raise ValueError("codings must be a list")
    for index, coding in enumerate(codings):
        if not isinstance(coding, dict):
            raise ValueError(f"Coding at index {index} is not an object")
        if coding_payload_uses_legacy_schema(coding):
            raise ValueError(f"Coding at index {index} still contains legacy fields")
        CodingEntry.model_validate(coding)


# Kept as a compatibility alias for tests and any local tooling written for the
# first migration release. It now validates the current schema version.
_validate_version_two_store = _validate_current_store


def _write_json_temp(destination: Path, payload: dict) -> Path:
    with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=destination.parent) as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        return Path(handle.name)


def _write_json_atomic(destination: Path, payload: dict) -> None:
    temp_path = _write_json_temp(destination, payload)
    try:
        os.replace(temp_path, destination)
    finally:
        temp_path.unlink(missing_ok=True)


def _v1_content_counts(codings: list[dict]) -> dict[str, int]:
    counts = {
        "values_with_content": 0,
        "comments_with_content": 0,
        "legacy_span_paths": 0,
        "legacy_spans": 0,
    }
    for coding in codings:
        differentiation = coding.get("differentiation")
        if isinstance(differentiation, dict):
            for field_name in (OLD_WHY, OLD_UNITARY):
                if differentiation.get(field_name):
                    counts["values_with_content"] += 1
                if differentiation.get(f"{field_name}_comment"):
                    counts["comments_with_content"] += 1
            for perspective in differentiation.get("perspectives_extract") or []:
                if not isinstance(perspective, dict):
                    continue
                if perspective.get(OLD_COMPLEXITY):
                    counts["values_with_content"] += 1
                if perspective.get(f"{OLD_COMPLEXITY}_comment"):
                    counts["comments_with_content"] += 1
        field_spans = coding.get("field_spans")
        if isinstance(field_spans, dict):
            for key, spans in field_spans.items():
                if not any(field_name in str(key) for field_name in _LEGACY_FIELD_NAMES):
                    continue
                counts["legacy_span_paths"] += 1
                if isinstance(spans, list):
                    counts["legacy_spans"] += len(spans)
    return counts


def _v2_content_counts(codings: list[dict]) -> dict[str, int]:
    counts = {
        "values_with_content": 0,
        "comments_with_content": 0,
        "legacy_span_paths": 0,
        "legacy_spans": 0,
        "parent_conditions_created": 0,
    }
    for coding in codings:
        nuance = coding.get("nuance")
        field_spans = coding.get("field_spans")
        if isinstance(nuance, dict):
            for field_name in (OLD_CERTAINTY, OLD_EPISTEMIC_STANCE, OLD_PARENT_CONDITION):
                if _has_text(nuance.get(field_name)):
                    counts["values_with_content"] += 1
                if _has_text(nuance.get(f"{field_name}_comment")):
                    counts["comments_with_content"] += 1
            if (
                _has_text(nuance.get(OLD_PARENT_CONDITION))
                or _has_text(nuance.get(f"{OLD_PARENT_CONDITION}_comment"))
                or _has_span_data(field_spans, f"nuance.{OLD_PARENT_CONDITION}")
                or _has_span_data(field_spans, f"nuance.{OLD_PARENT_CONDITION}_comment")
            ):
                counts["parent_conditions_created"] += 1
        if isinstance(field_spans, dict):
            for key, spans in field_spans.items():
                if str(key) not in _V2_LEGACY_SPAN_PATHS:
                    continue
                counts["legacy_span_paths"] += 1
                if isinstance(spans, list):
                    counts["legacy_spans"] += len(spans)
    return counts


def _combined_content_counts(step_counts: dict[str, dict[str, int]]) -> dict[str, int]:
    keys = {
        key
        for counts in step_counts.values()
        for key in counts
    }
    return {
        key: sum(counts.get(key, 0) for counts in step_counts.values())
        for key in sorted(keys)
    }


def _span_multiset(codings: list) -> list[str]:
    spans: list[str] = []
    for coding in codings:
        if not isinstance(coding, dict):
            continue
        field_spans = coding.get("field_spans")
        if not isinstance(field_spans, dict):
            continue
        for value in field_spans.values():
            if not isinstance(value, list):
                raise ValueError("Every field span path must contain a list")
            spans.extend(json.dumps(span, sort_keys=True, ensure_ascii=False) for span in value)
    return sorted(spans)


def _validate_lossless_transform(source: dict, migrated: dict) -> None:
    source_codings = source.get("codings") or []
    migrated_codings = migrated.get("codings") or []
    if len(source_codings) != len(migrated_codings):
        raise ValueError("Coding count changed during migration")
    source_ids = [coding.get("coding_id") if isinstance(coding, dict) else None for coding in source_codings]
    migrated_ids = [coding.get("coding_id") if isinstance(coding, dict) else None for coding in migrated_codings]
    if source_ids != migrated_ids:
        raise ValueError("Coding IDs or ordering changed during migration")
    source_store_extras = {key: value for key, value in source.items() if key not in {"schema_version", "codings"}}
    migrated_store_extras = {key: value for key, value in migrated.items() if key not in {"schema_version", "codings"}}
    if source_store_extras != migrated_store_extras:
        raise ValueError("Unrelated store metadata changed during migration")
    if _span_multiset(source_codings) != _span_multiset(migrated_codings):
        raise ValueError("A transcript span was added, removed, or changed during migration")

    context_names = (
        "context_why_is_this_thing_being_considered_or_talked_about_extract",
        "context_why_is_this_thing_being_considered_or_talked_about_extract_comment",
    )
    for source_coding, migrated_coding in zip(source_codings, migrated_codings):
        if not isinstance(source_coding, dict) or not isinstance(migrated_coding, dict):
            continue
        source_diff = source_coding.get("differentiation")
        migrated_diff = migrated_coding.get("differentiation")
        if isinstance(source_diff, dict):
            if not isinstance(migrated_diff, dict):
                raise ValueError("Differentiation data disappeared during migration")
            for name in context_names:
                if source_diff.get(name) != migrated_diff.get(name):
                    raise ValueError("Differentiation context changed during migration")
        source_nuance = source_coding.get("nuance")
        migrated_nuance = migrated_coding.get("nuance")
        if isinstance(source_nuance, dict):
            if not isinstance(migrated_nuance, dict):
                raise ValueError("Nuance data disappeared during migration")
            existing = source_nuance.get(CONDITION_LIST)
            if isinstance(existing, list):
                migrated_conditions = migrated_nuance.get(CONDITION_LIST)
                if not isinstance(migrated_conditions, list) or migrated_conditions[: len(existing)] != existing:
                    raise ValueError("Existing nested conditions changed during migration")


def _atomic_restore(backup_path: Path, destination: Path) -> None:
    with backup_path.open("rb") as source, NamedTemporaryFile("wb", delete=False, dir=destination.parent) as handle:
        shutil.copyfileobj(source, handle)
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)
    os.replace(temp_path, destination)


def _backup_directory(backup_root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    target = backup_root / stamp
    if target.exists():
        target = backup_root / f"{stamp}-{uuid.uuid4().hex[:8]}"
    target.mkdir(parents=True, exist_ok=False)
    return target


def _acquire_lock(lock_path: Path, *, timeout_seconds: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            lock_path.mkdir(parents=False, exist_ok=False)
            (lock_path / "owner.json").write_text(
                json.dumps({"pid": os.getpid(), "created_at": datetime.now(timezone.utc).isoformat()}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            return
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Could not acquire migration lock: {lock_path}")
            time.sleep(0.1)


def ensure_current_coding_schema(
    *,
    analyses_path: Path,
    codings_path: Path,
    backup_root: Path,
) -> MigrationResult:
    """Back up and atomically migrate the live coding store to the current schema."""
    if not codings_path.exists():
        return MigrationResult(status="no_store")

    initial = _load_store(codings_path)
    try:
        initial_steps = _required_migration_steps(initial, version_field="schema_version")
    except ValueError as exc:
        raise MigrationStartupError(
            str(exc),
            phase="schema_detection",
            analyses_path=analyses_path,
            codings_path=codings_path,
        ) from exc
    if not initial_steps:
        try:
            _validate_current_store(initial)
        except Exception as exc:
            raise MigrationStartupError(
                str(exc),
                phase="current_schema_validation",
                analyses_path=analyses_path,
                codings_path=codings_path,
            ) from exc
        return MigrationResult(status="current")

    lock_path = codings_path.parent / ".schema_migration.lock"
    backup_dir: Path | None = None
    backup_verified = False
    phase = "migration_lock"
    replaced = False
    restored = False
    lock_acquired = False
    temp_path: Path | None = None
    try:
        _acquire_lock(lock_path)
        lock_acquired = True
        phase = "schema_recheck"
        source_payload = _load_store(codings_path)
        source_steps = _required_migration_steps(source_payload, version_field="schema_version")
        if not source_steps:
            _validate_current_store(source_payload)
            return MigrationResult(status="current_after_wait")
        if not analyses_path.exists():
            raise FileNotFoundError(f"Required analysis store is missing: {analyses_path}")

        phase = "backup_creation"
        backup_dir = _backup_directory(backup_root)
        analyses_backup = backup_dir / analyses_path.name
        codings_backup = backup_dir / codings_path.name
        source_hashes_before = {
            analyses_path.name: _sha256(analyses_path),
            codings_path.name: _sha256(codings_path),
        }
        shutil.copy2(analyses_path, analyses_backup)
        shutil.copy2(codings_path, codings_backup)

        phase = "backup_verification"
        hashes = {
            analyses_path.name: {"source": _sha256(analyses_path), "backup": _sha256(analyses_backup)},
            codings_path.name: {"source": _sha256(codings_path), "backup": _sha256(codings_backup)},
        }
        if any(values["source"] != values["backup"] for values in hashes.values()):
            raise ValueError("A backup checksum does not match its source file")
        if any(hashes[name]["source"] != source_hashes_before[name] for name in source_hashes_before):
            raise ValueError("A live data file changed while the backup was being created")
        json.loads(analyses_backup.read_text(encoding="utf-8"))
        source_payload = _load_store(codings_backup)
        backup_verified = True

        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "backup_verified",
            "source_files": [str(analyses_path), str(codings_path)],
            "source_schema_version": source_payload.get("schema_version"),
            "target_schema_version": CODING_SCHEMA_VERSION,
            "applied_steps": list(source_steps),
            "coding_count": len(source_payload["codings"]),
            "affected_coding_indices": [],
            "affected_coding_ids": [],
            "legacy_coding_indices": [],
            "legacy_coding_ids": [],
            "migration_counts": {},
            "step_migration_counts": {},
            "sha256": hashes,
        }
        _write_json_atomic(backup_dir / "migration_manifest.json", manifest)

        phase = "migration_build"
        source_codings = source_payload["codings"]
        working_codings = deepcopy(source_codings)
        step_counts: dict[str, dict[str, int]] = {}
        if SCHEMA_V1_TO_V2 in source_steps:
            step_counts[SCHEMA_V1_TO_V2] = _v1_content_counts(
                [coding for coding in working_codings if isinstance(coding, dict)]
            )
            working_codings = _migrate_codings(working_codings, (SCHEMA_V1_TO_V2,))
        if SCHEMA_V2_TO_V3 in source_steps:
            step_counts[SCHEMA_V2_TO_V3] = _v2_content_counts(
                [coding for coding in working_codings if isinstance(coding, dict)]
            )
            working_codings = _migrate_codings(working_codings, (SCHEMA_V2_TO_V3,))
        migrated_codings = working_codings
        affected_indices = [
            index
            for index, (source, migrated) in enumerate(zip(source_codings, migrated_codings))
            if source != migrated
        ]
        affected_ids = [
            source_codings[index].get("coding_id")
            for index in affected_indices
            if isinstance(source_codings[index], dict)
        ]
        manifest["affected_coding_indices"] = affected_indices
        manifest["affected_coding_ids"] = affected_ids
        # Compatibility keys keep the original migration-review release able
        # to list backups made by this release.
        manifest["legacy_coding_indices"] = affected_indices
        manifest["legacy_coding_ids"] = affected_ids
        manifest["migration_counts"] = _combined_content_counts(step_counts)
        manifest["step_migration_counts"] = step_counts
        _write_json_atomic(backup_dir / "migration_manifest.json", manifest)

        migrated_payload = {
            key: deepcopy(value)
            for key, value in source_payload.items()
            if key not in {"schema_version", "codings"}
        }
        migrated_payload["schema_version"] = CODING_SCHEMA_VERSION
        migrated_payload["codings"] = migrated_codings

        _validate_lossless_transform(source_payload, migrated_payload)
        _validate_current_store(migrated_payload)
        if migrated_payload != {
            **{key: deepcopy(value) for key, value in migrated_payload.items() if key != "codings"},
            "codings": [migrate_coding_entry_payload(coding) for coding in migrated_codings],
        }:
            raise ValueError("Migration is not idempotent")

        phase = "temporary_file_validation"
        temp_path = _write_json_temp(codings_path, migrated_payload)
        _validate_current_store(_load_store(temp_path))

        phase = "atomic_replace"
        if _sha256(analyses_path) != hashes[analyses_path.name]["source"]:
            raise ValueError("analyses.json changed after backup; refusing to replace codings.json")
        if _sha256(codings_path) != hashes[codings_path.name]["source"]:
            raise ValueError("codings.json changed after backup; refusing to replace it")
        os.replace(temp_path, codings_path)
        temp_path = None
        replaced = True

        phase = "post_replace_validation"
        _validate_current_store(_load_store(codings_path))
        manifest["status"] = "completed"
        manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
        manifest["post_migration_codings_sha256"] = _sha256(codings_path)
        _write_json_atomic(backup_dir / "migration_manifest.json", manifest)
        return MigrationResult(
            status="migrated",
            migrated_codings=len(affected_indices),
            backup_dir=backup_dir,
            applied_steps=source_steps,
        )
    except MigrationStartupError:
        raise
    except Exception as exc:
        if replaced and backup_dir is not None:
            try:
                _atomic_restore(backup_dir / codings_path.name, codings_path)
                if _sha256(codings_path) != _sha256(backup_dir / codings_path.name):
                    raise ValueError("Restored coding store does not match the verified backup")
                restored = True
            except Exception as restore_exc:
                raise MigrationStartupError(
                    f"Migration failed ({exc}); automatic restore also failed ({restore_exc})",
                    phase=f"{phase}/restore",
                    analyses_path=analyses_path,
                    codings_path=codings_path,
                    backup_dir=backup_dir,
                    backup_verified=backup_verified,
                    originals_state="restore_failed",
                ) from restore_exc
        raise MigrationStartupError(
            str(exc),
            phase=phase,
            analyses_path=analyses_path,
            codings_path=codings_path,
            backup_dir=backup_dir,
            backup_verified=backup_verified,
            originals_state="restored" if restored else "untouched",
        ) from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        if lock_acquired and lock_path.exists():
            shutil.rmtree(lock_path, ignore_errors=True)


def format_migration_failure(exc: BaseException) -> str:
    if isinstance(exc, MigrationStartupError):
        phase = exc.phase
        analyses_path = exc.analyses_path
        codings_path = exc.codings_path
        backup_dir = exc.backup_dir
        backup_verified = exc.backup_verified
        originals_state = exc.originals_state
    else:
        phase = "unexpected_startup_error"
        analyses_path = Path("unknown")
        codings_path = Path("unknown")
        backup_dir = None
        backup_verified = False
        originals_state = "unknown"
    state_explanation = {
        "untouched": "The live files were not replaced.",
        "restored": "The live codings file was restored from the verified backup.",
        "restore_failed": "Automatic restoration failed; do not edit or restart before Arthur reviews the files.",
        "unknown": "The live-file state could not be determined automatically.",
    }.get(originals_state, f"Live-file state: {originals_state}.")
    if backup_dir is None:
        backup_explanation = "No backup folder was created."
    elif backup_verified:
        backup_explanation = f"Verified backup folder: {backup_dir}."
    else:
        backup_explanation = f"An incomplete or unverified backup folder exists at {backup_dir}; do not rely on it."
    return "\n".join(
        [
            "SRT Coder could not safely complete the analysis schema migration, so the server was not started.",
            state_explanation,
            backup_explanation,
            "",
            "Technical details:",
            f"- phase: {phase}",
            f"- error: {type(exc).__name__}: {exc}",
            f"- analyses file: {analyses_path}",
            f"- codings file: {codings_path}",
            f"- supported target schema: {CODING_SCHEMA_VERSION}",
            f"- manifest: {(backup_dir / 'migration_manifest.json') if backup_dir else 'not created'}",
            "",
            "Please copy this entire message and send it to Arthur. He can use it to diagnose and fix the migration safely.",
        ]
    )


def run_startup_schema_migration() -> MigrationResult:
    from config import ANALYSES_JSON, CODED_DATA_DIR, CODINGS_JSON, RUNTIME_DIR

    try:
        result = ensure_current_coding_schema(
            analyses_path=ANALYSES_JSON,
            codings_path=CODINGS_JSON,
            backup_root=CODED_DATA_DIR / "old_schema_analyses",
        )
        (RUNTIME_DIR / "migration_error.txt").unlink(missing_ok=True)
        return result
    except Exception as exc:
        if not isinstance(exc, MigrationStartupError):
            exc = MigrationStartupError(
                str(exc),
                phase="initial_schema_read",
                analyses_path=ANALYSES_JSON,
                codings_path=CODINGS_JSON,
            )
        message = format_migration_failure(exc)
        print(message, file=sys.stderr, flush=True)
        try:
            RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
            (RUNTIME_DIR / "migration_error.txt").write_text(message + "\n", encoding="utf-8")
        except Exception:
            pass
        raise
