from __future__ import annotations

from parsing.srt_parser import TranscriptSegment


def extract_text_for_span(
    segments: list[TranscriptSegment],
    start_segment_id: str,
    start_char_offset: int,
    end_segment_id: str,
    end_char_offset: int,
) -> str:
    order = {segment.segment_id: index for index, segment in enumerate(segments)}
    by_id = {segment.segment_id: segment for segment in segments}
    if start_segment_id not in order or end_segment_id not in order:
        return ""
    start_index = order[start_segment_id]
    end_index = order[end_segment_id]
    if start_index > end_index:
        start_index, end_index = end_index, start_index
        start_segment_id, end_segment_id = end_segment_id, start_segment_id
        start_char_offset, end_char_offset = end_char_offset, start_char_offset

    if start_segment_id == end_segment_id:
        text = by_id[start_segment_id].text or ""
        start = max(0, min(len(text), int(start_char_offset)))
        end = max(0, min(len(text), int(end_char_offset)))
        if end < start:
            start, end = end, start
        return text[start:end]

    first = by_id[start_segment_id].text or ""
    start = max(0, min(len(first), int(start_char_offset)))
    chunks = [first[start:]]
    chunks.extend((segment.text or "") for segment in segments[start_index + 1 : end_index])
    last = by_id[end_segment_id].text or ""
    end = max(0, min(len(last), int(end_char_offset)))
    chunks.append(last[:end])
    return "\n".join(chunks)


def normalize_span_selection(
    segments: list[TranscriptSegment],
    payload: dict,
) -> dict | None:
    """Canonicalize a new selection by trimming only its outer whitespace.

    The returned anchors point to the first and one-past-last non-whitespace
    characters in transcript text. Interior whitespace and intermediate segments
    are preserved. Browser-provided selected text is deliberately ignored.
    """
    index_by_id = {segment.segment_id: index for index, segment in enumerate(segments)}
    segment_by_id = {segment.segment_id: segment for segment in segments}
    try:
        start_id = str(payload["start_segment_id"])
        end_id = str(payload["end_segment_id"])
        start_offset = int(payload["start_char_offset"])
        end_offset = int(payload["end_char_offset"])
    except (KeyError, TypeError, ValueError):
        return None
    if start_id not in index_by_id or end_id not in index_by_id:
        return None
    if index_by_id[start_id] > index_by_id[end_id]:
        start_id, end_id = end_id, start_id
        start_offset, end_offset = end_offset, start_offset

    start_text = segment_by_id[start_id].text or ""
    end_text = segment_by_id[end_id].text or ""
    start_offset = max(0, min(len(start_text), start_offset))
    end_offset = max(0, min(len(end_text), end_offset))
    if start_id == end_id and start_offset > end_offset:
        start_offset, end_offset = end_offset, start_offset

    start_index = index_by_id[start_id]
    end_index = index_by_id[end_id]
    first_non_whitespace: tuple[str, int] | None = None
    for index in range(start_index, end_index + 1):
        segment = segments[index]
        text = segment.text or ""
        lower = start_offset if index == start_index else 0
        upper = end_offset if index == end_index else len(text)
        while lower < upper and text[lower].isspace():
            lower += 1
        if lower < upper:
            first_non_whitespace = (segment.segment_id, lower)
            break

    last_non_whitespace: tuple[str, int] | None = None
    for index in range(end_index, start_index - 1, -1):
        segment = segments[index]
        text = segment.text or ""
        lower = start_offset if index == start_index else 0
        upper = end_offset if index == end_index else len(text)
        while upper > lower and text[upper - 1].isspace():
            upper -= 1
        if upper > lower:
            last_non_whitespace = (segment.segment_id, upper)
            break

    if first_non_whitespace is None or last_non_whitespace is None:
        return None

    normalized_start_id, normalized_start_offset = first_non_whitespace
    normalized_end_id, normalized_end_offset = last_non_whitespace
    selected_text = extract_text_for_span(
        segments,
        normalized_start_id,
        normalized_start_offset,
        normalized_end_id,
        normalized_end_offset,
    )
    if not selected_text or not selected_text.strip():
        return None
    return {
        "start_segment_id": normalized_start_id,
        "start_char_offset": normalized_start_offset,
        "end_segment_id": normalized_end_id,
        "end_char_offset": normalized_end_offset,
        "selected_text": selected_text,
    }
