from __future__ import annotations

import asyncio
from collections.abc import Callable
import time

from nicegui import ui

from auth.service import current_username, require_auth_or_redirect
from auth.views import top_nav
from domain.analysis_service import get_analysis
from domain.coding_service import (
    create_object_entry,
    delete_entry,
    list_entries_for_analysis_and_file,
    update_entry_payload,
)
from domain.transcript_service import load_transcript
from models import (
    CodingEntry,
    ComparatorDetail,
    Comparison,
    ConditionAntecedentReason,
    Differentiation,
    Nuance,
    Perspective,
)
from parsing.srt_parser import TranscriptSegment
from state.session_state import set_selected_analysis_id, set_selected_interview_file
from ui.components.transcript_view import render_transcript_segments


FIELD_LABELS = {
    "thing_being_considered_extract": "Thing being considered",
    "context_why_is_this_thing_being_considered_or_talked_about_extract": "Context: why considered or discussed",
    "why_is_it_important_extract": "Why is it important?",
    "why_is_this_a_thing_extract": "Why is this a thing?",
    "different_perspectives_or_dimensions_extract": "Different perspectives or dimensions",
    "why_is_it_important_to_take_different_perspectives_extract": "Why important to take different perspectives?",
    "what_is_wrong_with_taking_a_unitary_perspective_extract": "What is wrong with a unitary perspective?",
    "perspectives_extract": "Perspectives",
    "what_is_this_perspective_extract": "What is this perspective?",
    "why_is_it_relevant_to_take_this_perspective_extract": "Why is this perspective relevant?",
    "how_does_this_particular_perspective_add_complexity_or_difficulty_to_the_thing_being_considered_extract": "How does this perspective add complexity/difficulty?",
    "what_are_the_implications_extract": "Implications",
    "outcome_something_that_can_happen_or_has_happened_event_something_that_can_be_or_is_the_case_state_extract": "Outcome / event / state",
    "certitude_about_outcome_or_epistemic_modality_does_the_person_say_that_this_will_happen_or_could_it_happen_or_might_it_happen_extract": "Certitude / epistemic modality",
    "epistemic_stance_extract": "Epistemic stance",
    "negation_or_not_extract": "Negation",
    "stance_does_the_person_want_this_or_does_the_person_not_want_this_extract": "Stance (wants / does not want)",
    "condition_antecedent_reason_extract": "Condition / antecedent reason",
    "condition_antecedent_reason": "Condition antecedent reasons",
    "sufficiency_does_person_state_that_these_are_sufficient_conditions_extract": "Sufficiency of conditions",
    "description_an_event_or_state_that_contributes_or_contributed_towards_increasing_the_likelihood_of_the_outcome_or_towards_explaining_why_it_happened_extract": "Condition description",
    "direction_of_impact_increase_or_decrease_the_likelihood_extract": "Direction of impact",
    "reasoning_of_impact_in_what_ways_would_this_contribute_towards_the_likelihood_of_the_outcome_extract": "Reasoning of impact",
    "certitude_about_impact_how_likely_is_this_condition_to_impact_the_likelihood_of_the_outcome_extract": "Certitude about impact",
    "comparand": "Comparand",
    "comparators": "Comparators",
    "comparator": "Comparator",
    "adjective": "Adjective",
    "dimensions_or_examples": "Dimensions or examples",
}


def _display_name(field_name: str) -> str:
    if field_name.endswith("_comment"):
        base = field_name[:-8]
        return f"{FIELD_LABELS.get(base, base.replace('_', ' ').title())} comment"
    return FIELD_LABELS.get(field_name, field_name.replace("_", " ").title())


def render_analysis_page(analysis_id: str) -> None:
    if not require_auth_or_redirect():
        return

    analysis = get_analysis(analysis_id)
    if analysis is None or not analysis.interview_file:
        top_nav()
        with ui.column().classes("w-full max-w-3xl mx-auto mt-8 gap-3"):
            ui.label("Analysis not found").classes("text-2xl font-semibold")
            ui.label("This analysis id does not exist.")
            ui.button("Back to interview list", on_click=lambda: ui.navigate.to("/"))
        return

    selected_file = analysis.interview_file
    set_selected_analysis_id(analysis_id)
    set_selected_interview_file(selected_file)

    top_nav()
    _install_selection_cache_script()

    with ui.column().classes("w-full max-w-[1800px] mx-auto mt-6 gap-3"):
        ui.button("Back to interview list", on_click=lambda: ui.navigate.to("/")).props("flat")
        ui.label("Analysis Workspace").classes("text-2xl font-semibold")
        ui.label(f"Analysis: {analysis.name or analysis.analysis_id}").classes("text-sm text-gray-700")
        ui.label(f"Interview file: {selected_file}").classes("text-sm text-gray-700")

        status_label = ui.label("").classes("text-sm text-gray-700")
        count_label = ui.label("Objects in this analysis: 0").classes("text-sm text-gray-700")

        state: dict = {
            "transcript": None,
            "entries": [],
            "pending_span": None,
            "pending_span_sig": None,
            "selection_revision_seen": -1,
        }

        with ui.row().classes("w-full items-start no-wrap gap-4"):
            left_col = ui.column().classes("w-1/3 gap-2")
            right_col = ui.column().classes("w-2/3 gap-2")

        with left_col:
            transcript_scroll = ui.scroll_area().classes("w-full h-[72vh] border rounded p-3 bg-gray-50")

        with right_col:
            with ui.row().classes("w-full flex-wrap gap-2"):
                ui.button("New Differentiation", on_click=lambda: _create_object("differentiation"))
                ui.button("New Comparison", on_click=lambda: _create_object("comparison"))
                ui.button("New Nuance", on_click=lambda: _create_object("nuance"))
            objects_scroll = ui.scroll_area().classes("w-full h-[72vh] border rounded p-3 bg-gray-50")
            with objects_scroll:
                objects_container = ui.column().classes("w-full gap-3")

        def _refresh_entries() -> None:
            entries = list_entries_for_analysis_and_file(
                analysis_id=analysis_id,
                interview_file=selected_file,
            )
            entries.sort(key=lambda x: x.created_at or "")
            state["entries"] = entries
            count_label.set_text(f"Objects in this analysis: {len(entries)}")

        def _replace_entry(updated: CodingEntry) -> None:
            updated_entries: list[CodingEntry] = []
            replaced = False
            for entry in state["entries"]:
                if entry.coding_id == updated.coding_id:
                    updated_entries.append(updated)
                    replaced = True
                else:
                    updated_entries.append(entry)
            if not replaced:
                updated_entries.append(updated)
            state["entries"] = updated_entries

        def _count_spans_for_key(entry: CodingEntry, span_key: str) -> int:
            spans = (entry.field_spans or {}).get(span_key) or []
            return len(spans)

        def _count_total_spans(entry: CodingEntry) -> int:
            total = 0
            for spans in (entry.field_spans or {}).values():
                total += len(spans or [])
            if (
                entry.start_segment_id
                and entry.end_segment_id
                and entry.start_char_offset is not None
                and entry.end_char_offset is not None
            ):
                total += 1
            return total

        def _has_data(value) -> bool:
            if value is None:
                return False
            if hasattr(value, "model_dump"):
                return _has_data(value.model_dump())
            if isinstance(value, str):
                return bool(value.strip())
            if isinstance(value, (int, float, bool)):
                return True
            if isinstance(value, dict):
                return any(_has_data(v) for v in value.values())
            if isinstance(value, (list, tuple, set)):
                return any(_has_data(v) for v in value)
            return bool(value)

        def _is_entry_empty(entry: CodingEntry) -> bool:
            kind = (entry.object_type or "").lower()
            payload = None
            if kind in {"differentiation", "consider"}:
                payload = entry.differentiation
            elif kind == "nuance":
                payload = entry.nuance
            elif kind == "comparison":
                payload = entry.comparison
            else:
                payload = entry.differentiation or entry.nuance or entry.comparison
            return (
                not _has_data(payload)
                and not _has_data(entry.note)
                and _count_total_spans(entry) == 0
            )

        def _delete_entry_now(entry: CodingEntry) -> None:
            try:
                removed = delete_entry(
                    analysis_id=analysis_id,
                    coding_id=entry.coding_id or "",
                )
            except Exception as exc:
                status_label.set_text(f"Delete failed: {exc}")
                return
            if not removed:
                status_label.set_text("Delete failed: object not found.")
                return
            state["entries"] = [
                e for e in state["entries"] if e.coding_id != entry.coding_id
            ]
            _refresh_entries()
            _refresh_transcript()
            _render_objects()
            status_label.set_text("Object deleted.")

        def _request_delete_entry(entry: CodingEntry, object_name: str) -> None:
            if _is_entry_empty(entry):
                _delete_entry_now(entry)
                return
            span_count = _count_total_spans(entry)
            dialog = ui.dialog()
            with dialog, ui.card().classes("w-[520px]"):
                ui.label("Confirm deletion").classes("text-lg font-semibold")
                ui.label(
                    f"Are you sure you want to delete this {object_name}? "
                    f"It will delete everything in the {object_name}, including "
                    f"{span_count} text selections/spans."
                ).classes("text-sm text-gray-700")
                with ui.row().classes("justify-end gap-2"):
                    ui.button("Cancel", on_click=dialog.close).props("flat")
                    ui.button(
                        "Delete",
                        on_click=lambda: (dialog.close(), _delete_entry_now(entry)),
                    ).props("color=negative")
            dialog.open()

        def _persist_models(
            entry: CodingEntry,
            *,
            comparison: Comparison | None,
            differentiation: Differentiation | None,
            nuance: Nuance | None,
            field_spans: dict[str, list[dict]] | None,
            note: str | None = None,
        ) -> CodingEntry:
            updated = update_entry_payload(
                analysis_id=analysis_id,
                coding_id=entry.coding_id or "",
                object_type=entry.object_type,
                comparison=comparison,
                differentiation=differentiation,
                nuance=nuance,
                note=note if note is not None else entry.note,
                field_spans=field_spans,
            )
            _replace_entry(updated)
            _refresh_transcript()
            _render_objects()
            return updated

        async def _append_selection_to_field(
            entry: CodingEntry,
            *,
            span_key: str,
            mutator: Callable[[Comparison | None, Differentiation | None, Nuance | None, str], None],
        ) -> None:
            transcript = state["transcript"]
            if transcript is None:
                return
            cached = await ui.run_javascript("window.__srt_last_selection || null")
            if not cached:
                return
            normalized = _normalize_span_selection(transcript.segments, cached)
            if normalized is None:
                return
            selected_text = (normalized.get("selected_text") or "").strip()
            if not selected_text:
                selected_text = _extract_text_for_span(
                    transcript.segments,
                    normalized["start_segment_id"],
                    normalized["start_char_offset"],
                    normalized["end_segment_id"],
                    normalized["end_char_offset"],
                )
            selected_text = (selected_text or "").strip()
            if not selected_text:
                return

            comparison = entry.comparison.model_copy(deep=True) if entry.comparison else None
            differentiation = (
                entry.differentiation.model_copy(deep=True) if entry.differentiation else None
            )
            nuance = entry.nuance.model_copy(deep=True) if entry.nuance else None
            kind = (entry.object_type or "").lower()
            if kind == "comparison" and comparison is None:
                comparison = Comparison()
            if kind in {"differentiation", "consider"} and differentiation is None:
                differentiation = Differentiation()
            if kind == "nuance" and nuance is None:
                nuance = Nuance()

            mutator(comparison, differentiation, nuance, selected_text)

            spans = {k: list(v) for k, v in (entry.field_spans or {}).items()}
            spans.setdefault(span_key, []).append(
                {
                    "start_segment_id": normalized["start_segment_id"],
                    "start_char_offset": normalized["start_char_offset"],
                    "end_segment_id": normalized["end_segment_id"],
                    "end_char_offset": normalized["end_char_offset"],
                    "selected_text": selected_text,
                }
            )

            _persist_models(
                entry,
                comparison=comparison,
                differentiation=differentiation,
                nuance=nuance,
                field_spans=spans,
            )
            state["pending_span"] = None
            state["pending_span_sig"] = None
            await ui.run_javascript(
                """
                window.__srt_last_selection = null;
                window.__srt_selection_revision = (window.__srt_selection_revision || 0) + 1;
                """
            )
            _refresh_transcript()
            status_label.set_text(f"Appended span to {span_key}")

        def _refresh_transcript() -> None:
            transcript_scroll.clear()
            transcript = state["transcript"]
            with transcript_scroll:
                if transcript is None:
                    ui.label("No transcript loaded.").classes("text-gray-600")
                    return
                highlight_ranges = _build_highlight_ranges(
                    transcript.segments,
                    state["entries"],
                )
                pending_ranges = _build_highlight_ranges(
                    transcript.segments,
                    [],
                    pending_span=state["pending_span"],
                )
                render_transcript_segments(
                    transcript.segments,
                    selected_segment_id=None,
                    coded_segment_ids=set(highlight_ranges.keys()),
                    highlight_ranges=highlight_ranges,
                    pending_highlight_ranges=pending_ranges,
                    on_segment_click=None,
                )

        def _create_object(object_type: str) -> None:
            try:
                created = create_object_entry(
                    analysis_id=analysis_id,
                    interview_file=selected_file,
                    object_type=object_type,
                    created_by=current_username() or "unknown",
                )
            except ValueError as exc:
                status_label.set_text(str(exc))
                return
            _replace_entry(created)
            _refresh_entries()
            _refresh_transcript()
            _render_objects()
            status_label.set_text(f"Created new {object_type} object")

        def _bind_span_append(
            element,
            entry: CodingEntry,
            *,
            span_key: str,
            mutator: Callable[[Comparison | None, Differentiation | None, Nuance | None, str], None],
            enable_field_jump: bool = False,
        ) -> None:
            async def _on_mouse_down(_e) -> None:
                await _append_selection_to_field(entry, span_key=span_key, mutator=mutator)

            async def _on_click(_e) -> None:
                await _jump_to_field_span(entry, span_key)

            element.on("mousedown", _on_mouse_down)
            if enable_field_jump:
                element.on("click", _on_click)

        async def _jump_to_field_span(entry: CodingEntry, span_key: str) -> None:
            spans = (entry.field_spans or {}).get(span_key) or []
            if not spans:
                return
            target = spans[-1]
            segment_id = target.get("start_segment_id")
            if not segment_id:
                return
            segment_id_js = str(segment_id).replace("\\", "\\\\").replace('"', '\\"')
            await ui.run_javascript(
                f"""
                (() => {{
                  const el = document.getElementById("segment-{segment_id_js}");
                  if (!el) return;
                  el.scrollIntoView({{ behavior: "smooth", block: "center" }});
                  const prev = el.style.boxShadow;
                  el.style.boxShadow = "0 0 0 2px #60a5fa inset";
                  setTimeout(() => {{
                    el.style.boxShadow = prev;
                  }}, 900);
                }})();
                """
            )

        async def _jump_to_specific_span(span: dict) -> None:
            segment_id = span.get("start_segment_id")
            if not segment_id:
                return
            segment_id_js = str(segment_id).replace("\\", "\\\\").replace('"', '\\"')
            await ui.run_javascript(
                f"""
                (() => {{
                  const el = document.getElementById("segment-{segment_id_js}");
                  if (!el) return;
                  el.scrollIntoView({{ behavior: "smooth", block: "center" }});
                  const prev = el.style.boxShadow;
                  el.style.boxShadow = "0 0 0 2px #60a5fa inset";
                  setTimeout(() => {{
                    el.style.boxShadow = prev;
                  }}, 900);
                }})();
                """
            )

        def _bind_span_jump(element, span: dict) -> None:
            async def _on_click(_e=None) -> None:
                await _jump_to_specific_span(span)
            # stop bubbling to avoid accidental parent interactions
            element.on("mousedown.stop", lambda _e: None)
            element.on("click.stop", _on_click)

        def _render_field_spans(entry: CodingEntry, span_key: str, *, inside_box: bool = False) -> int:
            spans = (entry.field_spans or {}).get(span_key) or []
            if not spans:
                return 0
            if not inside_box:
                ui.label(f"Spans ({len(spans)})").classes("text-[11px] text-gray-600")
            for idx, span in enumerate(spans, start=1):
                text = (span.get("selected_text") or "").strip() or "(empty)"
                snippet = text if len(text) <= 220 else text[:220] + "..."
                box = ui.element("div").classes(
                    (
                        "w-full border rounded px-2 py-1 text-xs bg-white/80 cursor-pointer whitespace-pre-wrap "
                        if inside_box
                        else "w-full border rounded px-2 py-1 text-xs bg-white cursor-pointer whitespace-pre-wrap"
                    )
                )
                with box:
                    ui.label(f"{idx}. {snippet}").classes("whitespace-pre-wrap")
                _bind_span_jump(box, span)
            return len(spans)

        def _render_locked_field(
            *,
            label: str,
            value: str | None,
            entry: CodingEntry,
            span_key: str,
            mutator: Callable[[Comparison | None, Differentiation | None, Nuance | None, str], None],
            on_clear: Callable[[], None] | None = None,
        ) -> None:
            with ui.row().classes("w-full items-center justify-between"):
                ui.label(label).classes("text-xs text-gray-700")
                if on_clear is not None:
                    _render_hold_to_clear_button(on_clear)
            box = ui.element("div").classes(
                "w-full min-h-[42px] border rounded px-3 py-2 bg-gray-100 text-gray-900 whitespace-pre-wrap"
            )
            span_count = _count_spans_for_key(entry, span_key)
            with box:
                if span_count > 0:
                    _render_field_spans(entry, span_key, inside_box=True)

                add_box = ui.element("div").classes(
                    "w-full min-h-[34px] border border-dashed rounded mt-2 px-2 py-2 bg-white/70 cursor-pointer"
                )
                with add_box:
                    # Keep this visually empty by default, while preserving fixed clickable area.
                    ui.label(" ").classes("whitespace-pre-wrap")
                _bind_span_append(
                    add_box,
                    entry=entry,
                    span_key=span_key,
                    mutator=mutator,
                    enable_field_jump=False,
                )

        def _render_comment_field(
            *,
            label: str,
            value: str | None,
            on_save: Callable[[str | None], None],
            entry: CodingEntry,
            span_key: str,
            mutator: Callable[[Comparison | None, Differentiation | None, Nuance | None, str], None],
        ) -> None:
            with ui.row().classes("w-full items-center justify-between"):
                ui.label(label).classes("text-xs text-gray-700")
            cmt = ui.input().classes("w-full")
            cmt.set_value(value or "")
            cmt.on("blur", lambda _e, el=cmt: on_save(el.value))
            _bind_span_append(
                cmt,
                entry=entry,
                span_key=span_key,
                mutator=mutator,
                enable_field_jump=False,
            )
            _render_field_spans(entry, span_key)

        def _render_hold_to_clear_button(on_clear: Callable[[], None]) -> None:
            with ui.element("div").classes("relative inline-flex items-stretch overflow-hidden rounded"):
                fill = ui.element("div").classes("absolute left-0 top-0 h-full bg-red-300")
                fill.style("width:0%;pointer-events:none;")
                btn = ui.button("Hold 1.2s to clear").props("outline dense color=negative")
                btn.classes("relative z-10")
                btn.style("background:transparent;")

            state_hold = {"pressed": False, "token": 0}

            def _reset_visual() -> None:
                fill.style("width:0%;pointer-events:none;")
                btn.set_text("Hold 1.2s to clear")

            async def _run_hold_progress(token: int) -> None:
                started = time.monotonic()
                while state_hold["pressed"] and state_hold["token"] == token:
                    elapsed = time.monotonic() - started
                    progress = max(0.0, min(1.0, elapsed / 1.2))
                    remaining = max(0.0, 1.2 - elapsed)
                    fill.style(f"width:{progress * 100:.1f}%;pointer-events:none;")
                    btn.set_text(f"Hold {remaining:.1f}s to clear")
                    if progress >= 1.0:
                        state_hold["pressed"] = False
                        on_clear()
                        _reset_visual()
                        return
                    await asyncio.sleep(0.05)
                _reset_visual()

            def _start(_e=None) -> None:
                state_hold["pressed"] = True
                state_hold["token"] += 1
                asyncio.create_task(_run_hold_progress(state_hold["token"]))

            def _stop(_e=None) -> None:
                state_hold["pressed"] = False

            btn.on("mousedown", _start)
            btn.on("mouseup", _stop)
            btn.on("mouseleave", _stop)
            btn.on("touchstart", _start)
            btn.on("touchend", _stop)

        def _render_differentiation_card(entry: CodingEntry) -> None:
            differentiation = (
                entry.differentiation.model_copy(deep=True)
                if entry.differentiation
                else Differentiation()
            )

            def save_field(name: str, value: str | None) -> None:
                setattr(differentiation, name, (value or "").strip() or None)
                _persist_models(
                    entry,
                    comparison=entry.comparison,
                    differentiation=differentiation,
                    nuance=entry.nuance,
                    field_spans=entry.field_spans or {},
                )

            def clear_field(name: str) -> None:
                setattr(differentiation, name, None)
                spans = {k: list(v) for k, v in (entry.field_spans or {}).items()}
                spans.pop(f"differentiation.{name}", None)
                _persist_models(
                    entry,
                    comparison=entry.comparison,
                    differentiation=differentiation,
                    nuance=entry.nuance,
                    field_spans=spans,
                )

            def clear_perspective_field(index: int, name: str) -> None:
                rows = list(differentiation.perspectives_extract or [])
                while len(rows) <= index:
                    rows.append(Perspective())
                setattr(rows[index], name, None)
                differentiation.perspectives_extract = rows
                spans = {k: list(v) for k, v in (entry.field_spans or {}).items()}
                spans.pop(f"differentiation.perspectives_extract[{index}].{name}", None)
                _persist_models(
                    entry,
                    comparison=entry.comparison,
                    differentiation=differentiation,
                    nuance=entry.nuance,
                    field_spans=spans,
                )

            def _render_text_field(field: str) -> None:
                comment_field = f"{field}_comment"
                _render_locked_field(
                    label=_display_name(field),
                    value=getattr(differentiation, field),
                    entry=entry,
                    span_key=f"differentiation.{field}",
                    on_clear=lambda f=field: clear_field(f),
                    mutator=lambda _cmp, dif, _nua, text, f=field: setattr(
                        dif,
                        f,
                        _append_text(getattr(dif, f), text),
                    ),
                )
                _render_comment_field(
                    label=_display_name(comment_field),
                    value=getattr(differentiation, comment_field),
                    on_save=lambda v, f=comment_field: save_field(f, v),
                    entry=entry,
                    span_key=f"differentiation.{comment_field}",
                    mutator=lambda _cmp, dif, _nua, text, f=comment_field: setattr(
                        dif,
                        f,
                        _append_text(getattr(dif, f), text),
                    ),
                )

            def add_perspective() -> None:
                rows = list(differentiation.perspectives_extract or [])
                rows.append(Perspective())
                differentiation.perspectives_extract = rows
                _persist_models(
                    entry,
                    comparison=entry.comparison,
                    differentiation=differentiation,
                    nuance=entry.nuance,
                    field_spans=entry.field_spans or {},
                )

            def remove_perspective(index: int) -> None:
                rows = list(differentiation.perspectives_extract or [])
                if 0 <= index < len(rows):
                    rows.pop(index)
                differentiation.perspectives_extract = rows or None
                _persist_models(
                    entry,
                    comparison=entry.comparison,
                    differentiation=differentiation,
                    nuance=entry.nuance,
                    field_spans=entry.field_spans or {},
                )

            def save_perspective_field(index: int, name: str, value: str | None) -> None:
                rows = list(differentiation.perspectives_extract or [])
                while len(rows) <= index:
                    rows.append(Perspective())
                setattr(rows[index], name, (value or "").strip() or None)
                differentiation.perspectives_extract = rows
                _persist_models(
                    entry,
                    comparison=entry.comparison,
                    differentiation=differentiation,
                    nuance=entry.nuance,
                    field_spans=entry.field_spans or {},
                )

            with ui.card().classes("w-full shadow-sm"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("Differentiation").classes("text-lg font-semibold")
                    ui.button(
                        "Delete object",
                        on_click=lambda: _request_delete_entry(entry, "differentiation"),
                    ).props("outline color=negative")
                ui.label(f"ID: {entry.coding_id}").classes("text-xs text-gray-500")

                for field in [
                    "thing_being_considered_extract",
                    "context_why_is_this_thing_being_considered_or_talked_about_extract",
                    "why_is_it_important_extract",
                    "why_is_this_a_thing_extract",
                    "different_perspectives_or_dimensions_extract",
                    "why_is_it_important_to_take_different_perspectives_extract",
                    "what_is_wrong_with_taking_a_unitary_perspective_extract",
                ]:
                    _render_text_field(field)

                ui.separator()
                ui.label(_display_name("perspectives_extract")).classes("text-sm font-medium")
                rows = list(differentiation.perspectives_extract or [])
                for idx, row in enumerate(rows):
                    with ui.card().classes("w-full border shadow-none"):
                        ui.label(f"Perspective {idx + 1}").classes("text-sm font-semibold")
                        for field in [
                            "what_is_this_perspective_extract",
                            "why_is_it_relevant_to_take_this_perspective_extract",
                            "how_does_this_particular_perspective_add_complexity_or_difficulty_to_the_thing_being_considered_extract",
                            "what_are_the_implications_extract",
                        ]:
                            _render_locked_field(
                                label=_display_name(field),
                                value=getattr(row, field),
                                entry=entry,
                                span_key=f"differentiation.perspectives_extract[{idx}].{field}",
                                on_clear=lambda i=idx, f=field: clear_perspective_field(i, f),
                                mutator=lambda _cmp, dif, _nua, text, i=idx, f=field: _append_to_perspective_field(
                                    dif,
                                    i,
                                    f,
                                    text,
                                ),
                            )

                            cmt_field = f"{field}_comment"
                            _render_comment_field(
                                label=_display_name(cmt_field),
                                value=getattr(row, cmt_field),
                                on_save=lambda v, i=idx, f=cmt_field: save_perspective_field(i, f, v),
                                entry=entry,
                                span_key=f"differentiation.perspectives_extract[{idx}].{cmt_field}",
                                mutator=lambda _cmp, dif, _nua, text, i=idx, f=cmt_field: _append_to_perspective_field(
                                    dif,
                                    i,
                                    f,
                                    text,
                                ),
                            )

                        ui.button("Remove perspective", on_click=lambda _e, i=idx: remove_perspective(i)).props("flat")

                ui.button("New perspective", on_click=add_perspective).props("outline")
                _render_comment_field(
                    label=_display_name("perspectives_extract_comment"),
                    value=differentiation.perspectives_extract_comment,
                    on_save=lambda v: save_field("perspectives_extract_comment", v),
                    entry=entry,
                    span_key="differentiation.perspectives_extract_comment",
                    mutator=lambda _cmp, dif, _nua, text: setattr(
                        dif,
                        "perspectives_extract_comment",
                        _append_text(dif.perspectives_extract_comment, text),
                    ),
                )

        def _render_nuance_card(entry: CodingEntry) -> None:
            nuance = entry.nuance.model_copy(deep=True) if entry.nuance else Nuance()

            def save_field(name: str, value: str | None) -> None:
                setattr(nuance, name, (value or "").strip() or None)
                _persist_models(
                    entry,
                    comparison=entry.comparison,
                    differentiation=entry.differentiation,
                    nuance=nuance,
                    field_spans=entry.field_spans or {},
                )

            def clear_field(name: str) -> None:
                setattr(nuance, name, None)
                spans = {k: list(v) for k, v in (entry.field_spans or {}).items()}
                spans.pop(f"nuance.{name}", None)
                _persist_models(
                    entry,
                    comparison=entry.comparison,
                    differentiation=entry.differentiation,
                    nuance=nuance,
                    field_spans=spans,
                )

            def clear_condition_field(index: int, name: str) -> None:
                rows = list(nuance.condition_antecedent_reason or [])
                while len(rows) <= index:
                    rows.append(ConditionAntecedentReason())
                setattr(rows[index], name, None)
                nuance.condition_antecedent_reason = rows
                spans = {k: list(v) for k, v in (entry.field_spans or {}).items()}
                spans.pop(f"nuance.condition_antecedent_reason[{index}].{name}", None)
                _persist_models(
                    entry,
                    comparison=entry.comparison,
                    differentiation=entry.differentiation,
                    nuance=nuance,
                    field_spans=spans,
                )

            def _render_text_field(field: str) -> None:
                comment_field = f"{field}_comment"
                _render_locked_field(
                    label=_display_name(field),
                    value=getattr(nuance, field),
                    entry=entry,
                    span_key=f"nuance.{field}",
                    on_clear=lambda f=field: clear_field(f),
                    mutator=lambda _cmp, _dif, nua, text, f=field: setattr(
                        nua,
                        f,
                        _append_text(getattr(nua, f), text),
                    ),
                )
                _render_comment_field(
                    label=_display_name(comment_field),
                    value=getattr(nuance, comment_field),
                    on_save=lambda v, f=comment_field: save_field(f, v),
                    entry=entry,
                    span_key=f"nuance.{comment_field}",
                    mutator=lambda _cmp, _dif, nua, text, f=comment_field: setattr(
                        nua,
                        f,
                        _append_text(getattr(nua, f), text),
                    ),
                )

            def add_condition() -> None:
                rows = list(nuance.condition_antecedent_reason or [])
                rows.append(ConditionAntecedentReason())
                nuance.condition_antecedent_reason = rows
                _persist_models(
                    entry,
                    comparison=entry.comparison,
                    differentiation=entry.differentiation,
                    nuance=nuance,
                    field_spans=entry.field_spans or {},
                )

            def remove_condition(index: int) -> None:
                rows = list(nuance.condition_antecedent_reason or [])
                if 0 <= index < len(rows):
                    rows.pop(index)
                nuance.condition_antecedent_reason = rows or None
                _persist_models(
                    entry,
                    comparison=entry.comparison,
                    differentiation=entry.differentiation,
                    nuance=nuance,
                    field_spans=entry.field_spans or {},
                )

            def save_condition_field(index: int, name: str, value: str | None) -> None:
                rows = list(nuance.condition_antecedent_reason or [])
                while len(rows) <= index:
                    rows.append(ConditionAntecedentReason())
                setattr(rows[index], name, (value or "").strip() or None)
                nuance.condition_antecedent_reason = rows
                _persist_models(
                    entry,
                    comparison=entry.comparison,
                    differentiation=entry.differentiation,
                    nuance=nuance,
                    field_spans=entry.field_spans or {},
                )

            with ui.card().classes("w-full shadow-sm"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("Nuance").classes("text-lg font-semibold")
                    ui.button(
                        "Delete object",
                        on_click=lambda: _request_delete_entry(entry, "nuance"),
                    ).props("outline color=negative")
                ui.label(f"ID: {entry.coding_id}").classes("text-xs text-gray-500")

                for field in [
                    "outcome_something_that_can_happen_or_has_happened_event_something_that_can_be_or_is_the_case_state_extract",
                    "certitude_about_outcome_or_epistemic_modality_does_the_person_say_that_this_will_happen_or_could_it_happen_or_might_it_happen_extract",
                    "epistemic_stance_extract",
                    "negation_or_not_extract",
                    "stance_does_the_person_want_this_or_does_the_person_not_want_this_extract",
                    "condition_antecedent_reason_extract",
                    "sufficiency_does_person_state_that_these_are_sufficient_conditions_extract",
                ]:
                    _render_text_field(field)

                ui.separator()
                ui.label(_display_name("condition_antecedent_reason")).classes("text-sm font-medium")
                rows = list(nuance.condition_antecedent_reason or [])
                for idx, row in enumerate(rows):
                    with ui.card().classes("w-full border shadow-none"):
                        ui.label(f"Condition antecedent reason {idx + 1}").classes("text-sm font-semibold")
                        for field in [
                            "description_an_event_or_state_that_contributes_or_contributed_towards_increasing_the_likelihood_of_the_outcome_or_towards_explaining_why_it_happened_extract",
                            "direction_of_impact_increase_or_decrease_the_likelihood_extract",
                            "reasoning_of_impact_in_what_ways_would_this_contribute_towards_the_likelihood_of_the_outcome_extract",
                            "certitude_about_impact_how_likely_is_this_condition_to_impact_the_likelihood_of_the_outcome_extract",
                            "epistemic_stance_extract",
                        ]:
                            _render_locked_field(
                                label=_display_name(field),
                                value=getattr(row, field),
                                entry=entry,
                                span_key=f"nuance.condition_antecedent_reason[{idx}].{field}",
                                on_clear=lambda i=idx, f=field: clear_condition_field(i, f),
                                mutator=lambda _cmp, _dif, nua, text, i=idx, f=field: _append_to_condition_field(
                                    nua,
                                    i,
                                    f,
                                    text,
                                ),
                            )

                            cmt_field = f"{field}_comment"
                            _render_comment_field(
                                label=_display_name(cmt_field),
                                value=getattr(row, cmt_field),
                                on_save=lambda v, i=idx, f=cmt_field: save_condition_field(i, f, v),
                                entry=entry,
                                span_key=f"nuance.condition_antecedent_reason[{idx}].{cmt_field}",
                                mutator=lambda _cmp, _dif, nua, text, i=idx, f=cmt_field: _append_to_condition_field(
                                    nua,
                                    i,
                                    f,
                                    text,
                                ),
                            )

                        ui.button("Remove condition antecedent reason", on_click=lambda _e, i=idx: remove_condition(i)).props("flat")

                ui.button("New condition antecedent reason", on_click=add_condition).props("outline")
                _render_comment_field(
                    label=_display_name("condition_antecedent_reason_comment"),
                    value=nuance.condition_antecedent_reason_comment,
                    on_save=lambda v: save_field("condition_antecedent_reason_comment", v),
                    entry=entry,
                    span_key="nuance.condition_antecedent_reason_comment",
                    mutator=lambda _cmp, _dif, nua, text: setattr(
                        nua,
                        "condition_antecedent_reason_comment",
                        _append_text(nua.condition_antecedent_reason_comment, text),
                    ),
                )

        def _ensure_comparator(cmp: Comparison, index: int) -> ComparatorDetail:
            rows = list(cmp.comparators or [])
            while len(rows) <= index:
                rows.append(ComparatorDetail())
            cmp.comparators = rows
            return rows[index]

        def _render_comparison_card(entry: CodingEntry) -> None:
            comparison = entry.comparison.model_copy(deep=True) if entry.comparison else Comparison()

            def save_top_field(name: str, value: str | None) -> None:
                setattr(comparison, name, (value or "").strip() or None)
                _persist_models(
                    entry,
                    comparison=comparison,
                    differentiation=entry.differentiation,
                    nuance=entry.nuance,
                    field_spans=entry.field_spans or {},
                )

            def clear_top_field(name: str) -> None:
                setattr(comparison, name, None)
                spans = {k: list(v) for k, v in (entry.field_spans or {}).items()}
                spans.pop(f"comparison.{name}", None)
                _persist_models(
                    entry,
                    comparison=comparison,
                    differentiation=entry.differentiation,
                    nuance=entry.nuance,
                    field_spans=spans,
                )

            def save_comparator_field(index: int, field_name: str, value: str | None) -> None:
                row = _ensure_comparator(comparison, index)
                setattr(row, field_name, (value or "").strip() or None)
                _persist_models(
                    entry,
                    comparison=comparison,
                    differentiation=entry.differentiation,
                    nuance=entry.nuance,
                    field_spans=entry.field_spans or {},
                )

            def clear_comparator_field(index: int, field_name: str) -> None:
                row = _ensure_comparator(comparison, index)
                setattr(row, field_name, None)
                spans = {k: list(v) for k, v in (entry.field_spans or {}).items()}
                spans.pop(f"comparison.comparators[{index}].{field_name}", None)
                _persist_models(
                    entry,
                    comparison=comparison,
                    differentiation=entry.differentiation,
                    nuance=entry.nuance,
                    field_spans=spans,
                )

            def add_comparator() -> None:
                rows = list(comparison.comparators or [])
                rows.append(ComparatorDetail())
                comparison.comparators = rows
                _persist_models(
                    entry,
                    comparison=comparison,
                    differentiation=entry.differentiation,
                    nuance=entry.nuance,
                    field_spans=entry.field_spans or {},
                )

            def remove_comparator(index: int) -> None:
                rows = list(comparison.comparators or [])
                if 0 <= index < len(rows):
                    rows.pop(index)
                comparison.comparators = rows or None
                _persist_models(
                    entry,
                    comparison=comparison,
                    differentiation=entry.differentiation,
                    nuance=entry.nuance,
                    field_spans=entry.field_spans or {},
                )

            def add_dimension(index: int) -> None:
                row = _ensure_comparator(comparison, index)
                dims = list(row.dimensions_or_examples or [])
                dims.append("")
                row.dimensions_or_examples = dims
                _persist_models(
                    entry,
                    comparison=comparison,
                    differentiation=entry.differentiation,
                    nuance=entry.nuance,
                    field_spans=entry.field_spans or {},
                )

            def update_dimension(index: int, dim_index: int, value: str | None) -> None:
                row = _ensure_comparator(comparison, index)
                dims = list(row.dimensions_or_examples or [])
                while len(dims) <= dim_index:
                    dims.append("")
                dims[dim_index] = (value or "").strip()
                row.dimensions_or_examples = dims
                _persist_models(
                    entry,
                    comparison=comparison,
                    differentiation=entry.differentiation,
                    nuance=entry.nuance,
                    field_spans=entry.field_spans or {},
                )

            def clear_dimension(index: int, dim_index: int) -> None:
                row = _ensure_comparator(comparison, index)
                dims = list(row.dimensions_or_examples or [])
                while len(dims) <= dim_index:
                    dims.append("")
                dims[dim_index] = ""
                row.dimensions_or_examples = dims
                spans = {k: list(v) for k, v in (entry.field_spans or {}).items()}
                spans.pop(f"comparison.comparators[{index}].dimensions_or_examples[{dim_index}]", None)
                _persist_models(
                    entry,
                    comparison=comparison,
                    differentiation=entry.differentiation,
                    nuance=entry.nuance,
                    field_spans=spans,
                )

            def remove_dimension(index: int, dim_index: int) -> None:
                row = _ensure_comparator(comparison, index)
                dims = list(row.dimensions_or_examples or [])
                if 0 <= dim_index < len(dims):
                    dims.pop(dim_index)
                row.dimensions_or_examples = dims or None
                _persist_models(
                    entry,
                    comparison=comparison,
                    differentiation=entry.differentiation,
                    nuance=entry.nuance,
                    field_spans=entry.field_spans or {},
                )

            with ui.card().classes("w-full shadow-sm"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("Comparison").classes("text-lg font-semibold")
                    ui.button(
                        "Delete object",
                        on_click=lambda: _request_delete_entry(entry, "comparison"),
                    ).props("outline color=negative")
                ui.label(f"ID: {entry.coding_id}").classes("text-xs text-gray-500")

                _render_locked_field(
                    label=_display_name("comparand"),
                    value=comparison.comparand,
                    entry=entry,
                    span_key="comparison.comparand",
                    on_clear=lambda: clear_top_field("comparand"),
                    mutator=lambda cmp, _dif, _nua, text: setattr(cmp, "comparand", _append_text(cmp.comparand, text)),
                )

                _render_comment_field(
                    label=_display_name("comparand_comment"),
                    value=comparison.comparand_comment,
                    on_save=lambda v: save_top_field("comparand_comment", v),
                    entry=entry,
                    span_key="comparison.comparand_comment",
                    mutator=lambda cmp, _dif, _nua, text: setattr(
                        cmp,
                        "comparand_comment",
                        _append_text(cmp.comparand_comment, text),
                    ),
                )

                ui.separator()
                ui.label(_display_name("comparators")).classes("text-sm font-medium")
                rows = list(comparison.comparators or [])
                for idx, row in enumerate(rows):
                    with ui.card().classes("w-full border shadow-none"):
                        ui.label(f"Comparator {idx + 1}").classes("text-sm font-semibold")

                        for field in ["comparator", "adjective"]:
                            _render_locked_field(
                                label=_display_name(field),
                                value=getattr(row, field),
                                entry=entry,
                                span_key=f"comparison.comparators[{idx}].{field}",
                                on_clear=lambda i=idx, f=field: clear_comparator_field(i, f),
                                mutator=lambda cmp, _dif, _nua, text, i=idx, f=field: _append_to_comparator_field(
                                    cmp,
                                    i,
                                    f,
                                    text,
                                ),
                            )

                            cmt_field = f"{field}_comment"
                            _render_comment_field(
                                label=_display_name(cmt_field),
                                value=getattr(row, cmt_field),
                                on_save=lambda v, i=idx, f=cmt_field: save_comparator_field(i, f, v),
                                entry=entry,
                                span_key=f"comparison.comparators[{idx}].{cmt_field}",
                                mutator=lambda cmp, _dif, _nua, text, i=idx, f=cmt_field: _append_to_comparator_field(
                                    cmp,
                                    i,
                                    f,
                                    text,
                                ),
                            )

                        dims = list(row.dimensions_or_examples or [])
                        ui.label(_display_name("dimensions_or_examples")).classes("text-xs text-gray-700")
                        for d_idx, dim in enumerate(dims):
                            with ui.row().classes("w-full items-center gap-2"):
                                _render_locked_field(
                                    label=f"{_display_name('dimensions_or_examples')} {d_idx + 1}",
                                    value=dim,
                                    entry=entry,
                                    span_key=f"comparison.comparators[{idx}].dimensions_or_examples[{d_idx}]",
                                    on_clear=lambda i=idx, di=d_idx: clear_dimension(i, di),
                                    mutator=lambda cmp, _dif, _nua, text, i=idx, di=d_idx: _append_to_comparator_dimension(
                                        cmp,
                                        i,
                                        di,
                                        text,
                                    ),
                                )
                                ui.button("Remove", on_click=lambda _e, i=idx, di=d_idx: remove_dimension(i, di)).props("flat")
                        ui.button("New dimension or example", on_click=lambda _e, i=idx: add_dimension(i)).props("outline")

                        _render_comment_field(
                            label=_display_name("dimensions_or_examples_comment"),
                            value=row.dimensions_or_examples_comment,
                            on_save=lambda v, i=idx: save_comparator_field(
                                i,
                                "dimensions_or_examples_comment",
                                v,
                            ),
                            entry=entry,
                            span_key=f"comparison.comparators[{idx}].dimensions_or_examples_comment",
                            mutator=lambda cmp, _dif, _nua, text, i=idx: _append_to_comparator_field(
                                cmp,
                                i,
                                "dimensions_or_examples_comment",
                                text,
                            ),
                        )

                        ui.button("Remove comparator", on_click=lambda _e, i=idx: remove_comparator(i)).props("flat")

                ui.button("New comparator", on_click=add_comparator).props("outline")

        def _render_objects() -> None:
            objects_container.clear()
            with objects_container:
                if not state["entries"]:
                    ui.label("No objects yet. Create one from the buttons above.").classes("text-sm text-gray-600")
                    return
                for entry in state["entries"]:
                    kind = (entry.object_type or "").lower()
                    if kind in {"differentiation", "consider"}:
                        _render_differentiation_card(entry)
                    elif kind == "nuance":
                        _render_nuance_card(entry)
                    else:
                        _render_comparison_card(entry)

        async def _poll_pending_selection() -> None:
            transcript = state["transcript"]
            if transcript is None:
                return
            snapshot = await ui.run_javascript(
                """
                ({
                  revision: window.__srt_selection_revision || 0,
                  payload: window.__srt_last_selection || null,
                })
                """
            )
            revision = int((snapshot or {}).get("revision") or 0)
            if revision == state["selection_revision_seen"]:
                return
            state["selection_revision_seen"] = revision
            payload = (snapshot or {}).get("payload")
            if not payload:
                state["pending_span"] = None
                state["pending_span_sig"] = None
                _refresh_transcript()
                return
            normalized = _normalize_span_selection(transcript.segments, payload)
            if normalized is None:
                state["pending_span"] = None
                state["pending_span_sig"] = None
                _refresh_transcript()
                return
            sig = _span_signature(normalized)
            if sig != state["pending_span_sig"]:
                state["pending_span"] = normalized
                state["pending_span_sig"] = sig
                _refresh_transcript()

        try:
            transcript = load_transcript(selected_file)
        except Exception as exc:  # pragma: no cover
            status_label.set_text(f"Failed to load file: {exc}")
            state["transcript"] = None
            _refresh_entries()
            _refresh_transcript()
            _render_objects()
            return

        state["transcript"] = transcript
        status_label.set_text(
            f"{transcript.source_file} • {len(transcript.segments)} segments • {len(transcript.speakers)} speakers"
        )
        _refresh_entries()
        _refresh_transcript()
        _render_objects()
        ui.timer(0.2, _poll_pending_selection)


def _append_text(existing: str | None, addition: str) -> str:
    base = (existing or "").strip()
    add = (addition or "").strip()
    if not add:
        return base
    if not base:
        return add
    return f"{base}\n{add}"


def _append_to_perspective_field(
    differentiation: Differentiation,
    index: int,
    field_name: str,
    text: str,
) -> None:
    rows = list(differentiation.perspectives_extract or [])
    while len(rows) <= index:
        rows.append(Perspective())
    current = getattr(rows[index], field_name)
    setattr(rows[index], field_name, _append_text(current, text))
    differentiation.perspectives_extract = rows


def _append_to_condition_field(
    nuance: Nuance,
    index: int,
    field_name: str,
    text: str,
) -> None:
    rows = list(nuance.condition_antecedent_reason or [])
    while len(rows) <= index:
        rows.append(ConditionAntecedentReason())
    current = getattr(rows[index], field_name)
    setattr(rows[index], field_name, _append_text(current, text))
    nuance.condition_antecedent_reason = rows


def _append_to_comparator_field(cmp: Comparison, index: int, field_name: str, text: str) -> None:
    rows = list(cmp.comparators or [])
    while len(rows) <= index:
        rows.append(ComparatorDetail())
    current = getattr(rows[index], field_name)
    setattr(rows[index], field_name, _append_text(current, text))
    cmp.comparators = rows


def _append_to_comparator_dimension(cmp: Comparison, index: int, dim_index: int, text: str) -> None:
    rows = list(cmp.comparators or [])
    while len(rows) <= index:
        rows.append(ComparatorDetail())
    dims = list(rows[index].dimensions_or_examples or [])
    while len(dims) <= dim_index:
        dims.append("")
    dims[dim_index] = _append_text(dims[dim_index], text)
    rows[index].dimensions_or_examples = dims
    cmp.comparators = rows


def _extract_text_for_span(
    segments: list[TranscriptSegment],
    start_segment_id: str,
    start_char_offset: int,
    end_segment_id: str,
    end_char_offset: int,
) -> str:
    order = {seg.segment_id: i for i, seg in enumerate(segments)}
    by_id = {seg.segment_id: seg for seg in segments}
    if start_segment_id not in order or end_segment_id not in order:
        return ""
    a = order[start_segment_id]
    b = order[end_segment_id]
    if a > b:
        a, b = b, a
        start_segment_id, end_segment_id = end_segment_id, start_segment_id
        start_char_offset, end_char_offset = end_char_offset, start_char_offset
    if start_segment_id == end_segment_id:
        text = by_id[start_segment_id].text
        s = max(0, min(len(text), start_char_offset))
        e = max(0, min(len(text), end_char_offset))
        if e < s:
            s, e = e, s
        return text[s:e]

    chunks: list[str] = []
    first = by_id[start_segment_id].text
    s = max(0, min(len(first), start_char_offset))
    chunks.append(first[s:])
    for seg in segments[a + 1 : b]:
        chunks.append(seg.text)
    last = by_id[end_segment_id].text
    e = max(0, min(len(last), end_char_offset))
    chunks.append(last[:e])
    return "\n".join([c for c in chunks if c])


def _install_selection_cache_script() -> None:
    ui.add_head_html(
        """
<script>
(function() {
  if (window.__srtSelectionInstalled) return;
  window.__srtSelectionInstalled = true;
  window.__srt_last_selection = null;
  window.__srt_selection_revision = 0;

  function findSegment(node) {
    let n = node;
    while (n) {
      if (n.nodeType === 1 && n.classList && n.classList.contains('segment-text')) return n;
      n = n.parentNode;
    }
    return null;
  }

  function offsetWithin(segEl, container, offset) {
    const r = document.createRange();
    r.selectNodeContents(segEl);
    r.setEnd(container, offset);
    return r.toString().length;
  }

  function captureSelection() {
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
    const range = sel.getRangeAt(0);
    const startEl = findSegment(range.startContainer);
    const endEl = findSegment(range.endContainer);
    if (!startEl || !endEl) return null;

    const rawStart = {
      segmentId: startEl.dataset.segmentId,
      offset: offsetWithin(startEl, range.startContainer, range.startOffset),
      el: startEl,
    };
    const rawEnd = {
      segmentId: endEl.dataset.segmentId,
      offset: offsetWithin(endEl, range.endContainer, range.endOffset),
      el: endEl,
    };

    let start = rawStart;
    let end = rawEnd;
    if (rawStart.segmentId === rawEnd.segmentId) {
      if (rawStart.offset > rawEnd.offset) {
        start = rawEnd;
        end = rawStart;
      }
    } else {
      const pos = rawStart.el.compareDocumentPosition(rawEnd.el);
      const startBeforeEnd = !!(pos & Node.DOCUMENT_POSITION_FOLLOWING);
      if (!startBeforeEnd) {
        start = rawEnd;
        end = rawStart;
      }
    }

    return {
      start_segment_id: start.segmentId,
      start_char_offset: start.offset,
      end_segment_id: end.segmentId,
      end_char_offset: end.offset,
      selected_text: sel.toString(),
    };
  }

  document.addEventListener('selectionchange', () => {
    const payload = captureSelection();
    if (payload) window.__srt_last_selection = payload;
  });

  const finalizeSelection = () => {
    const payload = captureSelection();
    window.__srt_last_selection = payload;
    window.__srt_selection_revision += 1;
  };

  document.addEventListener('mouseup', finalizeSelection);
  document.addEventListener('touchend', finalizeSelection);
  document.addEventListener('keyup', (e) => {
    if (e.key === 'Shift' || e.key.startsWith('Arrow')) finalizeSelection();
  });
})();
</script>
        """
    )


def _normalize_span_selection(
    segments: list[TranscriptSegment],
    payload: dict,
) -> dict | None:
    index_map = {seg.segment_id: i for i, seg in enumerate(segments)}
    text_map = {seg.segment_id: seg.text for seg in segments}
    try:
        start_id = payload["start_segment_id"]
        end_id = payload["end_segment_id"]
        start_off = int(payload["start_char_offset"])
        end_off = int(payload["end_char_offset"])
    except Exception:
        return None
    if start_id not in index_map or end_id not in index_map:
        return None
    if index_map[start_id] > index_map[end_id]:
        start_id, end_id = end_id, start_id
        start_off, end_off = end_off, start_off
    start_text = text_map[start_id]
    end_text = text_map[end_id]
    start_off = max(0, min(len(start_text), start_off))
    end_off = max(0, min(len(end_text), end_off))
    if start_id == end_id and start_off > end_off:
        start_off, end_off = end_off, start_off
    return {
        "start_segment_id": start_id,
        "start_char_offset": start_off,
        "end_segment_id": end_id,
        "end_char_offset": end_off,
        "selected_text": payload.get("selected_text") or "",
    }


def _build_highlight_ranges(
    segments: list[TranscriptSegment],
    entries: list[CodingEntry],
    pending_span: dict | None = None,
) -> dict[str, list[tuple[int, int]]]:
    order = {seg.segment_id: i for i, seg in enumerate(segments)}
    lengths = {seg.segment_id: len(seg.text or "") for seg in segments}
    out: dict[str, list[tuple[int, int]]] = {}

    def add(seg_id: str, start: int, end: int) -> None:
        if seg_id not in lengths:
            return
        n = lengths[seg_id]
        s = max(0, min(n, int(start)))
        e = max(0, min(n, int(end)))
        if e <= s:
            return
        out.setdefault(seg_id, []).append((s, e))

    def add_span(span: dict) -> None:
        s_id = span.get("start_segment_id")
        e_id = span.get("end_segment_id")
        s_off = span.get("start_char_offset")
        e_off = span.get("end_char_offset")
        if s_id not in order or e_id not in order:
            return
        if s_off is None or e_off is None:
            return
        a = order[s_id]
        b = order[e_id]
        if a > b:
            s_id, e_id = e_id, s_id
            s_off, e_off = e_off, s_off
            a, b = b, a
        if s_id == e_id:
            add(s_id, s_off, e_off)
            return
        add(s_id, s_off, lengths[s_id])
        for seg in segments[a + 1 : b]:
            add(seg.segment_id, 0, lengths[seg.segment_id])
        add(e_id, 0, e_off)

    for entry in entries:
        if (
            entry.start_segment_id
            and entry.end_segment_id
            and entry.start_char_offset is not None
            and entry.end_char_offset is not None
        ):
            add_span(
                {
                    "start_segment_id": entry.start_segment_id,
                    "start_char_offset": entry.start_char_offset,
                    "end_segment_id": entry.end_segment_id,
                    "end_char_offset": entry.end_char_offset,
                }
            )
        for span_list in (entry.field_spans or {}).values():
            for span in span_list or []:
                add_span(span)
        if entry.segment_id and entry.segment_id in lengths:
            add(entry.segment_id, 0, lengths[entry.segment_id])

    if pending_span is not None:
        add_span(pending_span)

    return out


def _span_signature(span: dict) -> tuple:
    return (
        span.get("start_segment_id"),
        int(span.get("start_char_offset", -1)),
        span.get("end_segment_id"),
        int(span.get("end_char_offset", -1)),
        (span.get("selected_text") or "").strip(),
    )
