from __future__ import annotations

from typing import Callable
import html

from nicegui import ui

from parsing.srt_parser import TranscriptSegment
from parsing.speaker_color import color_for_speaker


def _format_mm_ss(total_ms: int) -> str:
    total_seconds = max(total_ms // 1000, 0)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def render_transcript_segments(
    segments: list[TranscriptSegment],
    *,
    selected_segment_id: str | None = None,
    coded_segment_ids: set[str] | None = None,
    highlight_ranges: dict[str, list[tuple[int, int]]] | None = None,
    pending_highlight_ranges: dict[str, list[tuple[int, int]]] | None = None,
    on_segment_click: Callable[[TranscriptSegment], None] | None = None,
) -> None:
    if not segments:
        ui.label("No transcript segments found in this file.").classes("text-gray-600")
        return

    coded_segment_ids = coded_segment_ids or set()
    highlight_ranges = highlight_ranges or {}
    pending_highlight_ranges = pending_highlight_ranges or {}
    speaker_order = list(dict.fromkeys(seg.speaker for seg in segments if seg.speaker))

    for seg in segments:
        speaker_color = color_for_speaker(seg.speaker, speaker_order)
        is_selected = selected_segment_id == seg.segment_id
        is_coded = seg.segment_id in coded_segment_ids
        classes = "w-full shadow-sm cursor-pointer"
        if is_selected:
            classes += " ring-2 ring-blue-500"
        elif is_coded:
            classes += " ring-1 ring-emerald-400"

        with ui.card().classes(classes) as card:
            card.style(f"background:{speaker_color};")
            with ui.row().classes("w-full items-center justify-between"):
                ui.label(f"#{seg.index}").classes("text-xs text-gray-500")
                ui.label(
                    f"{_format_mm_ss(seg.start_ms)} - {_format_mm_ss(seg.end_ms)}"
                ).classes("text-xs text-gray-500")
            with ui.row().classes("items-center justify-between"):
                ui.html(
                    (
                        f'<span style="background:{speaker_color};'
                        "padding:2px 8px;border-radius:9999px;font-size:12px;"
                        "font-weight:600;color:#111827;'>"
                        f"{seg.speaker}</span>"
                    )
                )
                if is_coded:
                    ui.label("coded").classes("text-xs text-emerald-700 font-medium")
            marked_html = _render_highlighted_text(
                seg.text,
                highlight_ranges.get(seg.segment_id, []),
                pending_highlight_ranges.get(seg.segment_id, []),
            )
            ui.html(
                (
                    '<div class="segment-text whitespace-pre-wrap leading-6" '
                    f'id="segment-{html.escape(seg.segment_id, quote=True)}" '
                    f'data-segment-id="{html.escape(seg.segment_id, quote=True)}">'
                    f"{marked_html}</div>"
                )
            )
        if on_segment_click is not None:
            card.on("click", lambda _e, s=seg: on_segment_click(s))


def _render_highlighted_text(
    text: str,
    ranges: list[tuple[int, int]],
    pending_ranges: list[tuple[int, int]],
) -> str:
    if not text:
        return ""
    if not ranges and not pending_ranges:
        return html.escape(text)

    n = len(text)
    mark = [0] * n  # 0 none, 1 saved, 2 pending (takes precedence)

    normalized: list[tuple[int, int, int]] = []
    n = len(text)
    for start, end in ranges:
        s = max(0, min(n, int(start)))
        e = max(0, min(n, int(end)))
        if e <= s:
            continue
        normalized.append((s, e, 1))
    for start, end in pending_ranges:
        s = max(0, min(n, int(start)))
        e = max(0, min(n, int(end)))
        if e <= s:
            continue
        normalized.append((s, e, 2))
    if not normalized:
        return html.escape(text)

    for s, e, kind in normalized:
        for i in range(s, e):
            if kind == 2 or mark[i] == 0:
                mark[i] = kind

    out: list[str] = []
    i = 0
    while i < n:
        kind = mark[i]
        j = i + 1
        while j < n and mark[j] == kind:
            j += 1
        chunk = html.escape(text[i:j])
        if kind == 1:
            out.append(f'<mark style="font-weight:700;">{chunk}</mark>')
        elif kind == 2:
            out.append(
                '<span style="background:#dbeafe;padding:0 1px;border-radius:2px;font-weight:700;">'
                f"{chunk}</span>"
            )
        else:
            out.append(chunk)
        i = j
    return "".join(out)
