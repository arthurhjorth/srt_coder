from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import re
import uuid

from config import EXPORTS_DIR
from domain.transcript_service import list_interview_files
from models import Analysis, CodingEntry, User
from storage.analyses_repo import list_analyses, save_analyses
from storage.coding_repo import list_codings, save_codings
from storage.users_repo import list_users, save_users


EXPORT_VERSION = "1"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_slug(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    return value.strip("-") or "analysis"


def _analysis_natural_key(owner_username: str | None, interview_file: str | None, name: str | None) -> tuple[str, str, str]:
    return (
        (owner_username or "").strip().lower(),
        (interview_file or "").strip().lower(),
        (name or "").strip().lower(),
    )


def export_analysis_to_file(*, analysis_id: str) -> Path:
    if not analysis_id:
        raise ValueError("analysis_id is required")

    analyses = list_analyses()
    target = next((a for a in analyses if a.analysis_id == analysis_id), None)
    if target is None:
        raise KeyError("Analysis not found")

    codings = [c for c in list_codings() if c.analysis_id == analysis_id]
    usernames: set[str] = set()
    if target.owner_username:
        usernames.add(target.owner_username)
    for coding in codings:
        if coding.created_by:
            usernames.add(coding.created_by)

    users = [u for u in list_users() if u.username in usernames]

    payload = {
        "export_version": EXPORT_VERSION,
        "exported_at": _utc_now_iso(),
        "analyses": [target.model_dump(mode="json")],
        "codings": [c.model_dump(mode="json") for c in codings],
        "users": [u.model_dump(mode="json") for u in users],
    }

    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = _safe_slug(f"{target.name or analysis_id}-{target.owner_username or 'owner'}")
    out_path = EXPORTS_DIR / f"analysis_export_{stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


def import_analyses_from_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Import payload must be a JSON object")

    analyses_raw = payload.get("analyses")
    if analyses_raw is None and payload.get("analysis") is not None:
        analyses_raw = [payload.get("analysis")]
    if not isinstance(analyses_raw, list):
        raise ValueError("Import payload must contain an analyses list")

    codings_raw = payload.get("codings") or []
    users_raw = payload.get("users") or []
    if not isinstance(codings_raw, list):
        raise ValueError("codings must be a list")
    if not isinstance(users_raw, list):
        raise ValueError("users must be a list")

    existing_users = list_users()
    existing_analyses = list_analyses()
    existing_codings = list_codings()

    users_by_name = {
        (u.username or "").strip().lower(): u
        for u in existing_users
        if u.username
    }

    imported_users = 0
    for raw in users_raw:
        user = User.model_validate(raw)
        key = (user.username or "").strip().lower()
        if not key:
            continue
        if key in users_by_name:
            continue
        existing_users.append(user)
        users_by_name[key] = user
        imported_users += 1

    available_files = {name.lower() for name in list_interview_files()}
    analysis_id_map: dict[str, str] = {}

    imported_analyses = 0
    skipped_missing_transcript = 0
    skipped_existing_analysis = 0

    natural_keys = {
        _analysis_natural_key(a.owner_username, a.interview_file, a.name)
        for a in existing_analyses
    }

    for raw in analyses_raw:
        source = Analysis.model_validate(raw)
        interview_file = (source.interview_file or "").strip()
        if not interview_file or interview_file.lower() not in available_files:
            skipped_missing_transcript += 1
            continue

        owner_username = (source.owner_username or "").strip() or "unknown"
        owner_key = owner_username.lower()
        if owner_key not in users_by_name:
            placeholder = User(
                username=owner_username,
                password_hash=None,
                role="imported",
                is_active=False,
                created_at=_utc_now_iso(),
                updated_at=_utc_now_iso(),
            )
            existing_users.append(placeholder)
            users_by_name[owner_key] = placeholder
            imported_users += 1

        key = _analysis_natural_key(owner_username, interview_file, source.name)
        if key in natural_keys:
            skipped_existing_analysis += 1
            continue

        new_id = uuid.uuid4().hex
        created = source.model_copy(
            update={
                "analysis_id": new_id,
                "owner_username": owner_username,
                "interview_file": interview_file,
                "created_at": source.created_at or _utc_now_iso(),
                "updated_at": _utc_now_iso(),
            }
        )
        existing_analyses.append(created)
        natural_keys.add(key)
        if source.analysis_id:
            analysis_id_map[source.analysis_id] = new_id
        imported_analyses += 1

    imported_codings = 0
    skipped_codings_without_analysis = 0

    for raw in codings_raw:
        source = CodingEntry.model_validate(raw)
        source_analysis_id = source.analysis_id
        if not source_analysis_id or source_analysis_id not in analysis_id_map:
            skipped_codings_without_analysis += 1
            continue

        created_by = (source.created_by or "").strip()
        if created_by:
            created_by_key = created_by.lower()
            if created_by_key not in users_by_name:
                placeholder = User(
                    username=created_by,
                    password_hash=None,
                    role="imported",
                    is_active=False,
                    created_at=_utc_now_iso(),
                    updated_at=_utc_now_iso(),
                )
                existing_users.append(placeholder)
                users_by_name[created_by_key] = placeholder
                imported_users += 1

        created = source.model_copy(
            update={
                "coding_id": uuid.uuid4().hex,
                "analysis_id": analysis_id_map[source_analysis_id],
                "created_at": source.created_at or _utc_now_iso(),
                "updated_at": _utc_now_iso(),
            }
        )
        existing_codings.append(created)
        imported_codings += 1

    save_users(existing_users)
    save_analyses(existing_analyses)
    save_codings(existing_codings)

    return {
        "imported_users": imported_users,
        "imported_analyses": imported_analyses,
        "imported_codings": imported_codings,
        "skipped_missing_transcript": skipped_missing_transcript,
        "skipped_existing_analysis": skipped_existing_analysis,
        "skipped_codings_without_analysis": skipped_codings_without_analysis,
    }


def import_analyses_from_json_text(raw_text: str) -> dict:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc
    return import_analyses_from_payload(payload)
