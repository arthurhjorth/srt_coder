from __future__ import annotations

from datetime import datetime, timezone
import uuid

from coding_books.simplified_v4.models import (
    ComparisonCoding,
    DifferentiationCoding,
    NuanceCoding,
    SimplifiedCoding,
    SimplifiedCodingEntry,
    TranscriptSpan,
)
from storage.simplified_coding_repo import (
    list_codings,
    list_codings_for_analysis,
    save_codings,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_coding(object_type: str) -> SimplifiedCoding:
    normalized = (object_type or "").strip().lower()
    if normalized == "differentiation":
        return DifferentiationCoding()
    if normalized == "comparison":
        return ComparisonCoding()
    if normalized == "nuance":
        return NuanceCoding()
    raise ValueError("object_type must be one of: differentiation, comparison, nuance")


def list_entries_for_analysis(analysis_id: str) -> list[SimplifiedCodingEntry]:
    if not analysis_id:
        raise ValueError("analysis_id is required")
    return list_codings_for_analysis(analysis_id)


def list_entries_for_analysis_and_file(
    *,
    analysis_id: str,
    interview_file: str,
) -> list[SimplifiedCodingEntry]:
    if not analysis_id:
        raise ValueError("analysis_id is required")
    if not interview_file:
        raise ValueError("interview_file is required")
    return [
        coding
        for coding in list_codings_for_analysis(analysis_id)
        if coding.interview_file == interview_file
    ]


def create_object_entry(
    *,
    analysis_id: str,
    interview_file: str,
    object_type: str,
    created_by: str,
) -> SimplifiedCodingEntry:
    if not analysis_id:
        raise ValueError("analysis_id is required")
    if not interview_file:
        raise ValueError("interview_file is required")
    normalized_creator = (created_by or "").strip()
    if not normalized_creator:
        raise ValueError("created_by cannot be empty")

    now = _utc_now_iso()
    entry = SimplifiedCodingEntry(
        coding_id=uuid.uuid4().hex,
        analysis_id=analysis_id,
        interview_file=interview_file,
        coding=_new_coding(object_type),
        created_by=normalized_creator,
        created_at=now,
        updated_at=now,
    )
    current = list_codings()
    current.append(entry)
    save_codings(current)
    return entry


def update_entry_payload(
    *,
    analysis_id: str,
    coding_id: str,
    coding: SimplifiedCoding,
    field_spans: dict[str, list[TranscriptSpan]] | None = None,
) -> SimplifiedCodingEntry:
    if not analysis_id:
        raise ValueError("analysis_id is required")
    if not coding_id:
        raise ValueError("coding_id is required")

    all_entries = list_codings()
    target_index = next(
        (
            index
            for index, entry in enumerate(all_entries)
            if entry.coding_id == coding_id and entry.analysis_id == analysis_id
        ),
        None,
    )
    if target_index is None:
        raise KeyError("Coding entry not found in selected analysis")

    existing = all_entries[target_index]
    validated_coding = type(existing.coding).model_validate(coding)
    if validated_coding.code_type != existing.coding.code_type:
        raise ValueError("A coding object cannot change type after it has been created.")

    updated = existing.model_copy(
        update={
            "coding": validated_coding,
            "field_spans": (
                existing.field_spans
                if field_spans is None
                else {
                    key: [TranscriptSpan.model_validate(span) for span in spans]
                    for key, spans in field_spans.items()
                }
            ),
            "updated_at": _utc_now_iso(),
        }
    )
    all_entries[target_index] = SimplifiedCodingEntry.model_validate(updated)
    save_codings(all_entries)
    return all_entries[target_index]


def delete_entry(*, analysis_id: str, coding_id: str) -> bool:
    if not analysis_id:
        raise ValueError("analysis_id is required")
    if not coding_id:
        raise ValueError("coding_id is required")

    all_entries = list_codings()
    kept = [
        entry
        for entry in all_entries
        if not (entry.analysis_id == analysis_id and entry.coding_id == coding_id)
    ]
    if len(kept) == len(all_entries):
        return False
    save_codings(kept)
    return True
