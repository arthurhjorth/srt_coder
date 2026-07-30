from __future__ import annotations

from domain import coding_service
from domain.agreement_service import AgreementRules, NormalizedAnnotation, TranscriptSpan, annotations_match
from parsing.span_normalization import normalize_span_selection
from parsing.srt_parser import TranscriptSegment


def _segment(segment_id: str, index: int, text: str) -> TranscriptSegment:
    return TranscriptSegment(
        segment_id=segment_id,
        index=index,
        start_ms=(index - 1) * 1000,
        end_ms=index * 1000,
        speaker="Speaker 1",
        text=text,
    )


def _payload(start_id: str, start: int, end_id: str, end: int, selected_text: str = "browser text") -> dict:
    return {
        "start_segment_id": start_id,
        "start_char_offset": start,
        "end_segment_id": end_id,
        "end_char_offset": end,
        "selected_text": selected_text,
    }


def test_single_segment_trims_spaces_tabs_newlines_and_unicode_whitespace() -> None:
    text = " \t\u00a0leadership \n"
    segment = _segment("seg-00001", 1, text)
    normalized = normalize_span_selection(
        [segment],
        _payload(segment.segment_id, 0, segment.segment_id, len(text)),
    )

    assert normalized == {
        "start_segment_id": "seg-00001",
        "start_char_offset": text.index("leadership"),
        "end_segment_id": "seg-00001",
        "end_char_offset": text.index("leadership") + len("leadership"),
        "selected_text": "leadership",
    }


def test_selecting_word_with_or_without_outer_whitespace_is_canonicalized_identically() -> None:
    segment = _segment("seg-00001", 1, "  leadership  ")
    with_spaces = normalize_span_selection(
        [segment],
        _payload("seg-00001", 0, "seg-00001", len(segment.text), "  leadership  "),
    )
    word_only = normalize_span_selection(
        [segment],
        _payload("seg-00001", 2, "seg-00001", 12, "leadership"),
    )
    assert with_spaces == word_only


def test_internal_whitespace_is_preserved() -> None:
    segment = _segment("seg-00001", 1, "  public   leadership  ")
    normalized = normalize_span_selection(
        [segment],
        _payload("seg-00001", 0, "seg-00001", len(segment.text)),
    )
    assert normalized["selected_text"] == "public   leadership"


def test_whitespace_only_selection_is_rejected() -> None:
    segment = _segment("seg-00001", 1, " \t\n\u00a0 ")
    assert (
        normalize_span_selection(
            [segment],
            _payload("seg-00001", 0, "seg-00001", len(segment.text)),
        )
        is None
    )


def test_multi_segment_selection_trims_only_outer_edges_and_skips_blank_edge_segment() -> None:
    segments = [
        _segment("seg-00001", 1, "   "),
        _segment("seg-00002", 2, "\talpha  "),
        _segment("seg-00003", 3, " beta \n"),
    ]
    normalized = normalize_span_selection(
        segments,
        _payload("seg-00001", 0, "seg-00003", len(segments[2].text)),
    )
    assert normalized == {
        "start_segment_id": "seg-00002",
        "start_char_offset": 1,
        "end_segment_id": "seg-00003",
        "end_char_offset": 5,
        "selected_text": "alpha  \n beta",
    }


def test_browser_selected_text_is_reconstructed_from_transcript() -> None:
    segment = _segment("seg-00001", 1, "  canonical text  ")
    normalized = normalize_span_selection(
        [segment],
        _payload("seg-00001", 0, "seg-00001", len(segment.text), "UI metadata and wrong text"),
    )
    assert normalized["selected_text"] == "canonical text"


def test_new_service_span_is_trimmed_before_persistence() -> None:
    segment = _segment("seg-00001", 1, "  leadership  ")
    saved = {"codings": None}
    original_list = coding_service.list_codings
    original_save = coding_service.save_codings
    coding_service.list_codings = lambda: []
    coding_service.save_codings = lambda codings: saved.__setitem__("codings", codings)
    try:
        created = coding_service.create_entry_for_span(
            analysis_id="analysis",
            interview_file="fixture.srt",
            segment=segment,
            start_segment_id=segment.segment_id,
            start_char_offset=0,
            end_segment_id=segment.segment_id,
            end_char_offset=len(segment.text),
            selected_text="  leadership  ",
            created_by="coder",
        )
    finally:
        coding_service.list_codings = original_list
        coding_service.save_codings = original_save

    assert created.start_char_offset == 2
    assert created.end_char_offset == 12
    assert created.selected_text == "leadership"
    assert saved["codings"] == [created]


def test_canonicalized_equivalent_selections_match_under_exact_agreement_rules() -> None:
    segment = _segment("seg-00001", 1, "  leadership  ")
    left_payload = normalize_span_selection(
        [segment],
        _payload("seg-00001", 0, "seg-00001", len(segment.text)),
    )
    right_payload = normalize_span_selection(
        [segment],
        _payload("seg-00001", 2, "seg-00001", 12),
    )
    assert left_payload is not None and right_payload is not None

    def annotation(source_index: int, payload: dict) -> NormalizedAnnotation:
        return NormalizedAnnotation(
            annotation_id=source_index,
            source_index=source_index,
            source_label=f"coder-{source_index}",
            source_name=f"coder-{source_index}.json",
            analysis_id=f"analysis-{source_index}",
            analysis_name="Analysis",
            interview_file="fixture.srt",
            coding_id=f"coding-{source_index}",
            object_type="differentiation",
            field_path="differentiation.thing_being_considered_extract",
            normalized_field_path="differentiation.thing_being_considered_extract",
            root_object_key=f"coding-{source_index}",
            embedded_parent_path=None,
            normalized_embedded_parent_path=None,
            span=TranscriptSpan(**payload),
        )

    assert annotations_match(annotation(0, left_payload), annotation(1, right_payload), AgreementRules(span_mode="exact"))
