from __future__ import annotations

from dataclasses import dataclass
import json
import re


TIME_RANGE_RE = re.compile(
    r"^\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*"
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*$"
)
SPEAKER_RE = re.compile(r"^\[(?P<speaker>[^\]]+)\]\s*(?P<text>.*)$", re.DOTALL)


@dataclass
class TranscriptSegment:
    segment_id: str
    index: int
    start_ms: int
    end_ms: int
    speaker: str
    text: str


def parse_timestamp_to_ms(value: str) -> int:
    match = re.match(r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})$", value.strip())
    if not match:
        raise ValueError(f"Invalid timestamp: {value!r}")
    hours, minutes, seconds, millis = [int(part, 10) for part in match.groups()]
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def extract_speaker(text: str) -> tuple[str, str]:
    stripped = text.strip()
    if not stripped:
        return "Unknown", ""
    match = SPEAKER_RE.match(stripped)
    if not match:
        return "Unknown", stripped
    speaker = match.group("speaker").strip() or "Unknown"
    # Guard against JSON payloads that start with '[' and would otherwise be
    # misread as a speaker marker (e.g. [{"Start": ...}]).
    if any(token in speaker for token in ['{', '}', '"', ':']):
        return "Unknown", stripped
    spoken_text = match.group("text").strip()
    return speaker, spoken_text


def parse_srt(content: str) -> list[TranscriptSegment]:
    blocks = [b.strip() for b in re.split(r"\r?\n\s*\r?\n", content.strip()) if b.strip()]
    segments: list[TranscriptSegment] = []

    for sequence, block in enumerate(blocks, start=1):
        lines = [line.rstrip() for line in block.splitlines() if line.strip() != ""]
        if len(lines) < 2:
            continue

        cursor = 0
        if lines[0].strip().isdigit():
            index = int(lines[0].strip(), 10)
            cursor = 1
        else:
            index = sequence

        if cursor >= len(lines):
            continue

        time_match = TIME_RANGE_RE.match(lines[cursor])
        if not time_match:
            continue

        start_raw = ":".join(time_match.groups()[0:3]) + "," + time_match.group(4)
        end_raw = ":".join(time_match.groups()[4:7]) + "," + time_match.group(8)
        start_ms = parse_timestamp_to_ms(start_raw)
        end_ms = parse_timestamp_to_ms(end_raw)

        text = "\n".join(lines[cursor + 1 :]).strip()
        speaker, spoken_text = extract_speaker(text)
        if not spoken_text:
            spoken_text = text

        segments.append(
            TranscriptSegment(
                segment_id=f"seg-{index:05d}",
                index=index,
                start_ms=start_ms,
                end_ms=end_ms,
                speaker=speaker,
                text=spoken_text,
            )
        )

    # Fallback: some interview files are a single SRT cue containing
    # a JSON array with timestamped chunks.
    if len(segments) == 1:
        json_segments = _try_parse_json_payload(segments[0].text)
        if json_segments:
            return json_segments

    return segments


def _try_parse_json_payload(payload: str) -> list[TranscriptSegment]:
    raw = payload.strip()
    if not raw.startswith("["):
        return []
    items = _decode_json_array_tolerant(raw)
    if not items:
        return []

    segments: list[TranscriptSegment] = []
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        try:
            start = float(item["Start"])
            end = float(item["End"])
        except (KeyError, TypeError, ValueError):
            continue
        content = str(item.get("Content", "")).strip()
        if not content:
            continue
        speaker_raw = item.get("Speaker")
        if speaker_raw is None:
            speaker = "Unknown"
        elif isinstance(speaker_raw, (int, float)):
            speaker = f"Speaker {int(speaker_raw)}"
        else:
            speaker = str(speaker_raw).strip() or "Unknown"

        segments.append(
            TranscriptSegment(
                segment_id=f"seg-{idx:05d}",
                index=idx,
                start_ms=int(start * 1000),
                end_ms=int(end * 1000),
                speaker=speaker,
                text=content,
            )
        )
    return segments


def _decode_json_array_tolerant(raw: str) -> list[dict]:
    """Decode as many JSON objects as possible from a JSON array string.

    This supports files where the payload is truncated before the closing
    bracket/string terminator: valid leading items are still returned.
    """
    decoder = json.JSONDecoder()
    out: list[dict] = []
    pos = 1  # skip '['
    length = len(raw)

    while pos < length:
        while pos < length and raw[pos] in " \t\r\n,":
            pos += 1
        if pos >= length or raw[pos] == "]":
            break
        try:
            item, next_pos = decoder.raw_decode(raw, pos)
        except json.JSONDecodeError:
            break
        if isinstance(item, dict):
            out.append(item)
        pos = next_pos

    return out
