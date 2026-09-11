from __future__ import annotations

import hashlib
import re
from typing import Any

from nicegui import ui

from auth.service import require_auth_or_redirect
from auth.views import top_nav
from coding_books.simplified_v5.labels import CODE_TYPE_LABELS, FIELD_LABELS
from coding_books.simplified_v5.models import (
    ComparisonCoding,
    DifferentiationCoding,
    NuanceCoding,
    SimplifiedCodingEntry,
)
from domain.simplified_agreement_service_v5 import (
    AgreementReport,
    AgreementRules,
    AgreementSource,
    NormalizedAnnotation,
    PairAgreement,
    build_agreement_report,
    load_agreement_export,
    matched_annotation_keys,
    report_as_csv,
    report_as_json,
)
from domain.transcript_service import load_transcript


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _short(value: Any) -> str:
    if value is None or value == "" or value == []:
        return "(empty)"
    if isinstance(value, list):
        return ", ".join(str(getattr(item, "value", item)) for item in value) or "(empty)"
    return str(getattr(value, "value", value))


def _field_rows(entry: SimplifiedCodingEntry) -> list[tuple[str, str, Any, bool]]:
    fields = entry.coding.fields
    rows: list[tuple[str, str, Any, bool]] = []
    if isinstance(entry.coding, DifferentiationCoding):
        rows.append(
            (
                "differentiation.thing_being_considered",
                _label("thing_being_considered"),
                fields.thing_being_considered,
                False,
            )
        )
        for index, perspective in enumerate(fields.perspectives):
            for name in ("text", "perspective_types", "perspective_types_comment"):
                rows.append(
                    (
                        f"differentiation.perspectives[{index}].{name}",
                        f"Perspective {index + 1} · {_label(name)}",
                        getattr(perspective, name),
                        name.endswith("_comment"),
                    )
                )
    elif isinstance(entry.coding, ComparisonCoding):
        for base in ("text_passage", "thing_a", "thing_b", "relation", "comparison_basis"):
            rows.append((f"comparison.{base}", _label(base), getattr(fields, base), False))
    elif isinstance(entry.coding, NuanceCoding):
        for base in (
            "relation_type",
            "influence_or_action_x",
            "outcome_or_goal_y",
            "x_y_connection",
            "expressed_certainty",
            "limitation",
        ):
            rows.append((f"nuance.{base}", _label(base), getattr(fields, base), False))
            if base in {"relation_type", "expressed_certainty"}:
                comment_name = f"{base}_comment"
                rows.append(
                    (
                        f"nuance.{comment_name}",
                        _label(comment_name),
                        getattr(fields, comment_name),
                        True,
                    )
                )
    rows.append((f"{entry.object_type}.coder_note", FIELD_LABELS["coder_note"], fields.coder_note, True))
    return rows


def _label(name: str) -> str:
    base = name.removesuffix("_comment")
    label = FIELD_LABELS.get(base, base.replace("_", " ").title())
    return f"{label} – comment" if name.endswith("_comment") else label


def _entry_title(entry: SimplifiedCodingEntry) -> str:
    fields = entry.coding.fields
    if isinstance(entry.coding, DifferentiationCoding):
        summary = fields.thing_being_considered
    elif isinstance(entry.coding, ComparisonCoding):
        summary = fields.text_passage or fields.relation
    else:
        summary = fields.x_y_connection or fields.outcome_or_goal_y
    return f"{CODE_TYPE_LABELS[entry.object_type]} · {summary or entry.coding_id}"


def _local_evidence(annotation: NormalizedAnnotation) -> tuple[str, bool]:
    try:
        transcript = load_transcript(annotation.interview_file)
        by_id = {segment.segment_id: index for index, segment in enumerate(transcript.segments)}
        start = by_id[annotation.span.start_segment_id]
        end = by_id[annotation.span.end_segment_id]
        if start > end:
            start, end = end, start
        excerpt = "\n".join(
            f"{segment.speaker or 'Speaker'}: {segment.text}"
            for segment in transcript.segments[start : end + 1]
        )
        if excerpt.strip():
            return excerpt, True
    except Exception:
        pass
    return annotation.span.selected_text or "(no selected text)", False


def render_agreement_page() -> None:
    if not require_auth_or_redirect():
        return
    top_nav()

    with ui.column().classes("w-full max-w-[1800px] mx-auto mt-8 gap-4"):
        with ui.row().classes("w-full items-center justify-between"):
            with ui.column().classes("gap-0"):
                ui.label("Coding Agreement · v5").classes("text-2xl font-semibold")
                ui.label(
                    "Span agreement and categorical agreement are reported separately. "
                    "Comments and coder notes are shown only for neutral review."
                ).classes("text-sm text-gray-700")
            ui.button("Back to dashboard", on_click=lambda: ui.navigate.to("/")).props("flat")

        state: dict[str, Any] = {
            "sources": [],
            "next_index": 0,
            "errors": [],
            "rules": AgreementRules(),
            "report": None,
            "selected_pair": None,
        }
        status = ui.label("").classes("text-sm text-red-700 whitespace-pre-wrap")
        source_container = ui.column().classes("w-full gap-2")
        report_container = ui.column().classes("w-full gap-3")

        with ui.card().classes("w-full shadow-sm gap-3"):
            ui.label("1. Add coding exports").classes("font-semibold")
            ui.label(
                "V5 exports and v4 exports are accepted. Files are kept in selection order, "
                "validated independently, and never modified. Duplicate content is rejected."
            ).classes("text-xs text-gray-600")

            async def on_upload(event) -> None:
                reserved_index = state["next_index"]
                state["next_index"] += 1
                filename = str(getattr(event.file, "name", "") or f"source-{reserved_index + 1}.json")
                try:
                    content = await event.file.read()
                    if isinstance(content, str):
                        raw_bytes = content.encode("utf-8")
                    else:
                        raw_bytes = bytes(content)
                    digest = hashlib.sha256(raw_bytes).hexdigest()
                    if any(source.content_hash == digest for source in state["sources"]):
                        raise ValueError("duplicate of an already selected export")
                    source = load_agreement_export(
                        raw_bytes.decode("utf-8-sig"),
                        source_name=filename,
                        source_index=reserved_index,
                        content_hash=digest,
                    )
                    state["sources"].append(source)
                    state["sources"].sort(key=lambda item: item.source_index)
                except Exception as exc:
                    state["errors"].append((reserved_index, filename, str(exc)))
                    state["errors"].sort()
                _rebuild_report()

            ui.upload(
                label="Drop two or more v4/v5 analysis exports",
                multiple=True,
                on_upload=on_upload,
                auto_upload=True,
            ).props('accept=".json"')

            with ui.row().classes("w-full items-end gap-3 flex-wrap"):
                span_mode = ui.select(
                    options={"partial": "Any overlap", "exact": "Exact span"},
                    value="partial",
                    label="Span rule",
                ).classes("w-56")
                field_mode = ui.select(
                    options={
                        "normalized": "Same field (ignore list index)",
                        "exact": "Exact field path",
                        "ignore": "Ignore field path",
                    },
                    value="normalized",
                    label="Field rule",
                ).classes("w-72")
                same_type = ui.checkbox("Require same object type", value=True)
                ui.button("Clear all", on_click=lambda: _clear_all()).props(
                    "outline color=negative"
                )

            def rules_changed(_event=None) -> None:
                state["rules"] = AgreementRules(
                    span_mode=span_mode.value,
                    field_mode=field_mode.value,
                    require_same_object_type=bool(same_type.value),
                )
                _rebuild_report()

            span_mode.on_value_change(rules_changed)
            field_mode.on_value_change(rules_changed)
            same_type.on_value_change(rules_changed)

        def _remove_source(source_index: int) -> None:
            state["sources"] = [
                source for source in state["sources"] if source.source_index != source_index
            ]
            _rebuild_report()

        def _remove_error(index: int) -> None:
            state["errors"] = [error for error in state["errors"] if error[0] != index]
            _render_sources()

        def _clear_all() -> None:
            state["sources"] = []
            state["errors"] = []
            state["report"] = None
            state["selected_pair"] = None
            _render_sources()
            _render_report()

        def _render_sources() -> None:
            source_container.clear()
            with source_container:
                for source in state["sources"]:
                    with ui.row().classes(
                        "w-full items-center justify-between rounded border bg-emerald-50 px-3 py-2"
                    ):
                        with ui.column().classes("gap-0"):
                            ui.label(
                                f"{source.source_index + 1}. {source.source_name} · {source.label}"
                            ).classes("text-sm font-medium")
                            ui.label(
                                f"{len(source.codings)} objects · {len(source.annotations)} primary spans"
                            ).classes("text-xs text-gray-600")
                        ui.button(
                            "Remove",
                            on_click=lambda _e, index=source.source_index: _remove_source(index),
                        ).props("flat dense color=negative")
                for index, filename, message in state["errors"]:
                    with ui.row().classes(
                        "w-full items-center justify-between rounded border bg-red-50 px-3 py-2"
                    ):
                        ui.label(f"{index + 1}. {filename}: {message}").classes(
                            "text-sm text-red-800"
                        )
                        ui.button(
                            "Dismiss", on_click=lambda _e, i=index: _remove_error(i)
                        ).props("flat dense")

        def _rebuild_report() -> None:
            if len(state["sources"]) >= 2:
                state["report"] = build_agreement_report(
                    state["sources"], state["rules"]
                )
                valid_pairs = {
                    (pair.left_source_index, pair.right_source_index)
                    for pair in state["report"].pair_agreements
                }
                if state["selected_pair"] not in valid_pairs:
                    first_pair = next(iter(state["report"].pair_agreements), None)
                    state["selected_pair"] = (
                        (first_pair.left_source_index, first_pair.right_source_index)
                        if first_pair
                        else None
                    )
                status.set_text("")
            else:
                state["report"] = None
                status.set_text("Add at least two valid exports to compare.")
            _render_sources()
            _render_report()

        def _selected_pair(report: AgreementReport) -> PairAgreement | None:
            return next(
                (
                    pair
                    for pair in report.pair_agreements
                    if (pair.left_source_index, pair.right_source_index)
                    == state["selected_pair"]
                ),
                None,
            )

        def _render_metric(label: str, value: str) -> None:
            with ui.card().classes("min-w-36 bg-slate-50 shadow-none gap-0"):
                ui.label(value).classes("text-xl font-semibold")
                ui.label(label).classes("text-xs text-gray-600")

        def _field_status(
            source: AgreementSource,
            entry: SimplifiedCodingEntry,
            path: str,
            pair: PairAgreement,
        ) -> str:
            categorical = _categorical_status(source, entry, path, pair)
            if categorical is not None:
                return categorical
            matched = matched_annotation_keys(pair)
            annotations = [
                annotation
                for annotation in source.annotations
                if annotation.coding_id == entry.coding_id and annotation.field_path == path
            ]
            if not annotations:
                return "neutral"
            count = sum(annotation.key in matched for annotation in annotations)
            if count == len(annotations):
                return "match"
            return "partial" if count else "mismatch"

        def _categorical_status(
            source: AgreementSource,
            entry: SimplifiedCodingEntry,
            path: str,
            pair: PairAgreement,
        ) -> str | None:
            is_left = source.source_index == pair.left_source_index
            for comparison in pair.categorical_comparisons:
                expected_id = (
                    comparison.left_coding_id if is_left else comparison.right_coding_id
                )
                if expected_id != entry.coding_id:
                    continue
                if comparison.field_path == path:
                    return "match" if comparison.agrees else "mismatch"
                match = re.fullmatch(
                    r"differentiation\.perspectives\[(\d+):(\d+)\]\.perspective_types",
                    comparison.field_path,
                )
                current = re.fullmatch(
                    r"differentiation\.perspectives\[(\d+)\]\.perspective_types",
                    path,
                )
                if match and current:
                    side_index = int(match.group(1 if is_left else 2))
                    if int(current.group(1)) == side_index:
                        return "match" if comparison.agrees else "mismatch"
            return None

        def _render_entry(
            source: AgreementSource,
            entry: SimplifiedCodingEntry,
            pair: PairAgreement,
        ) -> None:
            with ui.card().classes("w-full shadow-none border gap-1"):
                ui.label(_entry_title(entry)).classes("font-semibold")
                ui.label(entry.coding_id).classes("font-mono text-[10px] text-gray-500")
                for path, label, value, neutral in _field_rows(entry):
                    status_name = "neutral" if neutral else _field_status(source, entry, path, pair)
                    classes = {
                        "neutral": "bg-slate-50 border-slate-200 text-slate-800",
                        "match": "bg-emerald-50 border-emerald-300 text-emerald-950",
                        "partial": "bg-amber-50 border-amber-300 text-amber-950",
                        "mismatch": "bg-red-50 border-red-300 text-red-950",
                    }[status_name]
                    with ui.element("div").classes(f"w-full rounded border px-2 py-1 {classes}"):
                        ui.label(label).classes("text-[10px] font-semibold")
                        ui.label(_short(value)).classes("text-xs whitespace-pre-wrap")
                for path, spans in entry.field_spans.items():
                    for index, span in enumerate(spans):
                        if not span.comment:
                            continue
                        with ui.element("div").classes(
                            "w-full rounded border px-2 py-1 bg-slate-50 "
                            "border-slate-200 text-slate-800"
                        ):
                            ui.label(f"Span comment · {path} · #{index + 1}").classes(
                                "text-[10px] font-semibold"
                            )
                            ui.label(span.comment).classes("text-xs whitespace-pre-wrap")

        def _render_pair_detail(report: AgreementReport, pair: PairAgreement) -> None:
            sources = {source.source_index: source for source in report.sources}
            left = sources[pair.left_source_index]
            right = sources[pair.right_source_index]
            left_entries = {entry.coding_id: entry for entry in left.codings}
            right_entries = {entry.coding_id: entry for entry in right.codings}

            ui.label("Aligned coding objects").classes("text-lg font-semibold")
            if not pair.object_alignments:
                ui.label("No objects could be aligned by their primary spans.").classes(
                    "text-sm text-gray-600"
                )
            for alignment in pair.object_alignments:
                with ui.expansion(
                    f"{alignment.object_type} · {alignment.matched_span_count} matched spans",
                    value=True,
                ).classes("w-full border rounded bg-white"):
                    with ui.row().classes("w-full items-start no-wrap gap-3"):
                        with ui.column().classes("w-1/2 gap-1"):
                            ui.label(pair.left_label).classes("text-xs font-semibold")
                            _render_entry(
                                left, left_entries[alignment.left_coding_id], pair
                            )
                        with ui.column().classes("w-1/2 gap-1"):
                            ui.label(pair.right_label).classes("text-xs font-semibold")
                            _render_entry(
                                right, right_entries[alignment.right_coding_id], pair
                            )

            with ui.expansion("Focused transcript evidence", value=True).classes(
                "w-full border rounded bg-white"
            ):
                if not pair.annotation_matches:
                    ui.label("No matched transcript spans.").classes("text-sm text-gray-600")
                for match in pair.annotation_matches:
                    with ui.row().classes("w-full items-stretch no-wrap gap-3"):
                        for annotation in (match.left, match.right):
                            excerpt, local = _local_evidence(annotation)
                            with ui.element("div").classes(
                                "w-1/2 rounded border bg-sky-50 px-3 py-2"
                            ):
                                ui.label(
                                    f"{annotation.source_label} · {annotation.field_path}"
                                ).classes("text-xs font-semibold")
                                ui.label(
                                    f"{annotation.span.range_label} · "
                                    f"{'local transcript' if local else 'export fallback'}"
                                ).classes("text-[10px] text-gray-600")
                                ui.label(excerpt).classes("text-xs whitespace-pre-wrap")

            with ui.expansion("Discrepancies", value=True).classes(
                "w-full border rounded bg-white"
            ):
                ui.label("Unmatched coding objects").classes("font-semibold")
                with ui.row().classes("w-full items-start no-wrap gap-3"):
                    for ids, label in (
                        (pair.unmatched_left_coding_ids, pair.left_label),
                        (pair.unmatched_right_coding_ids, pair.right_label),
                    ):
                        with ui.column().classes("w-1/2 gap-1"):
                            ui.label(label).classes("text-xs font-semibold")
                            if ids:
                                for coding_id in ids:
                                    ui.label(coding_id).classes("font-mono text-xs")
                            else:
                                ui.label("None").classes("text-xs text-gray-500")

                ui.label("Unmatched primary spans").classes("font-semibold mt-2")
                matched = matched_annotation_keys(pair)
                unmatched = [
                    annotation
                    for source in (left, right)
                    for annotation in source.annotations
                    if annotation.key not in matched
                ]
                if unmatched:
                    for annotation in unmatched:
                        ui.label(
                            f"{annotation.source_label} · {annotation.coding_id} · "
                            f"{annotation.field_path} · {annotation.span.range_label}"
                        ).classes("text-xs")
                else:
                    ui.label("None").classes("text-xs text-gray-500")

                ui.label("Differing categorical values").classes("font-semibold mt-2")
                differing = [item for item in pair.categorical_comparisons if not item.agrees]
                if differing:
                    for item in differing:
                        ui.label(
                            f"{item.field_path}: {_short(item.left_value)} ↔ {_short(item.right_value)}"
                        ).classes("text-xs text-red-800")
                else:
                    ui.label("None").classes("text-xs text-gray-500")

        def _render_report() -> None:
            report_container.clear()
            report: AgreementReport | None = state["report"]
            if report is None:
                return
            with report_container:
                ui.label("2. Pairwise results").classes("text-xl font-semibold")
                with ui.row().classes("w-full gap-2 flex-wrap"):
                    for pair in report.pair_agreements:
                        with ui.card().classes("min-w-[320px] shadow-sm gap-1"):
                            ui.label(f"{pair.left_label} ↔ {pair.right_label}").classes(
                                "text-sm font-semibold"
                            )
                            ui.label(
                                f"Span F1 {_percent(pair.f1)} · P {_percent(pair.precision)} · "
                                f"R {_percent(pair.recall)}"
                            ).classes("text-xs")
                            ui.label(
                                f"Categorical agreement {_percent(pair.categorical_agreement)} "
                                f"({pair.categorical_matches}/{pair.categorical_total})"
                            ).classes("text-xs")
                with ui.row().classes("w-full items-center gap-3 flex-wrap"):
                    options = {
                        f"{pair.left_source_index}:{pair.right_source_index}": (
                            f"{pair.left_label} ↔ {pair.right_label}"
                        )
                        for pair in report.pair_agreements
                    }
                    selected_value = (
                        f"{state['selected_pair'][0]}:{state['selected_pair'][1]}"
                        if state["selected_pair"]
                        else None
                    )
                    pair_select = ui.select(
                        options=options,
                        value=selected_value,
                        label="Detailed source pair",
                    ).classes("min-w-[520px]")

                    def select_pair(event) -> None:
                        left_index, right_index = str(event.value).split(":", maxsplit=1)
                        state["selected_pair"] = (int(left_index), int(right_index))
                        _render_report()

                    pair_select.on_value_change(select_pair)
                    ui.button(
                        "Download JSON",
                        on_click=lambda: ui.download(
                            report_as_json(report).encode("utf-8"),
                            "agreement_v5.json",
                            "application/json",
                        ),
                    ).props("outline")
                    ui.button(
                        "Download CSV",
                        on_click=lambda: ui.download(
                            report_as_csv(report).encode("utf-8"),
                            "agreement_v5.csv",
                            "text/csv; charset=utf-8",
                        ),
                    ).props("outline")
                pair = _selected_pair(report)
                if pair is not None:
                    with ui.row().classes("w-full gap-2 flex-wrap"):
                        _render_metric("Span precision", _percent(pair.precision))
                        _render_metric("Span recall", _percent(pair.recall))
                        _render_metric("Span F1", _percent(pair.f1))
                        _render_metric(
                            "Categorical", _percent(pair.categorical_agreement)
                        )
                    _render_pair_detail(report, pair)

        _render_sources()
        _render_report()
        status.set_text("Add at least two valid exports to compare.")
