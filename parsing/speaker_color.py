from __future__ import annotations

import hashlib


LIGHT_PINK = "#fce7f3"
LIGHT_GREEN = "#dcfce7"
LIGHT_PURPLE = "#ede9fe"

SPEAKER_PALETTE = [
    LIGHT_PINK,
    LIGHT_GREEN,
    LIGHT_PURPLE,
    "#ffedd5",  # orange-100
    "#fef3c7",  # amber-100
    "#cffafe",  # cyan-100
    "#dbeafe",  # blue-100
]


def color_for_speaker(speaker: str, speaker_order: list[str] | None = None) -> str:
    if speaker_order:
        ordered = [s for s in speaker_order if s]
        normalized = (speaker or "Unknown").strip()
        if normalized in ordered:
            idx = ordered.index(normalized)
            if len(ordered) == 2:
                return [LIGHT_PINK, LIGHT_GREEN][idx]
            if len(ordered) >= 3 and idx < 3:
                return [LIGHT_PINK, LIGHT_GREEN, LIGHT_PURPLE][idx]
            return SPEAKER_PALETTE[idx % len(SPEAKER_PALETTE)]

    normalized = (speaker or "Unknown").strip().lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    idx = int(digest[:8], 16) % len(SPEAKER_PALETTE)
    return SPEAKER_PALETTE[idx]
