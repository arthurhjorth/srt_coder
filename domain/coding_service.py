from __future__ import annotations

from datetime import datetime, timezone
import uuid

from models import CodingEntry, Comparison, Differentiation, Nuance
from parsing.srt_parser import TranscriptSegment
from storage.coding_repo import list_codings, list_codings_for_analysis, save_codings

_MISSING = object()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_entries_for_analysis(analysis_id: str) -> list[CodingEntry]:
    if not analysis_id:
        raise ValueError("analysis_id is required")
    return list_codings_for_analysis(analysis_id)


def list_entries_for_analysis_and_file(
    *,
    analysis_id: str,
    interview_file: str,
) -> list[CodingEntry]:
    if not analysis_id:
        raise ValueError("analysis_id is required")
    if not interview_file:
        raise ValueError("interview_file is required")
    return [
        c
        for c in list_codings_for_analysis(analysis_id)
        if c.interview_file == interview_file
    ]


def list_segment_ids_for_analysis(
    *,
    analysis_id: str,
    interview_file: str,
) -> set[str]:
    if not analysis_id:
        raise ValueError("analysis_id is required")
    if not interview_file:
        raise ValueError("interview_file is required")
    return {
        c.segment_id
        for c in list_codings_for_analysis(analysis_id)
        if c.interview_file == interview_file and c.segment_id
    }


def create_entry_for_segment(
    *,
    analysis_id: str,
    interview_file: str,
    segment: TranscriptSegment,
    created_by: str,
    note: str | None = None,
) -> CodingEntry:
    return create_entry_for_span(
        analysis_id=analysis_id,
        interview_file=interview_file,
        segment=segment,
        start_segment_id=segment.segment_id,
        start_char_offset=0,
        end_segment_id=segment.segment_id,
        end_char_offset=len(segment.text or ""),
        selected_text=segment.text,
        created_by=created_by,
        note=note,
    )


def create_entry_for_span(
    *,
    analysis_id: str,
    interview_file: str,
    segment: TranscriptSegment,
    start_segment_id: str,
    start_char_offset: int,
    end_segment_id: str,
    end_char_offset: int,
    selected_text: str,
    created_by: str,
    note: str | None = None,
) -> CodingEntry:
    if not analysis_id:
        raise ValueError("analysis_id is required")
    if not interview_file:
        raise ValueError("interview_file is required")
    if not created_by.strip():
        raise ValueError("created_by cannot be empty")
    if not start_segment_id or not end_segment_id:
        raise ValueError("start/end segment ids are required")
    if start_char_offset is None or end_char_offset is None:
        raise ValueError("start/end offsets are required")
    if start_char_offset < 0 or end_char_offset < 0:
        raise ValueError("Offsets cannot be negative")
    if start_segment_id == end_segment_id and start_char_offset > end_char_offset:
        raise ValueError("start offset cannot be greater than end offset")

    now = _utc_now_iso()
    entry = CodingEntry(
        coding_id=uuid.uuid4().hex,
        analysis_id=analysis_id,
        interview_file=interview_file,
        segment_id=segment.segment_id,
        segment_index=segment.index,
        segment_start_ms=segment.start_ms,
        segment_end_ms=segment.end_ms,
        start_segment_id=start_segment_id,
        start_char_offset=start_char_offset,
        end_segment_id=end_segment_id,
        end_char_offset=end_char_offset,
        speaker=segment.speaker,
        quote_text=segment.text,
        selected_text=selected_text,
        note=(note or "").strip() or None,
        created_by=created_by.strip(),
        created_at=now,
        updated_at=now,
    )
    current = list_codings()
    current.append(entry)
    save_codings(current)
    return entry


def create_object_entry(
    *,
    analysis_id: str,
    interview_file: str,
    object_type: str,
    created_by: str,
    note: str | None = None,
) -> CodingEntry:
    if not analysis_id:
        raise ValueError("analysis_id is required")
    if not interview_file:
        raise ValueError("interview_file is required")
    if not created_by.strip():
        raise ValueError("created_by cannot be empty")
    object_type = (object_type or "").strip().lower()
    if object_type not in {"differentiation", "comparison", "nuance"}:
        raise ValueError("object_type must be one of: differentiation, comparison, nuance")

    now = _utc_now_iso()
    entry = CodingEntry(
        coding_id=uuid.uuid4().hex,
        analysis_id=analysis_id,
        interview_file=interview_file,
        object_type=object_type,
        note=(note or "").strip() or None,
        comparison=Comparison() if object_type == "comparison" else None,
        differentiation=Differentiation() if object_type == "differentiation" else None,
        nuance=Nuance() if object_type == "nuance" else None,
        field_spans={},
        created_by=created_by.strip(),
        created_at=now,
        updated_at=now,
    )
    current = list_codings()
    current.append(entry)
    save_codings(current)
    return entry


def get_entry_for_analysis(
    *,
    analysis_id: str,
    coding_id: str,
) -> CodingEntry | None:
    if not analysis_id:
        raise ValueError("analysis_id is required")
    if not coding_id:
        raise ValueError("coding_id is required")
    for entry in list_codings_for_analysis(analysis_id):
        if entry.coding_id == coding_id:
            return entry
    return None


def update_entry_schema(
    *,
    analysis_id: str,
    coding_id: str,
    comparison: Comparison | None,
    note: str | None = None,
) -> CodingEntry:
    if not analysis_id:
        raise ValueError("analysis_id is required")
    if not coding_id:
        raise ValueError("coding_id is required")

    return update_entry_payload(
        analysis_id=analysis_id,
        coding_id=coding_id,
        comparison=comparison,
        note=(note or "").strip() or None,
    )


def update_entry_payload(
    *,
    analysis_id: str,
    coding_id: str,
    object_type: str | None | object = _MISSING,
    comparison: Comparison | None | object = _MISSING,
    differentiation: Differentiation | None | object = _MISSING,
    nuance: Nuance | None | object = _MISSING,
    note: str | None | object = _MISSING,
    field_spans: dict[str, list[dict]] | None | object = _MISSING,
) -> CodingEntry:
    if not analysis_id:
        raise ValueError("analysis_id is required")
    if not coding_id:
        raise ValueError("coding_id is required")

    all_entries = list_codings()
    target = None
    for i, entry in enumerate(all_entries):
        if entry.coding_id == coding_id and entry.analysis_id == analysis_id:
            target = (i, entry)
            break
    if target is None:
        raise KeyError("Coding entry not found in selected analysis")

    idx, existing = target
    updates: dict = {"updated_at": _utc_now_iso()}
    if object_type is not _MISSING:
        normalized = (object_type or "").strip().lower() if object_type else None
        if normalized not in {None, "differentiation", "comparison", "nuance"}:
            raise ValueError("object_type must be one of: differentiation, comparison, nuance")
        updates["object_type"] = normalized
    if comparison is not _MISSING:
        updates["comparison"] = comparison
    if differentiation is not _MISSING:
        updates["differentiation"] = differentiation
    if nuance is not _MISSING:
        updates["nuance"] = nuance
    if note is not _MISSING:
        updates["note"] = (note or "").strip() or None
    if field_spans is not _MISSING:
        updates["field_spans"] = field_spans

    updated = existing.model_copy(update=updates)
    all_entries[idx] = updated
    save_codings(all_entries)
    return updated


def delete_entry(
    *,
    analysis_id: str,
    coding_id: str,
) -> bool:
    if not analysis_id:
        raise ValueError("analysis_id is required")
    if not coding_id:
        raise ValueError("coding_id is required")

    all_entries = list_codings()
    kept: list[CodingEntry] = []
    removed = False
    for entry in all_entries:
        if entry.analysis_id == analysis_id and entry.coding_id == coding_id:
            removed = True
            continue
        kept.append(entry)
    if removed:
        save_codings(kept)
    return removed
