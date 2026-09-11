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
from tempfile import NamedTemporaryFile
import time
import uuid
from typing import Any

from coding_books.simplified_v4.models import SimplifiedCodingEntry as V4CodingEntry
from coding_books.simplified_v5.models import SimplifiedCodingEntry as V5CodingEntry
from storage.simplified_coding_repo_v5 import STORE_FORMAT_VERSION, validate_store


SOURCE_CODING_BOOK_VERSION = 4
TARGET_CODING_BOOK_VERSION = 5
MIGRATION_STEP = "simplified_v4_to_v5"
PERSPECTIVE_PATH_RE = re.compile(r"^differentiation\.perspectives\[(\d+)\]$")


@dataclass(frozen=True)
class MigrationResult:
    status: str
    migrated_codings: int = 0
    backup_dir: Path | None = None
    source_path: Path | None = None
    target_path: Path | None = None


class SimplifiedMigrationError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        phase: str,
        source_path: Path | None = None,
        target_path: Path | None = None,
        backup_dir: Path | None = None,
        backup_verified: bool = False,
        target_state: str = "unchanged",
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.source_path = source_path
        self.target_path = target_path
        self.backup_dir = backup_dir
        self.backup_verified = backup_verified
        self.target_state = target_state


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)
    os.replace(temp_path, path)


def _write_json_temp(destination: Path, payload: dict[str, Any]) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=destination.parent) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        return Path(handle.name)


def _span_count(entry: dict[str, Any]) -> int:
    field_spans = entry.get("field_spans") or {}
    active = sum(len(spans or []) for spans in field_spans.values() if isinstance(spans, list))
    metadata = entry.get("migration_metadata") or {}
    legacy = metadata.get("legacy_field_spans") or {}
    return active + sum(len(spans or []) for spans in legacy.values() if isinstance(spans, list))


def _content_count(value: Any, *, key: str = "") -> int:
    if isinstance(value, dict):
        return sum(_content_count(item, key=str(name)) for name, item in value.items())
    if isinstance(value, list):
        return sum(_content_count(item, key=key) for item in value)
    if isinstance(value, str) and value.strip() and key not in {
        "coding_id",
        "analysis_id",
        "interview_file",
        "created_by",
        "created_at",
        "updated_at",
        "selected_text",
    }:
        return 1
    return 0


def _store_counts(payload: dict[str, Any]) -> dict[str, int]:
    entries = [item for item in (payload.get("codings") or []) if isinstance(item, dict)]
    span_comments = 0
    for entry in entries:
        span_groups = list((entry.get("field_spans") or {}).values())
        span_groups.extend(
            ((entry.get("migration_metadata") or {}).get("legacy_field_spans") or {}).values()
        )
        span_comments += sum(
            1
            for spans in span_groups
            for span in (spans or [])
            if isinstance(span, dict) and str(span.get("comment") or "").strip()
        )
    return {
        "coding_objects": len(entries),
        "populated_coding_values": sum(
            _content_count(item.get("coding") or {}) for item in entries
        ),
        "transcript_spans_including_audit_metadata": sum(_span_count(item) for item in entries),
        "populated_span_comments": span_comments,
    }


def _comments_for(code_type: str) -> tuple[str, ...]:
    if code_type == "nuance":
        return (
            "relation_type_comment",
            "expressed_certainty_comment",
        )
    return ()


def migrate_v4_entry_payload(raw_entry: dict[str, Any]) -> dict[str, Any]:
    """Pure, deterministic v4-entry to v5-entry transformation."""
    source = V4CodingEntry.model_validate(raw_entry).model_dump(mode="json")
    migrated = deepcopy(source)
    migrated["coding_book_version"] = TARGET_CODING_BOOK_VERSION
    coding = migrated["coding"]
    code_type = coding["code_type"]
    fields = coding["fields"]
    for comment_name in _comments_for(code_type):
        fields.setdefault(comment_name, None)

    field_spans = migrated.get("field_spans") or {}
    migrated_spans: dict[str, Any] = {}
    legacy_spans: dict[str, Any] = {}
    for path, spans in field_spans.items():
        if path.startswith("differentiation.perspective_types"):
            legacy_spans[path] = deepcopy(spans)
            continue
        match = PERSPECTIVE_PATH_RE.match(path)
        target_path = (
            f"differentiation.perspectives[{match.group(1)}].text" if match else path
        )
        migrated_spans.setdefault(target_path, []).extend(deepcopy(spans))
    migrated["field_spans"] = migrated_spans

    legacy_types: list[str] = []
    if code_type == "differentiation":
        old_perspectives = list(fields.pop("perspectives", []) or [])
        legacy_types = list(fields.pop("perspective_types", []) or [])
        if legacy_types and not old_perspectives:
            old_perspectives = [None]
        fields["perspectives"] = [
            {
                "text": text,
                "perspective_types": deepcopy(legacy_types),
                "perspective_types_comment": None,
            }
            for text in old_perspectives
        ]

    migrated["migration_metadata"] = (
        {
            "source_coding_book_version": SOURCE_CODING_BOOK_VERSION,
            "legacy_differentiation_perspective_types": deepcopy(legacy_types),
            "legacy_field_spans": legacy_spans,
        }
        if legacy_types or legacy_spans
        else None
    )
    if code_type == "nuance" and fields.get("relation_type") == "ambition_intention":
        fields["relation_type"] = "expected_effect"
    return V5CodingEntry.model_validate(migrated).model_dump(mode="json")


def migrate_store_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("The simplified coding store must be a JSON object")
    version = payload.get("coding_book_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError("The simplified coding store has no valid coding_book_version")
    if version > TARGET_CODING_BOOK_VERSION:
        raise ValueError(f"Unsupported future coding book version: {version}")
    if version < SOURCE_CODING_BOOK_VERSION:
        raise ValueError("Only simplified coding book v4 can be migrated to v5")
    if payload.get("storage_format_version") != STORE_FORMAT_VERSION:
        raise ValueError("Unsupported simplified coding-store format")
    codings = payload.get("codings")
    if not isinstance(codings, list):
        raise ValueError("The simplified coding store must contain a codings list")

    if version == TARGET_CODING_BOOK_VERSION:
        migrated = deepcopy(payload)
        migrated["codings"] = [
            V5CodingEntry.model_validate(entry).model_dump(mode="json")
            for entry in codings
        ]
        validate_store(migrated)
        return migrated

    migrated = {
        key: deepcopy(value)
        for key, value in payload.items()
        if key not in {"coding_book_version", "codings"}
    }
    migrated["coding_book_version"] = TARGET_CODING_BOOK_VERSION
    migrated_entries: list[dict[str, Any]] = []
    for entry in codings:
        if not isinstance(entry, dict):
            raise ValueError("Every coding must be a JSON object")
        migrated_entries.append(migrate_v4_entry_payload(entry))
    migrated["codings"] = migrated_entries
    validate_store(migrated)
    [V5CodingEntry.model_validate(entry) for entry in migrated_entries]
    return migrated


def migrate_export_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Import payload must be a JSON object")
    version = payload.get("coding_book_version")
    if version == TARGET_CODING_BOOK_VERSION:
        result = deepcopy(payload)
        result["codings"] = [
            V5CodingEntry.model_validate(entry).model_dump(mode="json")
            for entry in (result.get("codings") or [])
        ]
        return result
    if version != SOURCE_CODING_BOOK_VERSION:
        raise ValueError("Only simplified coding book v4 or v5 exports are supported")
    result = deepcopy(payload)
    result["coding_book_version"] = TARGET_CODING_BOOK_VERSION
    result["codings"] = [
        migrate_v4_entry_payload(entry) for entry in (result.get("codings") or [])
    ]
    return result


def _validate_lossless_transform(
    source: dict[str, Any], migrated: dict[str, Any]
) -> None:
    source_entries = source.get("codings") or []
    migrated_entries = migrated.get("codings") or []
    if len(source_entries) != len(migrated_entries):
        raise ValueError("A coding object was added or removed during migration")
    identity_keys = (
        "coding_id",
        "analysis_id",
        "interview_file",
        "created_by",
        "created_at",
        "updated_at",
    )
    for old, new in zip(source_entries, migrated_entries):
        for key in identity_keys:
            if old.get(key) != new.get(key):
                raise ValueError(f"Coding identity field {key} changed during migration")
        if (old.get("coding") or {}).get("code_type") != (new.get("coding") or {}).get(
            "code_type"
        ):
            raise ValueError("A coding object changed type during migration")
        if _span_count(old) != _span_count(new):
            raise ValueError("A transcript span was added or removed during migration")


def _migration_counts(
    source: dict[str, Any], migrated: dict[str, Any]
) -> tuple[list[str], dict[str, int]]:
    affected: list[str] = []
    counts = {
        "affected_codings": 0,
        "perspectives_transformed": 0,
        "perspective_type_assignments": 0,
        "perspective_placeholders_created": 0,
        "ambition_objects_recoded": 0,
        "span_paths_rekeyed": 0,
        "legacy_span_paths_preserved": 0,
    }
    for old, new in zip(source.get("codings") or [], migrated.get("codings") or []):
        if old == new:
            continue
        counts["affected_codings"] += 1
        affected.append(str(old.get("coding_id") or ""))
        old_coding = old.get("coding") or {}
        old_fields = old_coding.get("fields") or {}
        if old_coding.get("code_type") == "differentiation":
            old_rows = list(old_fields.get("perspectives") or [])
            old_types = list(old_fields.get("perspective_types") or [])
            counts["perspectives_transformed"] += len(old_rows)
            assignment_rows = len(old_rows) or (1 if old_types else 0)
            counts["perspective_type_assignments"] += assignment_rows * len(old_types)
            if old_types and not old_rows:
                counts["perspective_placeholders_created"] += 1
        if (
            old_coding.get("code_type") == "nuance"
            and old_fields.get("relation_type") == "ambition_intention"
        ):
            counts["ambition_objects_recoded"] += 1
        for path in (old.get("field_spans") or {}):
            if PERSPECTIVE_PATH_RE.match(path):
                counts["span_paths_rekeyed"] += 1
            if path.startswith("differentiation.perspective_types"):
                counts["legacy_span_paths_preserved"] += 1
    return affected, counts


def _backup_directory(backup_root: Path) -> Path:
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    target = backup_root / stamp
    if target.exists():
        target = backup_root / f"{stamp}-{uuid.uuid4().hex[:8]}"
    target.mkdir()
    return target


def _acquire_lock(lock_path: Path, *, timeout_seconds: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            lock_path.mkdir(parents=False, exist_ok=False)
            _write_json_atomic(
                lock_path / "owner.json",
                {"pid": os.getpid(), "created_at": datetime.now(timezone.utc).isoformat()},
            )
            return
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Could not acquire migration lock: {lock_path}")
            time.sleep(0.1)


def _validate_current_store(payload: dict[str, Any]) -> None:
    raw_entries = validate_store(payload)
    entries = [V5CodingEntry.model_validate(entry) for entry in raw_entries]
    ids = [entry.coding_id for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("The simplified coding store contains duplicate coding ids")


def ensure_current_simplified_schema(
    *,
    analyses_path: Path,
    v4_path: Path,
    target_path: Path,
    backup_root: Path,
) -> MigrationResult:
    """Publish a validated v5 store only after an exact, verified backup exists."""
    source_path = target_path if target_path.exists() else v4_path
    if not source_path.exists():
        return MigrationResult(status="no_store", target_path=target_path)
    try:
        initial = _read_json(source_path)
    except Exception as exc:
        raise SimplifiedMigrationError(
            f"The coding store is not valid JSON: {exc}",
            phase="schema_detection",
            source_path=source_path,
            target_path=target_path,
        ) from exc
    version = initial.get("coding_book_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise SimplifiedMigrationError(
            "The coding store has no valid coding_book_version",
            phase="schema_detection",
            source_path=source_path,
            target_path=target_path,
        )
    if version > TARGET_CODING_BOOK_VERSION:
        raise SimplifiedMigrationError(
            f"Unsupported future coding book version: {version}",
            phase="schema_detection",
            source_path=source_path,
            target_path=target_path,
        )
    if source_path == target_path:
        if version != TARGET_CODING_BOOK_VERSION:
            raise SimplifiedMigrationError(
                "The neutral simplified store has an inconsistent coding-book version",
                phase="schema_detection",
                source_path=source_path,
                target_path=target_path,
            )
        try:
            _validate_current_store(initial)
            return MigrationResult(status="current", source_path=source_path, target_path=target_path)
        except Exception as exc:
            raise SimplifiedMigrationError(
                f"The v5 neutral coding store is invalid: {exc}",
                phase="current_schema_validation",
                source_path=source_path,
                target_path=target_path,
            ) from exc
    if version != SOURCE_CODING_BOOK_VERSION:
        raise SimplifiedMigrationError(
            f"The v4 source store has inconsistent version marker {version}",
            phase="schema_detection",
            source_path=source_path,
            target_path=target_path,
        )

    lock_path = target_path.parent / ".simplified_schema_migration.lock"
    backup_dir: Path | None = None
    backup_verified = False
    lock_acquired = False
    temp_path: Path | None = None
    target_replaced = False
    target_existed = target_path.exists()
    phase = "migration_lock"
    try:
        _acquire_lock(lock_path)
        lock_acquired = True
        source_path = target_path if target_path.exists() else v4_path
        source_payload = _read_json(source_path)
        if source_path == target_path:
            try:
                _validate_current_store(source_payload)
                return MigrationResult(
                    status="current_after_wait",
                    source_path=source_path,
                    target_path=target_path,
                )
            except Exception as exc:
                raise ValueError(
                    f"A conflicting invalid neutral store appeared while waiting: {exc}"
                ) from exc
        if not analyses_path.exists():
            raise FileNotFoundError(f"Required analysis store is missing: {analyses_path}")

        phase = "backup_creation"
        backup_dir = _backup_directory(backup_root)
        analyses_backup = backup_dir / analyses_path.name
        source_backup = backup_dir / source_path.name
        hashes_before = {
            analyses_path.name: _sha256(analyses_path),
            source_path.name: _sha256(source_path),
        }
        shutil.copy2(analyses_path, analyses_backup)
        shutil.copy2(source_path, source_backup)

        phase = "backup_verification"
        hashes = {
            analyses_path.name: {
                "source": _sha256(analyses_path),
                "backup": _sha256(analyses_backup),
            },
            source_path.name: {
                "source": _sha256(source_path),
                "backup": _sha256(source_backup),
            },
        }
        if any(item["source"] != item["backup"] for item in hashes.values()):
            raise ValueError("A backup checksum does not match its source file")
        if any(hashes[name]["source"] != digest for name, digest in hashes_before.items()):
            raise ValueError("A live data file changed while the backup was being created")
        _read_json(analyses_backup)
        source_payload = _read_json(source_backup)
        backup_verified = True

        manifest: dict[str, Any] = {
            "migration_family": "simplified_coding_book",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "backup_verified",
            "source_files": [str(analyses_path), str(source_path)],
            "source_coding_path": str(source_path),
            "target_coding_path": str(target_path),
            "source_coding_book_version": source_payload.get("coding_book_version"),
            "target_coding_book_version": TARGET_CODING_BOOK_VERSION,
            "applied_steps": [MIGRATION_STEP],
            "coding_count": len(source_payload.get("codings") or []),
            "affected_coding_ids": [],
            "migration_counts": {},
            "source_counts": _store_counts(source_payload),
            "sha256": hashes,
        }
        _write_json_atomic(backup_dir / "migration_manifest.json", manifest)

        phase = "migration_build"
        migrated_payload = migrate_store_payload(source_payload)
        _validate_lossless_transform(source_payload, migrated_payload)
        _validate_current_store(migrated_payload)
        if migrate_store_payload(migrated_payload) != migrated_payload:
            raise ValueError("Migration is not idempotent")
        affected_ids, counts = _migration_counts(source_payload, migrated_payload)
        manifest["affected_coding_ids"] = affected_ids
        manifest["migration_counts"] = counts
        manifest["target_counts"] = _store_counts(migrated_payload)
        _write_json_atomic(backup_dir / "migration_manifest.json", manifest)

        phase = "temporary_file_validation"
        temp_path = _write_json_temp(target_path, migrated_payload)
        _validate_current_store(_read_json(temp_path))

        phase = "atomic_publish"
        if _sha256(analyses_path) != hashes[analyses_path.name]["source"]:
            raise ValueError("analyses.json changed after backup; refusing to publish v5")
        if _sha256(source_path) != hashes[source_path.name]["source"]:
            raise ValueError("The source coding store changed after backup")
        if source_path != target_path and target_path.exists():
            raise ValueError("The v5 target appeared during migration; refusing to overwrite it")
        os.replace(temp_path, target_path)
        temp_path = None
        target_replaced = True

        phase = "post_publish_validation"
        _validate_current_store(_read_json(target_path))
        manifest["status"] = "completed"
        manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
        manifest["post_migration_codings_sha256"] = _sha256(target_path)
        _write_json_atomic(backup_dir / "migration_manifest.json", manifest)
        return MigrationResult(
            status="migrated",
            migrated_codings=len(affected_ids),
            backup_dir=backup_dir,
            source_path=source_path,
            target_path=target_path,
        )
    except SimplifiedMigrationError:
        raise
    except Exception as exc:
        target_state = "unchanged"
        if target_replaced:
            try:
                if target_existed and backup_dir is not None:
                    shutil.copy2(backup_dir / source_path.name, target_path)
                    if _sha256(target_path) != _sha256(backup_dir / source_path.name):
                        raise ValueError("Restored target does not match its verified backup")
                    target_state = "restored"
                elif target_path.exists():
                    target_path.unlink()
                    target_state = "removed_new_target"
            except Exception as restore_exc:
                raise SimplifiedMigrationError(
                    f"Migration failed ({exc}); target cleanup failed ({restore_exc})",
                    phase=f"{phase}/restore",
                    source_path=source_path,
                    target_path=target_path,
                    backup_dir=backup_dir,
                    backup_verified=backup_verified,
                    target_state="cleanup_failed",
                ) from restore_exc
        raise SimplifiedMigrationError(
            str(exc),
            phase=phase,
            source_path=source_path,
            target_path=target_path,
            backup_dir=backup_dir,
            backup_verified=backup_verified,
            target_state=target_state,
        ) from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        if lock_acquired:
            shutil.rmtree(lock_path, ignore_errors=True)


def format_startup_error(exc: SimplifiedMigrationError) -> str:
    me = exc
    backup = (
        f"Verified backup folder: {me.backup_dir}."
        if me.backup_verified and me.backup_dir
        else "No verified backup was completed."
    )
    return "\n".join(
        [
            "The server did not start because the simplified coding migration failed.",
            "No source coding data or analyses were intentionally modified.",
            backup,
            f"Phase: {me.phase}",
            f"Target state: {me.target_state}",
            f"Source: {me.source_path}",
            f"Target: {me.target_path}",
            f"Error: {me}",
        ]
    )


def run_startup_simplified_migration() -> MigrationResult:
    from config import (
        ANALYSES_JSON,
        CODED_DATA_DIR,
        CODINGS_V4_JSON,
        RUNTIME_DIR,
        SIMPLIFIED_CODINGS_JSON,
    )

    error_path = RUNTIME_DIR / "simplified_migration_error.txt"
    try:
        result = ensure_current_simplified_schema(
            analyses_path=ANALYSES_JSON,
            v4_path=CODINGS_V4_JSON,
            target_path=SIMPLIFIED_CODINGS_JSON,
            backup_root=CODED_DATA_DIR / "old_schema_analyses",
        )
        error_path.unlink(missing_ok=True)
        return result
    except SimplifiedMigrationError as exc:
        message = format_startup_error(exc)
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        error_path.write_text(message + "\n", encoding="utf-8")
        raise
