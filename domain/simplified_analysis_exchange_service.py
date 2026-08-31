from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import uuid

from coding_books.simplified_v4.models import CODING_BOOK_VERSION, SimplifiedCodingEntry
from config import EXPORTS_V4_DIR
from core_models import Analysis, User
from domain.transcript_service import list_interview_files
from storage.analyses_repo import list_analyses, save_analyses
from storage.simplified_coding_repo import list_codings, save_codings
from storage.users_repo import list_users, save_users


EXPORT_FORMAT_VERSION = 1


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_slug(value: str) -> str:
    normalized = (value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9._-]+", "-", normalized)
    return normalized.strip("-") or "analysis"


def _analysis_natural_key(
    owner_username: str | None,
    interview_file: str | None,
    name: str | None,
) -> tuple[str, str, str]:
    return (
        (owner_username or "").strip().lower(),
        (interview_file or "").strip().lower(),
        (name or "").strip().lower(),
    )


def _validate_export_envelope(payload: dict) -> None:
    if payload.get("export_format_version") != EXPORT_FORMAT_VERSION:
        raise ValueError("Unsupported simplified coding export format.")
    if payload.get("coding_book_version") != CODING_BOOK_VERSION:
        raise ValueError(
            "This file belongs to another coding book. Legacy exports are preserved but cannot "
            "be imported into coding book v4 without an explicit migration."
        )


def export_analysis_to_file(*, analysis_id: str) -> Path:
    if not analysis_id:
        raise ValueError("analysis_id is required")

    analyses = list_analyses()
    target = next((analysis for analysis in analyses if analysis.analysis_id == analysis_id), None)
    if target is None:
        raise KeyError("Analysis not found")

    codings = [coding for coding in list_codings() if coding.analysis_id == analysis_id]
    usernames = {target.owner_username} if target.owner_username else set()
    usernames.update(coding.created_by for coding in codings if coding.created_by)
    users = [user for user in list_users() if user.username in usernames]

    payload = {
        "export_format_version": EXPORT_FORMAT_VERSION,
        "coding_book_version": CODING_BOOK_VERSION,
        "exported_at": _utc_now_iso(),
        "analyses": [target.model_dump(mode="json")],
        "codings": [coding.model_dump(mode="json") for coding in codings],
        "users": [user.model_dump(mode="json") for user in users],
    }

    EXPORTS_V4_DIR.mkdir(parents=True, exist_ok=True)
    stem = _safe_slug(f"{target.name or analysis_id}-{target.owner_username or 'owner'}")
    output = EXPORTS_V4_DIR / (
        f"analysis_export_v4_{stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def import_analyses_from_payload(payload: dict) -> dict[str, int]:
    if not isinstance(payload, dict):
        raise ValueError("Import payload must be a JSON object")
    _validate_export_envelope(payload)

    analyses_raw = payload.get("analyses")
    codings_raw = payload.get("codings") or []
    users_raw = payload.get("users") or []
    if not isinstance(analyses_raw, list):
        raise ValueError("Import payload must contain an analyses list")
    if not isinstance(codings_raw, list):
        raise ValueError("codings must be a list")
    if not isinstance(users_raw, list):
        raise ValueError("users must be a list")

    parsed_analyses = [Analysis.model_validate(raw) for raw in analyses_raw]
    parsed_codings = [SimplifiedCodingEntry.model_validate(raw) for raw in codings_raw]
    parsed_users = [User.model_validate(raw) for raw in users_raw]

    existing_users = list_users()
    existing_analyses = list_analyses()
    existing_codings = list_codings()
    users_by_name = {
        (user.username or "").strip().lower(): user
        for user in existing_users
        if user.username
    }

    imported_users = 0
    for user in parsed_users:
        key = (user.username or "").strip().lower()
        if not key or key in users_by_name:
            continue
        existing_users.append(user)
        users_by_name[key] = user
        imported_users += 1

    available_files = {filename.lower() for filename in list_interview_files()}
    natural_keys = {
        _analysis_natural_key(analysis.owner_username, analysis.interview_file, analysis.name)
        for analysis in existing_analyses
    }
    analysis_id_map: dict[str, str] = {}
    imported_analyses = 0
    skipped_missing_transcript = 0
    skipped_existing_analysis = 0

    for source in parsed_analyses:
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

        natural_key = _analysis_natural_key(owner_username, interview_file, source.name)
        if natural_key in natural_keys:
            skipped_existing_analysis += 1
            continue

        new_analysis_id = uuid.uuid4().hex
        existing_analyses.append(
            source.model_copy(
                update={
                    "analysis_id": new_analysis_id,
                    "owner_username": owner_username,
                    "interview_file": interview_file,
                    "created_at": source.created_at or _utc_now_iso(),
                    "updated_at": _utc_now_iso(),
                }
            )
        )
        natural_keys.add(natural_key)
        if source.analysis_id:
            analysis_id_map[source.analysis_id] = new_analysis_id
        imported_analyses += 1

    imported_codings = 0
    skipped_codings_without_analysis = 0
    for source in parsed_codings:
        if source.analysis_id not in analysis_id_map:
            skipped_codings_without_analysis += 1
            continue
        creator_key = source.created_by.lower()
        if creator_key not in users_by_name:
            placeholder = User(
                username=source.created_by,
                password_hash=None,
                role="imported",
                is_active=False,
                created_at=_utc_now_iso(),
                updated_at=_utc_now_iso(),
            )
            existing_users.append(placeholder)
            users_by_name[creator_key] = placeholder
            imported_users += 1

        now = _utc_now_iso()
        existing_codings.append(
            source.model_copy(
                update={
                    "coding_id": uuid.uuid4().hex,
                    "analysis_id": analysis_id_map[source.analysis_id],
                    "created_at": source.created_at or now,
                    "updated_at": now,
                }
            )
        )
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


def import_analyses_from_json_text(raw_text: str) -> dict[str, int]:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc
    return import_analyses_from_payload(payload)
