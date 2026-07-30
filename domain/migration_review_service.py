from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from domain.differentiation_migration import (
    OLD_COMPLEXITY,
    OLD_UNITARY,
    OLD_WHY,
    TARGET_IMPLICATIONS,
    TARGET_PERSPECTIVES,
    TARGET_WHY,
    migrate_coding_entry_payload,
)


@dataclass(frozen=True)
class MigrationBackupSummary:
    directory: Path
    label: str
    status: str
    created_at: str
    coding_count: int
    migrated_coding_count: int


@dataclass(frozen=True)
class FieldMigrationChange:
    coding_id: str
    object_label: str
    source_path: str
    target_path: str
    source_label: str
    target_label: str
    retained_before: str
    migrated_from_legacy: str
    expected_after: str
    current_after: str | None
    retained_spans_before: list[dict]
    legacy_spans: list[dict]
    expected_spans: list[dict]
    current_spans: list[dict] | None
    current_matches_expected: bool


@dataclass(frozen=True)
class AnalysisMigrationReview:
    analysis_id: str
    name: str
    owner: str
    interview_file: str
    changes: list[FieldMigrationChange]


@dataclass(frozen=True)
class MigrationReview:
    backup: MigrationBackupSummary
    manifest: dict
    live_store_matches_migration_checksum: bool | None
    analyses: list[AnalysisMigrationReview]
    changed_coding_count: int
    changed_field_count: int
    moved_span_count: int


def _read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _summary(directory: Path) -> MigrationBackupSummary:
    manifest_path = directory / "migration_manifest.json"
    manifest_error = False
    try:
        manifest = _read_json(manifest_path) if manifest_path.exists() else {}
    except Exception:
        manifest = {}
        manifest_error = True
    coding_count = int(manifest.get("coding_count") or 0)
    legacy_ids = manifest.get("legacy_coding_ids")
    legacy_indices = manifest.get("legacy_coding_indices")
    migrated_count = len(legacy_ids) if isinstance(legacy_ids, list) else len(legacy_indices or [])
    created_at = str(manifest.get("created_at") or directory.name)
    status = "invalid manifest" if manifest_error else str(manifest.get("status") or "legacy manifest")
    return MigrationBackupSummary(
        directory=directory,
        label=f"{created_at} · {status}",
        status=status,
        created_at=created_at,
        coding_count=coding_count,
        migrated_coding_count=migrated_count,
    )


def list_migration_backups(backup_root: Path) -> list[MigrationBackupSummary]:
    if not backup_root.exists():
        return []
    backups = [
        _summary(path)
        for path in backup_root.iterdir()
        if path.is_dir() and (path / "analyses.json").is_file() and (path / "codings.json").is_file()
    ]
    return sorted(backups, key=lambda item: item.directory.name, reverse=True)


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def _spans(payload: dict, path: str) -> list[dict]:
    value = (payload.get("field_spans") or {}).get(path, [])
    if not isinstance(value, list):
        return []
    return [span for span in value if isinstance(span, dict)]


def _change(
    *,
    old_coding: dict,
    expected_coding: dict,
    current_coding: dict | None,
    old_container: dict,
    expected_container: dict,
    current_container: dict | None,
    source_name: str,
    target_name: str,
    source_path: str,
    target_path: str,
    source_label: str,
    target_label: str,
    object_label: str,
) -> FieldMigrationChange | None:
    source_value = _text(old_container.get(source_name))
    legacy_spans = _spans(old_coding, source_path)
    if not source_value.strip() and not legacy_spans:
        return None
    retained_before = _text(old_container.get(target_name))
    expected_after = _text(expected_container.get(target_name))
    current_after = _text(current_container.get(target_name)) if current_container is not None else None
    retained_spans = _spans(old_coding, target_path)
    expected_spans = _spans(expected_coding, target_path)
    current_spans = _spans(current_coding, target_path) if current_coding is not None else None
    return FieldMigrationChange(
        coding_id=str(old_coding.get("coding_id") or ""),
        object_label=object_label,
        source_path=source_path,
        target_path=target_path,
        source_label=source_label,
        target_label=target_label,
        retained_before=retained_before,
        migrated_from_legacy=source_value,
        expected_after=expected_after,
        current_after=current_after,
        retained_spans_before=retained_spans,
        legacy_spans=legacy_spans,
        expected_spans=expected_spans,
        current_spans=current_spans,
        current_matches_expected=(
            current_after == expected_after and current_spans == expected_spans
            if current_coding is not None
            else False
        ),
    )


def _coding_changes(old: dict, expected: dict, current: dict | None) -> list[FieldMigrationChange]:
    old_diff = old.get("differentiation")
    expected_diff = expected.get("differentiation")
    current_diff = current.get("differentiation") if current else None
    if not isinstance(old_diff, dict) or not isinstance(expected_diff, dict):
        return []
    if not isinstance(current_diff, dict):
        current_diff = None

    changes: list[FieldMigrationChange] = []
    top_mappings = (
        (OLD_WHY, TARGET_WHY, "Why is this a thing or how did it happen?", "Why considered or important"),
        (
            OLD_UNITARY,
            TARGET_PERSPECTIVES,
            "What is wrong with taking a unitary perspective?",
            "Why important to take different perspectives",
        ),
    )
    for source_name, target_name, source_label, target_label in top_mappings:
        for suffix, label_suffix in (("", ""), ("_comment", " comment")):
            change = _change(
                old_coding=old,
                expected_coding=expected,
                current_coding=current,
                old_container=old_diff,
                expected_container=expected_diff,
                current_container=current_diff,
                source_name=f"{source_name}{suffix}",
                target_name=f"{target_name}{suffix}",
                source_path=f"differentiation.{source_name}{suffix}",
                target_path=f"differentiation.{target_name}{suffix}",
                source_label=f"{source_label}{label_suffix}",
                target_label=f"{target_label}{label_suffix}",
                object_label="Differentiation",
            )
            if change is not None:
                changes.append(change)

    old_perspectives = old_diff.get("perspectives_extract") or []
    expected_perspectives = expected_diff.get("perspectives_extract") or []
    current_perspectives = (current_diff.get("perspectives_extract") or []) if current_diff else []
    for index, old_perspective in enumerate(old_perspectives):
        if not isinstance(old_perspective, dict) or index >= len(expected_perspectives):
            continue
        expected_perspective = expected_perspectives[index]
        current_perspective = (
            current_perspectives[index]
            if index < len(current_perspectives) and isinstance(current_perspectives[index], dict)
            else None
        )
        for suffix, label_suffix in (("", ""), ("_comment", " comment")):
            change = _change(
                old_coding=old,
                expected_coding=expected,
                current_coding=current,
                old_container=old_perspective,
                expected_container=expected_perspective,
                current_container=current_perspective,
                source_name=f"{OLD_COMPLEXITY}{suffix}",
                target_name=f"{TARGET_IMPLICATIONS}{suffix}",
                source_path=f"differentiation.perspectives_extract[{index}].{OLD_COMPLEXITY}{suffix}",
                target_path=f"differentiation.perspectives_extract[{index}].{TARGET_IMPLICATIONS}{suffix}",
                source_label=f"How this perspective adds complexity/difficulty{label_suffix}",
                target_label=f"What are the implications?{label_suffix}",
                object_label=f"Differentiation · Perspective {index + 1}",
            )
            if change is not None:
                changes.append(change)
    return changes


def build_migration_review(backup_dir: Path, live_codings_path: Path) -> MigrationReview:
    backup = _summary(backup_dir)
    analyses_store = _read_json(backup_dir / "analyses.json")
    old_store = _read_json(backup_dir / "codings.json")
    current_store = _read_json(live_codings_path)
    old_codings = old_store.get("codings") or []
    current_by_id = {
        str(coding.get("coding_id") or ""): coding
        for coding in current_store.get("codings") or []
        if isinstance(coding, dict)
    }
    analyses_by_id = {
        str(analysis.get("analysis_id") or ""): analysis
        for analysis in analyses_store.get("analyses") or []
        if isinstance(analysis, dict)
    }
    changes_by_analysis: dict[str, list[FieldMigrationChange]] = {}
    changed_coding_ids: set[str] = set()
    for old in old_codings:
        if not isinstance(old, dict):
            continue
        expected = migrate_coding_entry_payload(old)
        coding_id = str(old.get("coding_id") or "")
        changes = _coding_changes(old, expected, current_by_id.get(coding_id))
        if not changes:
            continue
        analysis_id = str(old.get("analysis_id") or "")
        changes_by_analysis.setdefault(analysis_id, []).extend(changes)
        changed_coding_ids.add(coding_id)

    analysis_reviews: list[AnalysisMigrationReview] = []
    for analysis_id, changes in changes_by_analysis.items():
        analysis = analyses_by_id.get(analysis_id, {})
        analysis_reviews.append(
            AnalysisMigrationReview(
                analysis_id=analysis_id,
                name=str(analysis.get("name") or "Unnamed analysis"),
                owner=str(analysis.get("owner_username") or "unknown"),
                interview_file=str(analysis.get("interview_file") or "unknown"),
                changes=changes,
            )
        )
    analysis_reviews.sort(key=lambda item: (item.name.lower(), item.owner.lower()))

    manifest_path = backup_dir / "migration_manifest.json"
    manifest = _read_json(manifest_path) if manifest_path.exists() else {}
    post_hash = manifest.get("post_migration_codings_sha256")
    checksum_matches = _sha256(live_codings_path) == post_hash if isinstance(post_hash, str) else None
    all_changes = [change for review in analysis_reviews for change in review.changes]
    return MigrationReview(
        backup=backup,
        manifest=manifest,
        live_store_matches_migration_checksum=checksum_matches,
        analyses=analysis_reviews,
        changed_coding_count=len(changed_coding_ids),
        changed_field_count=len(all_changes),
        moved_span_count=sum(len(change.legacy_spans) for change in all_changes),
    )
