from __future__ import annotations

from datetime import datetime, timezone
import uuid

from models import Analysis
from storage.analyses_repo import get_analysis_by_id, list_analyses, save_analyses


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_analyses_for_interview(interview_file: str) -> list[Analysis]:
    return [
        analysis
        for analysis in list_analyses()
        if analysis.interview_file == interview_file
    ]


def create_analysis(
    *,
    owner_username: str,
    interview_file: str,
    name: str,
    description: str | None = None,
) -> Analysis:
    if not owner_username.strip():
        raise ValueError("Owner username cannot be empty")
    if not interview_file.strip():
        raise ValueError("Interview file cannot be empty")
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Analysis name cannot be empty")

    now = _utc_now_iso()
    analysis = Analysis(
        analysis_id=uuid.uuid4().hex,
        owner_username=owner_username.strip(),
        interview_file=interview_file.strip(),
        name=clean_name,
        description=(description or "").strip() or None,
        created_at=now,
        updated_at=now,
    )
    current = list_analyses()
    current.append(analysis)
    save_analyses(current)
    return analysis


def get_analysis(analysis_id: str) -> Analysis | None:
    return get_analysis_by_id(analysis_id)
