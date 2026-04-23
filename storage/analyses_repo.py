from __future__ import annotations

from typing import Optional

from config import ANALYSES_JSON
from models import Analysis
from storage.fs_store import read_json, write_json


def list_analyses() -> list[Analysis]:
    payload = read_json(ANALYSES_JSON, default={"analyses": []})
    return [Analysis.model_validate(a) for a in payload.get("analyses", [])]


def save_analyses(analyses: list[Analysis]) -> None:
    payload = {"analyses": [a.model_dump(mode="json") for a in analyses]}
    write_json(ANALYSES_JSON, payload)


def get_analysis_by_id(analysis_id: str) -> Optional[Analysis]:
    for analysis in list_analyses():
        if analysis.analysis_id == analysis_id:
            return analysis
    return None
