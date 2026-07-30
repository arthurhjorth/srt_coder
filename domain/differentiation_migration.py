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


CODING_SCHEMA_VERSION = 2

OLD_WHY = "why_is_this_a_thing_or_how_did_it_happen_extract"
TARGET_WHY = "why_is_it_important_extract"
OLD_UNITARY = "what_is_wrong_with_taking_a_unitary_perspective_extract"
TARGET_PERSPECTIVES = "why_is_it_important_to_take_different_perspectives_extract"
OLD_COMPLEXITY = (
    "how_does_this_particular_perspective_add_complexity_or_difficulty_to_the_thing_being_considered_extract"
)
TARGET_IMPLICATIONS = "what_are_the_implications_extract"

_LEGACY_FIELD_NAMES = {OLD_WHY, OLD_UNITARY, OLD_COMPLEXITY}
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
    target_text = target.strip() if isinstance(target, str) else target
    legacy_text = legacy.strip() if isinstance(legacy, str) else legacy
    if target_text and legacy_text:
        return f"{target_text}\n{legacy_text}"
    if legacy_text:
        return legacy_text
    return target


def _merge_field(payload: dict, old_name: str, target_name: str) -> None:
    if old_name not in payload:
        return
    legacy_value = payload.pop(old_name)
    if target_name in payload:
        payload[target_name] = _merge_text(payload.get(target_name), legacy_value)
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


def migrate_coding_entry_payload(payload: dict) -> dict:
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


def coding_payload_uses_legacy_schema(payload: dict) -> bool:
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


def migrate_export_payload(payload: dict) -> dict:
    """Migrate an import/agreement bundle in memory; never alter its source file."""
    version = payload.get("coding_schema_version")
    if version is not None and (isinstance(version, bool) or not isinstance(version, int)):
        raise ValueError("coding_schema_version must be an integer")
    if isinstance(version, int) and version > CODING_SCHEMA_VERSION:
        raise ValueError(f"Unsupported future coding schema version: {version}")
    migrated = deepcopy(payload)
    codings = migrated.get("codings")
    if isinstance(codings, list):
        migrated["codings"] = [
            migrate_coding_entry_payload(coding) if isinstance(coding, dict) else coding
            for coding in codings
        ]
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


def _validate_version_two_store(payload: dict) -> None:
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


def _legacy_content_counts(codings: list[dict]) -> dict[str, int]:
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
    """Back up and migrate the live coding store if legacy keys are present."""
    if not codings_path.exists():
        return MigrationResult(status="no_store")

    initial = _load_store(codings_path)
    version = initial.get("schema_version")
    if version is not None and (isinstance(version, bool) or not isinstance(version, int)):
        raise MigrationStartupError(
            "schema_version must be an integer",
            phase="schema_detection",
            analyses_path=analyses_path,
            codings_path=codings_path,
        )
    if isinstance(version, int) and version > CODING_SCHEMA_VERSION:
        raise MigrationStartupError(
            f"Unsupported future coding schema version: {version}",
            phase="schema_detection",
            analyses_path=analyses_path,
            codings_path=codings_path,
        )
    needs_migration = any(
        isinstance(coding, dict) and coding_payload_uses_legacy_schema(coding)
        for coding in initial["codings"]
    )
    if not needs_migration:
        return MigrationResult(status="current" if version == CODING_SCHEMA_VERSION else "current_unversioned")

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
        if not any(
            isinstance(coding, dict) and coding_payload_uses_legacy_schema(coding)
            for coding in source_payload["codings"]
        ):
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

        legacy_indices = [
            index
            for index, coding in enumerate(source_payload["codings"])
            if isinstance(coding, dict) and coding_payload_uses_legacy_schema(coding)
        ]
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "backup_verified",
            "source_files": [str(analyses_path), str(codings_path)],
            "target_schema_version": CODING_SCHEMA_VERSION,
            "coding_count": len(source_payload["codings"]),
            "legacy_coding_indices": legacy_indices,
            "legacy_coding_ids": [
                source_payload["codings"][index].get("coding_id")
                for index in legacy_indices
                if isinstance(source_payload["codings"][index], dict)
            ],
            "migration_counts": _legacy_content_counts(
                [coding for coding in source_payload["codings"] if isinstance(coding, dict)]
            ),
            "sha256": hashes,
        }
        _write_json_atomic(backup_dir / "migration_manifest.json", manifest)

        phase = "migration_build"
        migrated_codings = [
            migrate_coding_entry_payload(coding) if isinstance(coding, dict) else coding
            for coding in source_payload["codings"]
        ]
        migrated_payload = {
            key: deepcopy(value)
            for key, value in source_payload.items()
            if key not in {"schema_version", "codings"}
        }
        migrated_payload["schema_version"] = CODING_SCHEMA_VERSION
        migrated_payload["codings"] = migrated_codings

        if [coding.get("coding_id") for coding in migrated_codings if isinstance(coding, dict)] != [
            coding.get("coding_id") for coding in source_payload["codings"] if isinstance(coding, dict)
        ]:
            raise ValueError("Coding IDs or ordering changed during migration")
        _validate_version_two_store(migrated_payload)
        if migrated_payload != {
            **{key: deepcopy(value) for key, value in migrated_payload.items() if key != "codings"},
            "codings": [migrate_coding_entry_payload(coding) for coding in migrated_codings],
        }:
            raise ValueError("Migration is not idempotent")

        phase = "temporary_file_validation"
        temp_path = _write_json_temp(codings_path, migrated_payload)
        _validate_version_two_store(_load_store(temp_path))

        phase = "atomic_replace"
        if _sha256(analyses_path) != hashes[analyses_path.name]["source"]:
            raise ValueError("analyses.json changed after backup; refusing to replace codings.json")
        if _sha256(codings_path) != hashes[codings_path.name]["source"]:
            raise ValueError("codings.json changed after backup; refusing to replace it")
        os.replace(temp_path, codings_path)
        temp_path = None
        replaced = True

        phase = "post_replace_validation"
        _validate_version_two_store(_load_store(codings_path))
        manifest["status"] = "completed"
        manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
        manifest["post_migration_codings_sha256"] = _sha256(codings_path)
        _write_json_atomic(backup_dir / "migration_manifest.json", manifest)
        return MigrationResult(
            status="migrated",
            migrated_codings=len(legacy_indices),
            backup_dir=backup_dir,
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
