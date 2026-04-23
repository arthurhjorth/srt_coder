from models import CodingEntry, Comparison
from domain import coding_service
from parsing.srt_parser import TranscriptSegment


def test_list_entries_requires_analysis_id() -> None:
    try:
        coding_service.list_entries_for_analysis("")
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError for missing analysis_id")


def test_segment_ids_are_scoped_by_analysis_and_file() -> None:
    def fake_list_for_analysis(analysis_id: str):
        if analysis_id == "a1":
            return [
                CodingEntry(
                    analysis_id="a1",
                    interview_file="file1.srt",
                    segment_id="seg-00001",
                ),
                CodingEntry(
                    analysis_id="a1",
                    interview_file="file2.srt",
                    segment_id="seg-00002",
                ),
            ]
        if analysis_id == "a2":
            return [
                CodingEntry(
                    analysis_id="a2",
                    interview_file="file1.srt",
                    segment_id="seg-99999",
                ),
            ]
        return []

    original = coding_service.list_codings_for_analysis
    coding_service.list_codings_for_analysis = fake_list_for_analysis
    try:
        s1 = coding_service.list_segment_ids_for_analysis(
            analysis_id="a1",
            interview_file="file1.srt",
        )
        s2 = coding_service.list_segment_ids_for_analysis(
            analysis_id="a2",
            interview_file="file1.srt",
        )
    finally:
        coding_service.list_codings_for_analysis = original

    assert s1 == {"seg-00001"}
    assert s2 == {"seg-99999"}


def test_update_entry_schema_is_scoped_to_analysis() -> None:
    entries = [
        CodingEntry(coding_id="c1", analysis_id="a1", interview_file="file.srt"),
        CodingEntry(coding_id="c1", analysis_id="a2", interview_file="file.srt"),
    ]

    original_list = coding_service.list_codings
    original_save = coding_service.save_codings
    saved = {"entries": None}

    def fake_list():
        return [e.model_copy() for e in entries]

    def fake_save(new_entries):
        saved["entries"] = new_entries

    coding_service.list_codings = fake_list
    coding_service.save_codings = fake_save
    try:
        updated = coding_service.update_entry_schema(
            analysis_id="a2",
            coding_id="c1",
            comparison=Comparison(comparand="X"),
            note="note",
        )
    finally:
        coding_service.list_codings = original_list
        coding_service.save_codings = original_save

    assert updated.analysis_id == "a2"
    assert updated.comparison is not None
    assert updated.comparison.comparand == "X"
    assert saved["entries"] is not None
    assert saved["entries"][0].comparison is None
    assert saved["entries"][1].comparison is not None


def test_create_entry_for_span_requires_valid_offsets() -> None:
    seg = TranscriptSegment(
        segment_id="seg-00001",
        index=1,
        start_ms=0,
        end_ms=1000,
        speaker="Speaker 1",
        text="abcdef",
    )
    try:
        coding_service.create_entry_for_span(
            analysis_id="a1",
            interview_file="file.srt",
            segment=seg,
            start_segment_id="seg-00001",
            start_char_offset=5,
            end_segment_id="seg-00001",
            end_char_offset=2,
            selected_text="",
            created_by="admin",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError for reversed same-segment offsets")
