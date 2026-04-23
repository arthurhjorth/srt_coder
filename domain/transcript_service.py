from __future__ import annotations

from dataclasses import dataclass

from config import INTERVIEW_DATA_DIR
from parsing.srt_parser import TranscriptSegment, parse_srt


@dataclass
class TranscriptDocument:
    source_file: str
    segments: list[TranscriptSegment]
    speakers: list[str]


def list_interview_files() -> list[str]:
    if not INTERVIEW_DATA_DIR.exists():
        return []
    files = [
        p.name
        for p in INTERVIEW_DATA_DIR.iterdir()
        if p.is_file() and p.suffix.lower() == ".srt"
    ]
    return sorted(files, key=str.lower)


def _read_srt_text(filename: str) -> str:
    path = INTERVIEW_DATA_DIR / filename
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Interview file not found: {filename}")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8-sig")


def load_transcript(filename: str) -> TranscriptDocument:
    if filename not in set(list_interview_files()):
        raise FileNotFoundError(f"Interview file is not available: {filename}")

    content = _read_srt_text(filename)
    segments = parse_srt(content)
    speakers = list(dict.fromkeys(seg.speaker for seg in segments if seg.speaker))
    return TranscriptDocument(
        source_file=filename,
        segments=segments,
        speakers=speakers,
    )
