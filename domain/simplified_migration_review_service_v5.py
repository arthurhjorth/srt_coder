from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from domain.simplified_schema_migration import MIGRATION_STEP, migrate_store_payload


@dataclass(frozen=True)
class MigrationBackupSummary:
    directory: Path
    label: str
    manifest: dict[str, Any]
    is_v4_to_v5: bool


@dataclass(frozen=True)
class V5MigrationChange:
    coding_id: str
    object_type: str
    change_type: str
    before: Any
    expected_after: Any
    current_after: Any
    current_matches_expected: bool


@dataclass(frozen=True)
class V5MigrationReview:
    summary: MigrationBackupSummary
    changes: list[V5MigrationChange]
    live_checksum_matches: bool | None


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def list_simplified_migration_backups(root: Path) -> list[MigrationBackupSummary]:
    if not root.exists():
        return []
    summaries: list[MigrationBackupSummary] = []
    for manifest_path in root.glob("*/migration_manifest.json"):
        try:
            manifest = _read_object(manifest_path)
        except Exception:
            continue
        steps = manifest.get("applied_steps") or []
        is_v5 = (
            manifest.get("migration_family") == "simplified_coding_book"
            and MIGRATION_STEP in steps
        )
        if is_v5:
            version = (
                f"v{manifest.get('source_coding_book_version', '?')}→"
                f"v{manifest.get('target_coding_book_version', '?')}"
            )
        else:
            version = f"historical → v{manifest.get('target_schema_version', '?')}"
        label = f"{manifest_path.parent.name} · {version} · {manifest.get('status', 'unknown')}"
        summaries.append(
            MigrationBackupSummary(
                directory=manifest_path.parent,
                label=label,
                manifest=manifest,
                is_v4_to_v5=is_v5,
            )
        )
    return sorted(summaries, key=lambda item: item.directory.name, reverse=True)


def build_v5_migration_review(
    summary: MigrationBackupSummary, live_path: Path
) -> V5MigrationReview:
    if not summary.is_v4_to_v5:
        return V5MigrationReview(summary=summary, changes=[], live_checksum_matches=None)
    manifest = summary.manifest
    source_name = Path(str(manifest.get("source_coding_path") or "codings_v4.json")).name
    source_path = summary.directory / source_name
    if not source_path.exists():
        raise ValueError(f"The backed-up source coding file is missing: {source_name}")
    source = _read_object(source_path)
    expected = migrate_store_payload(source)
    current = _read_object(live_path) if live_path.exists() else {"codings": []}
    current_by_id = {
        str(item.get("coding_id")): item
        for item in current.get("codings") or []
        if isinstance(item, dict)
    }
    expected_by_id = {
        str(item.get("coding_id")): item
        for item in expected.get("codings") or []
        if isinstance(item, dict)
    }
    changes: list[V5MigrationChange] = []
    for old_entry in source.get("codings") or []:
        if not isinstance(old_entry, dict):
            continue
        coding_id = str(old_entry.get("coding_id") or "")
        expected_entry = expected_by_id.get(coding_id) or {}
        current_entry = current_by_id.get(coding_id) or {}
        old_coding = old_entry.get("coding") or {}
        old_fields = old_coding.get("fields") or {}
        expected_fields = ((expected_entry.get("coding") or {}).get("fields") or {})
        current_fields = ((current_entry.get("coding") or {}).get("fields") or {})
        object_type = str(old_coding.get("code_type") or "unknown")
        if object_type == "differentiation":
            before = {
                "perspectives": old_fields.get("perspectives") or [],
                "perspective_types": old_fields.get("perspective_types") or [],
            }
            after = expected_fields.get("perspectives") or []
            current_after = current_fields.get("perspectives") or []
            changes.append(
                V5MigrationChange(
                    coding_id=coding_id,
                    object_type=object_type,
                    change_type="Perspective restructuring and copied types",
                    before=before,
                    expected_after=after,
                    current_after=current_after,
                    current_matches_expected=current_after == after,
                )
            )
        if object_type == "nuance" and old_fields.get("relation_type") == "ambition_intention":
            after = expected_fields.get("relation_type")
            current_after = current_fields.get("relation_type")
            changes.append(
                V5MigrationChange(
                    coding_id=coding_id,
                    object_type=object_type,
                    change_type="Ambition/intention recoded",
                    before="ambition_intention",
                    expected_after=after,
                    current_after=current_after,
                    current_matches_expected=current_after == after,
                )
            )
        old_spans = old_entry.get("field_spans") or {}
        moved = {
            path: spans
            for path, spans in old_spans.items()
            if path.startswith("differentiation.perspective_types")
            or (path.startswith("differentiation.perspectives[") and path.endswith("]"))
        }
        if moved:
            after = {
                "active": expected_entry.get("field_spans") or {},
                "auditable_legacy": (
                    (expected_entry.get("migration_metadata") or {}).get("legacy_field_spans")
                    or {}
                ),
            }
            current_after = {
                "active": current_entry.get("field_spans") or {},
                "auditable_legacy": (
                    (current_entry.get("migration_metadata") or {}).get("legacy_field_spans")
                    or {}
                ),
            }
            changes.append(
                V5MigrationChange(
                    coding_id=coding_id,
                    object_type=object_type,
                    change_type="Transcript span-path movement",
                    before=moved,
                    expected_after=after,
                    current_after=current_after,
                    current_matches_expected=current_after == after,
                )
            )
    expected_checksum = manifest.get("post_migration_codings_sha256")
    checksum_matches = (
        _sha256(live_path) == expected_checksum
        if expected_checksum and live_path.exists()
        else None
    )
    return V5MigrationReview(
        summary=summary,
        changes=changes,
        live_checksum_matches=checksum_matches,
    )
