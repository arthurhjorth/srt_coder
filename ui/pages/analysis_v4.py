from __future__ import annotations

from nicegui import ui

from auth.service import current_username, require_auth_or_redirect
from auth.views import top_nav
from coding_books.simplified_v4.labels import (
    CODE_TYPE_LABELS,
    EXPRESSED_CERTAINTY_LABELS,
    FIELD_LABELS,
    NUANCE_RELATION_TYPE_LABELS,
    PERSPECTIVE_TYPE_LABELS,
)
from coding_books.simplified_v4.models import (
    ComparisonCoding,
    DifferentiationCoding,
    ExpressedCertainty,
    NuanceCoding,
    NuanceRelationType,
    PerspectiveType,
    SimplifiedCoding,
    SimplifiedCodingEntry,
    TranscriptSpan,
)
from coding_books.simplified_v4.validation import completion_issues
from domain.analysis_service import get_analysis
from domain.simplified_coding_service import (
    create_object_entry,
    delete_entry,
    list_entries_for_analysis_and_file,
    update_entry_payload,
)
from domain.transcript_service import load_transcript
from parsing.span_normalization import normalize_span_selection
from parsing.srt_parser import TranscriptSegment
from state.session_state import set_selected_analysis_id, set_selected_interview_file
from ui.components.transcript_view import render_transcript_segments


def _append_text(existing: str | None, addition: str) -> str:
    base = (existing or "").strip()
    added = (addition or "").strip()
    if not added:
        return base
    if not base:
        return added
    return f"{base}\n{added}"


def _span_key(code_type: str, field_name: str, index: int | None = None) -> str:
    if index is None:
        return f"{code_type}.{field_name}"
    return f"{code_type}.{field_name}[{index}]"


def _set_text_value(coding: SimplifiedCoding, key: str, value: str | None) -> None:
    prefix = f"{coding.code_type}."
    if not key.startswith(prefix):
        raise ValueError(f"Span path {key!r} does not belong to {coding.code_type!r}")
    relative = key[len(prefix) :]
    if relative.startswith("perspectives[") and relative.endswith("]"):
        index = int(relative[len("perspectives[") : -1])
        if not isinstance(coding, DifferentiationCoding):
            raise ValueError("Perspective path used for a non-differentiation coding")
        perspectives = list(coding.fields.perspectives)
        while len(perspectives) <= index:
            perspectives.append("")
        perspectives[index] = value or ""
        coding.fields.perspectives = perspectives
        return
    if not hasattr(coding.fields, relative):
        raise ValueError(f"Unknown coding field path: {key}")
    setattr(coding.fields, relative, value)


def _get_text_value(coding: SimplifiedCoding, key: str) -> str | None:
    prefix = f"{coding.code_type}."
    if not key.startswith(prefix):
        return None
    relative = key[len(prefix) :]
    if relative.startswith("perspectives[") and relative.endswith("]"):
        if not isinstance(coding, DifferentiationCoding):
            return None
        index = int(relative[len("perspectives[") : -1])
        return coding.fields.perspectives[index] if index < len(coding.fields.perspectives) else None
    value = getattr(coding.fields, relative, None)
    return value if isinstance(value, str) else None


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

    with ui.column().classes("w-full max-w-[1800px] mx-auto mt-6 gap-2"):
        ui.button("Back to interview list", on_click=lambda: ui.navigate.to("/")).props("flat")
        with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap"):
            with ui.column().classes("gap-0"):
                ui.label("Analysis Workspace").classes("text-2xl font-semibold")
                ui.label(f"Analysis: {analysis.name or analysis.analysis_id}").classes(
                    "text-sm text-gray-700"
                )
                ui.label(f"Interview file: {selected_file}").classes("text-sm text-gray-700")
            ui.badge("Coding book v4 · simplified manual", color="primary").props("outline")

        ui.label(
            "This workspace saves only v4 codings. Earlier hierarchical codings remain "
            "unchanged in the legacy data store and are not shown here."
        ).classes("text-xs text-gray-600")

        state: dict = {
            "transcript": None,
            "entries": [],
            "pending_span": None,
            "pending_span_sig": None,
            "selection_revision_seen": -1,
            "open_by_id": {},
        }

        with ui.row().classes("w-full items-center justify-between gap-2 flex-wrap"):
            status_label = ui.label("").classes("text-sm text-gray-700")
            count_label = ui.label("Objects in this analysis: 0").classes("text-sm text-gray-700")

        with ui.row().classes("w-full items-start no-wrap gap-2"):
            left_col = ui.column().classes("w-1/3 gap-1")
            right_col = ui.column().classes("w-2/3 gap-1")

        with left_col:
            ui.label("Select transcript text, then click the dashed area in a field.").classes(
                "text-xs text-gray-600"
            )
            transcript_scroll = ui.scroll_area().classes(
                "w-full h-[72vh] border rounded p-2 bg-gray-50"
            )

        with right_col:
            with ui.row().classes("w-full flex-wrap gap-2"):
                ui.button(
                    "New Differentiation",
                    on_click=lambda: _create_object("differentiation"),
                ).props("dense")
                ui.button(
                    "New Comparison",
                    on_click=lambda: _create_object("comparison"),
                ).props("dense")
                ui.button("New Nuance", on_click=lambda: _create_object("nuance")).props("dense")
            objects_scroll = ui.scroll_area().classes(
                "w-full h-[72vh] border rounded p-2 bg-gray-50"
            )
            with objects_scroll:
                objects_container = ui.column().classes("w-full gap-2")

        def _refresh_entries() -> None:
            entries = list_entries_for_analysis_and_file(
                analysis_id=analysis_id,
                interview_file=selected_file,
            )
            entries.sort(key=lambda entry: entry.created_at)
            state["entries"] = entries
            count_label.set_text(f"Objects in this analysis: {len(entries)}")

        def _replace_entry(updated: SimplifiedCodingEntry) -> None:
            state["entries"] = [
                updated if entry.coding_id == updated.coding_id else entry
                for entry in state["entries"]
            ]

        def _persist(
            entry: SimplifiedCodingEntry,
            coding: SimplifiedCoding,
            field_spans: dict[str, list[TranscriptSpan]] | None = None,
        ) -> SimplifiedCodingEntry:
            updated = update_entry_payload(
                analysis_id=analysis_id,
                coding_id=entry.coding_id,
                coding=coding,
                field_spans=field_spans,
            )
            _replace_entry(updated)
            _refresh_transcript()
            _render_objects()
            return updated

        def _create_object(object_type: str) -> None:
            try:
                created = create_object_entry(
                    analysis_id=analysis_id,
                    interview_file=selected_file,
                    object_type=object_type,
                    created_by=current_username() or "unknown",
                )
            except Exception as exc:
                status_label.set_text(f"Could not create coding: {exc}")
                return
            state["entries"].append(created)
            state["open_by_id"][created.coding_id] = True
            _refresh_entries()
            _render_objects()
            status_label.set_text(f"Created new {CODE_TYPE_LABELS[object_type]}.")

        def _delete_object(entry: SimplifiedCodingEntry) -> None:
            try:
                removed = delete_entry(analysis_id=analysis_id, coding_id=entry.coding_id)
            except Exception as exc:
                status_label.set_text(f"Delete failed: {exc}")
                return
            if not removed:
                status_label.set_text("Delete failed: coding object not found.")
                return
            state["entries"] = [
                candidate for candidate in state["entries"] if candidate.coding_id != entry.coding_id
            ]
            state["open_by_id"].pop(entry.coding_id, None)
            _refresh_transcript()
            _render_objects()
            status_label.set_text("Coding object deleted.")

        def _confirm_delete(entry: SimplifiedCodingEntry) -> None:
            dialog = ui.dialog()
            with dialog, ui.card().classes("w-[520px]"):
                ui.label("Delete coding object?").classes("text-lg font-semibold")
                ui.label(
                    "This deletes the v4 object and all of its transcript spans. "
                    "It does not change the transcript or any legacy coding."
                ).classes("text-sm text-gray-700")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button("Cancel", on_click=dialog.close).props("flat")
                    ui.button(
                        "Delete",
                        on_click=lambda: (dialog.close(), _delete_object(entry)),
                    ).props("color=negative")
            dialog.open()

        async def _jump_to_segment(segment_id: str) -> None:
            escaped = segment_id.replace("\\", "\\\\").replace('"', '\\"')
            await ui.run_javascript(
                f"""
                (() => {{
                  const sid = "{escaped}";
                  const el = document.getElementById(`segment-${{sid}}`) ||
                    document.querySelector(`[data-segment-id="${{sid}}"]`);
                  if (!el) return;
                  const scroller = el.closest('.q-scrollarea__container');
                  if (scroller) {{
                    const er = el.getBoundingClientRect();
                    const sr = scroller.getBoundingClientRect();
                    scroller.scrollTo({{
                      top: scroller.scrollTop + er.top - sr.top - sr.height / 2 + er.height / 2,
                      behavior: 'smooth'
                    }});
                  }} else {{
                    el.scrollIntoView({{behavior: 'smooth', block: 'center'}});
                  }}
                }})();
                """
            )

        async def _append_selection(entry: SimplifiedCodingEntry, key: str) -> None:
            transcript = state["transcript"]
            if transcript is None:
                return
            cached = await ui.run_javascript("window.__srt_last_selection || null")
            if not cached:
                status_label.set_text("Select transcript text first.")
                return
            normalized = normalize_span_selection(transcript.segments, cached)
            if normalized is None:
                status_label.set_text("The selection contains no non-whitespace transcript text.")
                return

            coding = entry.coding.model_copy(deep=True)
            selected_text = normalized["selected_text"]
            _set_text_value(coding, key, _append_text(_get_text_value(coding, key), selected_text))

            spans = {path: list(values) for path, values in entry.field_spans.items()}
            spans.setdefault(key, []).append(TranscriptSpan.model_validate(normalized))
            state["pending_span"] = None
            state["pending_span_sig"] = None
            await ui.run_javascript(
                """
                window.__srt_last_selection = null;
                window.__srt_selection_revision = (window.__srt_selection_revision || 0) + 1;
                """
            )
            _persist(entry, coding, spans)
            status_label.set_text(f"Added transcript text to {key}.")

        def _delete_span(entry: SimplifiedCodingEntry, key: str, index: int) -> None:
            current = list(entry.field_spans.get(key, []))
            if index < 0 or index >= len(current):
                return
            remaining = [span for span_index, span in enumerate(current) if span_index != index]
            spans = {path: list(values) for path, values in entry.field_spans.items()}
            if remaining:
                spans[key] = remaining
            else:
                spans.pop(key, None)
            coding = entry.coding.model_copy(deep=True)
            rebuilt = "\n".join(span.selected_text.strip() for span in remaining if span.selected_text.strip())
            _set_text_value(coding, key, rebuilt or None)
            _persist(entry, coding, spans)
            status_label.set_text("Transcript span deleted.")

        def _clear_field(entry: SimplifiedCodingEntry, key: str) -> None:
            coding = entry.coding.model_copy(deep=True)
            _set_text_value(coding, key, None)
            spans = {path: list(values) for path, values in entry.field_spans.items()}
            spans.pop(key, None)
            _persist(entry, coding, spans)
            status_label.set_text("Field cleared.")

        def _render_span_field(
            entry: SimplifiedCodingEntry,
            *,
            field_name: str,
            required: bool,
            index: int | None = None,
            help_text: str | None = None,
        ) -> None:
            key = _span_key(entry.object_type, field_name, index)
            label = FIELD_LABELS[field_name]
            if index is not None:
                label = f"{label} {index + 1}"
            with ui.row().classes("w-full items-center justify-between gap-2"):
                ui.label(f"{label}{' *' if required else ''}").classes("text-xs font-medium")
                if _get_text_value(entry.coding, key) or entry.field_spans.get(key):
                    ui.button(
                        "Clear",
                        on_click=lambda _e, e=entry, k=key: _clear_field(e, k),
                    ).props("flat dense color=negative")
            if help_text:
                ui.label(help_text).classes("text-[11px] text-gray-600")

            field_box = ui.element("div").classes(
                "w-full min-h-[48px] rounded border bg-gray-100 px-2 py-2"
            )
            with field_box:
                spans = entry.field_spans.get(key, [])
                for span_index, span in enumerate(spans):
                    span_row = ui.element("div").classes(
                        "w-full mb-1 rounded border bg-white px-2 py-1 cursor-pointer"
                    )
                    with span_row:
                        with ui.row().classes("w-full items-start justify-between gap-2 no-wrap"):
                            ui.label(span.selected_text).classes(
                                "text-xs whitespace-pre-wrap flex-1"
                            )
                            ui.button(
                                "Delete",
                                on_click=lambda _e, e=entry, k=key, i=span_index: _delete_span(
                                    e, k, i
                                ),
                            ).props("flat dense color=negative")
                    span_row.on(
                        "click",
                        lambda _e, segment_id=span.start_segment_id: _jump_to_segment(segment_id),
                    )
                add_box = ui.element("div").classes(
                    "w-full min-h-[28px] rounded border border-dashed bg-white/80 px-2 py-1 cursor-pointer"
                )
                with add_box:
                    ui.label("Click here to add the current transcript selection").classes(
                        "text-[11px] text-gray-500"
                    )
                add_box.on(
                    "mousedown",
                    lambda _e, e=entry, k=key: _append_selection(e, k),
                )

        def _save_coder_note(entry: SimplifiedCodingEntry, value: str | None) -> None:
            coding = entry.coding.model_copy(deep=True)
            coding.fields.coder_note = (value or "").strip() or None
            _persist(entry, coding)
            status_label.set_text("Coder note saved.")

        def _render_coder_note(entry: SimplifiedCodingEntry) -> None:
            ui.label(FIELD_LABELS["coder_note"]).classes("text-xs font-medium")
            note = ui.textarea(value=entry.coding.fields.coder_note or "").props("rows=2").classes(
                "w-full"
            )
            note.on("blur", lambda _e, element=note: _save_coder_note(entry, element.value))

        def _add_perspective(entry: SimplifiedCodingEntry) -> None:
            if not isinstance(entry.coding, DifferentiationCoding):
                return
            coding = entry.coding.model_copy(deep=True)
            coding.fields.perspectives = [*coding.fields.perspectives, ""]
            _persist(entry, coding)

        def _save_perspective_types(entry: SimplifiedCodingEntry, values) -> None:
            if not isinstance(entry.coding, DifferentiationCoding):
                return
            coding = entry.coding.model_copy(deep=True)
            coding.fields.perspective_types = [PerspectiveType(value) for value in (values or [])]
            _persist(entry, coding)
            status_label.set_text("Perspective types saved.")

        def _render_differentiation(entry: SimplifiedCodingEntry) -> None:
            if not isinstance(entry.coding, DifferentiationCoding):
                return
            _render_span_field(
                entry,
                field_name="thing_being_considered",
                required=True,
                help_text="Den ene bestemte ting, som alle perspektiverne handler om.",
            )
            perspective_count = max(2, len(entry.coding.fields.perspectives))
            for index in range(perspective_count):
                _render_span_field(
                    entry,
                    field_name="perspectives",
                    required=True,
                    index=index,
                    help_text="Et konkret, ikke-overlappende perspektiv på fokusemnet.",
                )
            ui.button("Add perspective", on_click=lambda: _add_perspective(entry)).props(
                "outline dense"
            )
            options = {value.value: label for value, label in PERSPECTIVE_TYPE_LABELS.items()}
            perspective_types = ui.select(
                options=options,
                value=[value.value for value in entry.coding.fields.perspective_types],
                label=FIELD_LABELS["perspective_types"],
                multiple=True,
            ).props("use-chips clearable").classes("w-full")
            perspective_types.on_value_change(
                lambda event: _save_perspective_types(entry, event.value),
            )
            _render_coder_note(entry)

        def _render_comparison(entry: SimplifiedCodingEntry) -> None:
            if not isinstance(entry.coding, ComparisonCoding):
                return
            fields = (
                ("text_passage", True, "Mindste tekststykke med A, B og relationen."),
                ("thing_a", True, "Den første ting, der sammenlignes."),
                ("thing_b", True, "Det eksplicitte sammenligningspunkt."),
                ("relation", True, "De ord, der placerer A relativt til B."),
                ("comparison_basis", False, "Det valgfrie grundlag, A og B sammenlignes på."),
            )
            for field_name, required, help_text in fields:
                _render_span_field(
                    entry,
                    field_name=field_name,
                    required=required,
                    help_text=help_text,
                )
            _render_coder_note(entry)

        def _save_relation_type(entry: SimplifiedCodingEntry, value) -> None:
            if not isinstance(entry.coding, NuanceCoding):
                return
            coding = entry.coding.model_copy(deep=True)
            coding.fields.relation_type = NuanceRelationType(value) if value else None
            _persist(entry, coding)
            status_label.set_text("Relation type saved.")

        def _save_certainty(entry: SimplifiedCodingEntry, value) -> None:
            if not isinstance(entry.coding, NuanceCoding):
                return
            coding = entry.coding.model_copy(deep=True)
            coding.fields.expressed_certainty = ExpressedCertainty(value) if value else None
            _persist(entry, coding)
            status_label.set_text("Expressed certainty saved.")

        def _render_nuance(entry: SimplifiedCodingEntry) -> None:
            if not isinstance(entry.coding, NuanceCoding):
                return
            relation_options = {
                value.value: label for value, label in NUANCE_RELATION_TYPE_LABELS.items()
            }
            relation = ui.select(
                options=relation_options,
                value=(
                    entry.coding.fields.relation_type.value
                    if entry.coding.fields.relation_type
                    else None
                ),
                label=f"{FIELD_LABELS['relation_type']} *",
            ).props("clearable").classes("w-full")
            relation.on_value_change(lambda event: _save_relation_type(entry, event.value))

            _render_span_field(
                entry,
                field_name="influence_or_action_x",
                required=True,
                help_text="Årsag, betingelse, handling eller plan, der forbindes med Y.",
            )
            _render_span_field(
                entry,
                field_name="outcome_or_goal_y",
                required=True,
                help_text="Tilstand, ændring, virkning eller mål, der forbindes med X.",
            )
            _render_span_field(
                entry,
                field_name="x_y_connection",
                required=True,
                help_text="Interviewpersonens ord eller konstruktion, der forbinder X og Y.",
            )

            if entry.coding.fields.relation_type != NuanceRelationType.AMBITION_INTENTION:
                certainty_options = {
                    value.value: label for value, label in EXPRESSED_CERTAINTY_LABELS.items()
                }
                certainty = ui.select(
                    options=certainty_options,
                    value=(
                        entry.coding.fields.expressed_certainty.value
                        if entry.coding.fields.expressed_certainty
                        else None
                    ),
                    label=f"{FIELD_LABELS['expressed_certainty']} *",
                ).props("clearable").classes("w-full")
                certainty.on_value_change(
                    lambda event: _save_certainty(entry, event.value),
                )
            else:
                ui.label(
                    "Udtrykt sikkerhed er ikke relevant for ambition/intention. "
                    "En tidligere værdi bevares skjult, hvis relationstypen ændres."
                ).classes("text-[11px] text-gray-600")

            _render_span_field(
                entry,
                field_name="limitation",
                required=False,
                help_text="Ekstra betingelser, der afgrænser relationens gyldighed eller formål.",
            )
            _render_coder_note(entry)

        def _summary(entry: SimplifiedCodingEntry) -> str:
            fields = entry.coding.fields
            if isinstance(entry.coding, DifferentiationCoding):
                return fields.thing_being_considered or "No focus topic yet"
            if isinstance(entry.coding, ComparisonCoding):
                return fields.text_passage or fields.relation or "No comparison text yet"
            if isinstance(entry.coding, NuanceCoding):
                return fields.x_y_connection or fields.outcome_or_goal_y or "No X–Y relation yet"
            return ""

        def _render_card(entry: SimplifiedCodingEntry) -> None:
            issues = completion_issues(entry.coding)
            label = CODE_TYPE_LABELS[entry.object_type]
            with ui.card().classes("w-full gap-2"):
                with ui.row().classes("w-full items-start justify-between gap-2"):
                    with ui.column().classes("gap-0 flex-1"):
                        ui.label(label).classes("text-lg font-semibold")
                        ui.label(_summary(entry)).classes("text-xs text-gray-600")
                        if issues:
                            ui.label(" · ".join(issues)).classes("text-xs text-amber-700")
                        else:
                            ui.label("Manualens anbefalede felter er udfyldt.").classes(
                                "text-xs text-green-700"
                            )
                    ui.button("Delete object", on_click=lambda: _confirm_delete(entry)).props(
                        "flat dense color=negative"
                    )
                ui.separator()
                if isinstance(entry.coding, DifferentiationCoding):
                    _render_differentiation(entry)
                elif isinstance(entry.coding, ComparisonCoding):
                    _render_comparison(entry)
                elif isinstance(entry.coding, NuanceCoding):
                    _render_nuance(entry)

        def _render_objects() -> None:
            objects_container.clear()
            with objects_container:
                if not state["entries"]:
                    ui.label(
                        "No v4 coding objects yet. Create one using the buttons above."
                    ).classes("text-sm text-gray-600")
                    return
                for entry in state["entries"]:
                    _render_card(entry)

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
                    coded_segment_ids=set(highlight_ranges),
                    highlight_ranges=highlight_ranges,
                    pending_highlight_ranges=pending_ranges,
                    on_segment_click=None,
                )

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
            normalized = (
                normalize_span_selection(transcript.segments, payload)
                if payload
                else None
            )
            state["pending_span"] = normalized
            signature = _span_signature(normalized) if normalized else None
            if signature != state["pending_span_sig"]:
                state["pending_span_sig"] = signature
                _refresh_transcript()

        try:
            transcript = load_transcript(selected_file)
        except Exception as exc:  # pragma: no cover - visual error path
            status_label.set_text(f"Failed to load file: {exc}")
            _refresh_entries()
            _refresh_transcript()
            _render_objects()
            return

        state["transcript"] = transcript
        status_label.set_text(
            f"{transcript.source_file} • {len(transcript.segments)} segments • "
            f"{len(transcript.speakers)} speakers"
        )
        _refresh_entries()
        _refresh_transcript()
        _render_objects()
        ui.timer(0.2, _poll_pending_selection)


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
    let current = node;
    while (current) {
      if (current.nodeType === 1 && current.classList && current.classList.contains('segment-text')) {
        return current;
      }
      current = current.parentNode;
    }
    return null;
  }

  function offsetWithin(segment, container, offset) {
    const range = document.createRange();
    range.selectNodeContents(segment);
    range.setEnd(container, offset);
    return range.toString().length;
  }

  function captureSelection() {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return null;
    const range = selection.getRangeAt(0);
    const startElement = findSegment(range.startContainer);
    const endElement = findSegment(range.endContainer);
    if (!startElement || !endElement) return null;

    const rawStart = {
      segmentId: startElement.dataset.segmentId,
      offset: offsetWithin(startElement, range.startContainer, range.startOffset),
      element: startElement,
    };
    const rawEnd = {
      segmentId: endElement.dataset.segmentId,
      offset: offsetWithin(endElement, range.endContainer, range.endOffset),
      element: endElement,
    };

    let start = rawStart;
    let end = rawEnd;
    if (rawStart.segmentId === rawEnd.segmentId) {
      if (rawStart.offset > rawEnd.offset) {
        start = rawEnd;
        end = rawStart;
      }
    } else {
      const position = rawStart.element.compareDocumentPosition(rawEnd.element);
      if (!(position & Node.DOCUMENT_POSITION_FOLLOWING)) {
        start = rawEnd;
        end = rawStart;
      }
    }

    return {
      start_segment_id: start.segmentId,
      start_char_offset: start.offset,
      end_segment_id: end.segmentId,
      end_char_offset: end.offset,
      selected_text: selection.toString(),
    };
  }

  document.addEventListener('selectionchange', () => {
    const payload = captureSelection();
    if (payload) window.__srt_last_selection = payload;
  });

  const finalizeSelection = () => {
    window.__srt_last_selection = captureSelection();
    window.__srt_selection_revision += 1;
  };
  document.addEventListener('mouseup', finalizeSelection);
  document.addEventListener('touchend', finalizeSelection);
  document.addEventListener('keyup', event => {
    if (event.key === 'Shift' || event.key.startsWith('Arrow')) finalizeSelection();
  });
})();
</script>
        """
    )


def _build_highlight_ranges(
    segments: list[TranscriptSegment],
    entries: list[SimplifiedCodingEntry],
    pending_span: dict | None = None,
) -> dict[str, list[tuple[int, int]]]:
    order = {segment.segment_id: index for index, segment in enumerate(segments)}
    lengths = {segment.segment_id: len(segment.text or "") for segment in segments}
    ranges: dict[str, list[tuple[int, int]]] = {}

    def add(segment_id: str, start: int, end: int) -> None:
        if segment_id not in lengths:
            return
        length = lengths[segment_id]
        normalized_start = max(0, min(length, int(start)))
        normalized_end = max(0, min(length, int(end)))
        if normalized_end > normalized_start:
            ranges.setdefault(segment_id, []).append((normalized_start, normalized_end))

    def add_span(span: TranscriptSpan | dict) -> None:
        raw = span.model_dump() if isinstance(span, TranscriptSpan) else span
        start_id = raw.get("start_segment_id")
        end_id = raw.get("end_segment_id")
        start_offset = raw.get("start_char_offset")
        end_offset = raw.get("end_char_offset")
        if start_id not in order or end_id not in order:
            return
        if start_offset is None or end_offset is None:
            return
        start_index = order[start_id]
        end_index = order[end_id]
        if start_index > end_index:
            start_id, end_id = end_id, start_id
            start_offset, end_offset = end_offset, start_offset
            start_index, end_index = end_index, start_index
        if start_id == end_id:
            add(start_id, start_offset, end_offset)
            return
        add(start_id, start_offset, lengths[start_id])
        for segment in segments[start_index + 1 : end_index]:
            add(segment.segment_id, 0, lengths[segment.segment_id])
        add(end_id, 0, end_offset)

    for entry in entries:
        for spans in entry.field_spans.values():
            for span in spans:
                add_span(span)
    if pending_span is not None:
        add_span(pending_span)
    return ranges


def _span_signature(span: dict) -> tuple:
    return (
        span.get("start_segment_id"),
        int(span.get("start_char_offset", -1)),
        span.get("end_segment_id"),
        int(span.get("end_char_offset", -1)),
        (span.get("selected_text") or "").strip(),
    )
