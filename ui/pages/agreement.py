from __future__ import annotations

from pathlib import Path

from nicegui import ui

from auth.service import require_auth_or_redirect
from auth.views import top_nav
from domain.agreement_service import (
    AgreementCluster,
    AgreementReport,
    AgreementRules,
    AgreementSource,
    NormalizedAnnotation,
    build_agreement_report,
    load_agreement_export,
)
from domain.transcript_service import load_transcript


def render_agreement_page() -> None:
    if not require_auth_or_redirect():
        return

    sources: list[AgreementSource] = []

    top_nav()
    with ui.column().classes("w-full max-w-6xl mx-auto mt-8 gap-4"):
        with ui.row().classes("w-full items-center justify-between"):
            with ui.column().classes("gap-1"):
                ui.label("Agreement Tool").classes("text-2xl font-semibold")
                ui.label(
                    "Upload exported analysis JSON files and compare coding overlap. "
                    "This does not import or change stored analyses."
                ).classes("text-sm text-gray-700")
            ui.button("Back to dashboard", on_click=lambda: ui.navigate.to("/")).props("flat")

        status = ui.label("").classes("text-sm text-gray-700")
        upload_status = ui.label("").classes("text-sm text-gray-700")

        sources_container = ui.column().classes("w-full gap-2")
        report_container = ui.column().classes("w-full gap-4")

        with ui.card().classes("w-full shadow-sm gap-2"):
            ui.label("Upload Exported Analyses").classes("font-medium")
            ui.label(
                "Use JSON files created by the analysis export button. Files stay in memory for this page only."
            ).classes("text-xs text-gray-600")

            async def on_upload(event) -> None:
                raw_name = getattr(event.file, "name", "") or "agreement-export.json"
                filename = Path(raw_name).name
                try:
                    text = await event.file.text()
                    source = load_agreement_export(
                        text,
                        source_name=filename,
                        source_index=len(sources),
                    )
                except Exception as exc:
                    upload_status.set_text(f"Rejected {filename}: {exc}")
                    return
                sources.append(source)
                upload_status.set_text(
                    f"Loaded {filename}: {len(source.codings)} codings, "
                    f"{len(source.annotations)} field-span annotations."
                )
                redraw()

            def clear_sources() -> None:
                sources.clear()
                upload_status.set_text("Cleared uploaded exports.")
                redraw()

            with ui.row().classes("items-center gap-2"):
                ui.upload(
                    label="Drop exported analysis JSON files or click to upload",
                    multiple=True,
                    on_upload=on_upload,
                    auto_upload=True,
                ).props('accept=".json"').classes("grow")
                ui.button("Clear", on_click=clear_sources).props("outline")

        with ui.card().classes("w-full shadow-sm gap-3"):
            ui.label("Matching Rules").classes("font-medium")
            with ui.row().classes("w-full gap-6 items-start"):
                span_mode = ui.radio(
                    {
                        "partial": "Partial span overlap",
                        "exact": "Exact same span",
                    },
                    value="partial",
                    on_change=lambda _e: redraw_report(),
                ).props("inline")
                field_mode = ui.radio(
                    {
                        "normalized": "Same field kind",
                        "exact": "Exact field path",
                        "ignore": "Ignore fields",
                    },
                    value="normalized",
                    on_change=lambda _e: redraw_report(),
                ).props("inline")
                same_object_type = ui.switch(
                    "Require same object type",
                    value=True,
                    on_change=lambda _e: redraw_report(),
                )
                show_full_transcript = ui.switch(
                    "Show full transcript",
                    value=False,
                    on_change=lambda _e: redraw_report(),
                )

            ui.label(
                "Same field kind ignores embedded list indexes, so perspectives_extract[0] and "
                "perspectives_extract[2] can match if the field meaning is the same."
            ).classes("text-xs text-gray-600")

        def current_rules() -> AgreementRules:
            return AgreementRules(
                span_mode=span_mode.value,
                field_mode=field_mode.value,
                require_same_object_type=bool(same_object_type.value),
            )

        def redraw_sources() -> None:
            sources_container.clear()
            with sources_container:
                if not sources:
                    ui.label("No agreement exports loaded.").classes("text-sm text-gray-600")
                    return
                with ui.card().classes("w-full shadow-sm gap-2"):
                    ui.label("Loaded Exports").classes("font-medium")
                    for source in sources:
                        with ui.row().classes("w-full items-center justify-between gap-3"):
                            ui.label(f"{source.label} ({source.source_name})").classes("font-medium")
                            ui.label(
                                f"{len(source.analyses)} analyses, {len(source.codings)} codings, "
                                f"{len(source.annotations)} annotations"
                            ).classes("text-sm text-gray-600")
                        for warning in source.warnings[:3]:
                            ui.label(f"Warning: {warning}").classes("text-xs text-orange-700")
                        if len(source.warnings) > 3:
                            ui.label(f"+{len(source.warnings) - 3} more warnings").classes(
                                "text-xs text-orange-700"
                            )

        def redraw_report() -> None:
            report_container.clear()
            if not sources:
                status.set_text("Upload at least two exported analyses to compare agreement.")
                return
            if len(sources) < 2:
                status.set_text("One export loaded. Upload at least one more exported analysis.")
                return

            report = build_agreement_report(sources, current_rules())
            status.set_text(
                f"Compared {len(report.sources)} exports, {report.total_annotations} annotations, "
                f"{len(report.clusters)} agreement clusters."
            )
            with report_container:
                _render_summary(report)
                _render_pair_table(report)
                _render_agreement_grid(report, show_full_transcript=bool(show_full_transcript.value))
                _render_cluster_table(report)

        def redraw() -> None:
            redraw_sources()
            redraw_report()

        redraw()


def _render_summary(report: AgreementReport) -> None:
    source_count = len(report.sources)
    with ui.card().classes("w-full shadow-sm gap-2"):
        ui.label("Summary").classes("font-medium")
        with ui.row().classes("flex-wrap gap-3"):
            _metric("Exports", str(source_count))
            _metric("Annotations", str(report.total_annotations))
            _metric("Clusters", str(len(report.clusters)))
            _metric("Full agreement", f"{report.full_agreement_clusters}/{len(report.clusters)}")
        ui.label(
            "Full agreement means at least one matching annotation from every uploaded export is present "
            "in the same cluster."
        ).classes("text-xs text-gray-600")


def _render_pair_table(report: AgreementReport) -> None:
    with ui.card().classes("w-full shadow-sm gap-2"):
        ui.label("Pairwise Agreement").classes("font-medium")
        rows = [
            {
                "pair": f"{pair.left_label} <-> {pair.right_label}",
                "overlap": pair.overlap_clusters,
                "union": pair.union_clusters,
                "score": f"{pair.score:.1%}",
                "tp": pair.true_positives,
                "fp": pair.false_positives,
                "fn": pair.false_negatives,
                "precision": f"{pair.precision:.1%}",
                "recall": f"{pair.recall:.1%}",
                "f1": f"{pair.f1:.1%}",
            }
            for pair in report.pair_agreements
        ]
        ui.table(
            columns=[
                {"name": "pair", "label": "Pair", "field": "pair", "align": "left"},
                {"name": "overlap", "label": "Overlap clusters", "field": "overlap", "align": "right"},
                {"name": "union", "label": "Union clusters", "field": "union", "align": "right"},
                {"name": "score", "label": "Cluster score", "field": "score", "align": "right"},
                {"name": "tp", "label": "TP", "field": "tp", "align": "right"},
                {"name": "fp", "label": "FP", "field": "fp", "align": "right"},
                {"name": "fn", "label": "FN", "field": "fn", "align": "right"},
                {"name": "precision", "label": "Precision", "field": "precision", "align": "right"},
                {"name": "recall", "label": "Recall", "field": "recall", "align": "right"},
                {"name": "f1", "label": "F1", "field": "f1", "align": "right"},
            ],
            rows=rows,
        ).classes("w-full")
        ui.label(
            "F1 uses one-to-one annotation matching under the current matching rules, so duplicate overlaps "
            "are not double-counted."
        ).classes("text-xs text-gray-600")


def _render_agreement_grid(report: AgreementReport, *, show_full_transcript: bool) -> None:
    transcript_context = _load_transcript_context(report)
    annotation_clusters = _annotation_cluster_map(report)
    row_segment_ids = _grid_segment_ids(report, transcript_context, show_full_transcript=show_full_transcript)
    source_labels = {
        source.source_index: f"{source.label} ({source.source_name})"
        for source in report.sources
    }
    annotations_by_source_and_segment = _annotations_by_source_and_segment(
        report,
        row_segment_ids=row_segment_ids,
        segment_order=transcript_context["segment_order"],
    )

    with ui.card().classes("w-full shadow-sm gap-3"):
        ui.label("Transcript-Aligned Agreement").classes("font-medium")
        if transcript_context["missing_files"]:
            ui.label(
                "Missing local transcript files: " + ", ".join(transcript_context["missing_files"])
            ).classes("text-xs text-orange-700")
        if not row_segment_ids:
            ui.label("No span annotations available to visualize.").classes("text-sm text-gray-600")
            return

        ui.label(
            "Rows are transcript segments. Columns are uploaded exports. Cards show annotations that touch "
            "that segment under the current matching rules."
        ).classes("text-xs text-gray-600")

        column_count = len(report.sources) + 1
        grid_template = "minmax(320px, 1.25fr) " + " ".join(
            "minmax(220px, 1fr)" for _source in report.sources
        )
        with ui.element("div").classes("w-full overflow-auto border rounded"):
            with ui.element("div").style(
                f"display: grid; grid-template-columns: {grid_template}; min-width: {320 + 240 * len(report.sources)}px;"
            ):
                ui.label("Transcript").classes(
                    "sticky left-0 z-20 bg-slate-100 font-semibold p-2 border-b border-r"
                )
                for source in report.sources:
                    ui.label(source_labels[source.source_index]).classes("bg-slate-100 font-semibold p-2 border-b")

                for segment_id in row_segment_ids:
                    _render_transcript_cell(segment_id, transcript_context)
                    for source in report.sources:
                        annotations = annotations_by_source_and_segment.get(
                            (source.source_index, segment_id),
                            [],
                        )
                        _render_annotation_cell(
                            annotations,
                            annotation_clusters=annotation_clusters,
                            source_count=len(report.sources),
                        )


def _render_cluster_table(report: AgreementReport) -> None:
    source_labels = {source.source_index: f"{source.label} ({source.source_name})" for source in report.sources}
    rows = []
    for cluster in report.clusters[:250]:
        present = [source_labels[index] for index in sorted(cluster.present_source_indices)]
        missing = [source_labels[index] for index in sorted(cluster.missing_source_indices)]
        annotations = cluster.annotations
        rows.append(
            {
                "cluster": cluster.cluster_id,
                "agreement": f"{len(cluster.present_source_indices)}/{len(report.sources)}",
                "present": "; ".join(present),
                "missing": "; ".join(missing) or "-",
                "object_type": ", ".join(cluster.object_types) or "-",
                "field": ", ".join(cluster.field_paths) or "-",
                "span": "; ".join(_annotation_span_label(a) for a in annotations[:4]),
                "text": _short_text(" | ".join(a.span.selected_text for a in annotations if a.span.selected_text)),
            }
        )

    with ui.card().classes("w-full shadow-sm gap-2"):
        ui.label("Agreement Clusters").classes("font-medium")
        if len(report.clusters) > 250:
            ui.label(f"Showing first 250 of {len(report.clusters)} clusters.").classes("text-xs text-gray-600")
        ui.table(
            columns=[
                {"name": "cluster", "label": "#", "field": "cluster", "align": "right"},
                {"name": "agreement", "label": "Agreement", "field": "agreement", "align": "left"},
                {"name": "present", "label": "Present", "field": "present", "align": "left"},
                {"name": "missing", "label": "Missing", "field": "missing", "align": "left"},
                {"name": "object_type", "label": "Object", "field": "object_type", "align": "left"},
                {"name": "field", "label": "Field", "field": "field", "align": "left"},
                {"name": "span", "label": "Spans", "field": "span", "align": "left"},
                {"name": "text", "label": "Selected text", "field": "text", "align": "left"},
            ],
            rows=rows,
        ).classes("w-full")


def _metric(label: str, value: str) -> None:
    with ui.card().classes("min-w-36 bg-slate-50 shadow-none"):
        ui.label(value).classes("text-xl font-semibold")
        ui.label(label).classes("text-xs text-gray-600")


def _annotation_span_label(annotation) -> str:
    return f"{annotation.source_label} ({annotation.source_name}): {annotation.span.range_label}"


def _load_transcript_context(report: AgreementReport) -> dict:
    interview_files = sorted(
        {
            annotation.interview_file
            for source in report.sources
            for annotation in source.annotations
            if annotation.interview_file
        }
    )
    segment_text: dict[tuple[str, str], str] = {}
    segment_order: dict[str, int] = {}
    ordered_segments: list[str] = []
    missing_files: list[str] = []

    for interview_file in interview_files:
        try:
            transcript = load_transcript(interview_file)
        except FileNotFoundError:
            missing_files.append(interview_file)
            continue
        for segment in transcript.segments:
            key = (interview_file, segment.segment_id)
            segment_text[key] = segment.text
            segment_order.setdefault(segment.segment_id, segment.index)
            if segment.segment_id not in ordered_segments:
                ordered_segments.append(segment.segment_id)

    return {
        "segment_text": segment_text,
        "segment_order": segment_order,
        "ordered_segments": sorted(ordered_segments, key=lambda sid: _segment_sort_key(sid, segment_order)),
        "missing_files": missing_files,
    }


def _annotation_cluster_map(report: AgreementReport) -> dict[tuple[int, int], AgreementCluster]:
    out = {}
    for cluster in report.clusters:
        for annotation in cluster.annotations:
            out[(annotation.source_index, annotation.annotation_id)] = cluster
    return out


def _grid_segment_ids(
    report: AgreementReport,
    transcript_context: dict,
    *,
    show_full_transcript: bool,
) -> list[str]:
    if show_full_transcript and transcript_context["ordered_segments"]:
        return transcript_context["ordered_segments"]

    ids: set[str] = set()
    segment_order = transcript_context["segment_order"]
    for source in report.sources:
        for annotation in source.annotations:
            ids.update(_segment_ids_for_annotation(annotation, segment_order))
    return sorted(ids, key=lambda sid: _segment_sort_key(sid, segment_order))


def _annotations_by_source_and_segment(
    report: AgreementReport,
    *,
    row_segment_ids: list[str],
    segment_order: dict[str, int],
) -> dict[tuple[int, str], list[NormalizedAnnotation]]:
    visible_segments = set(row_segment_ids)
    out: dict[tuple[int, str], list[NormalizedAnnotation]] = {}
    for source in report.sources:
        for annotation in source.annotations:
            for segment_id in _segment_ids_for_annotation(annotation, segment_order):
                if segment_id not in visible_segments:
                    continue
                out.setdefault((source.source_index, segment_id), []).append(annotation)
    for annotations in out.values():
        annotations.sort(key=lambda a: (a.span.start_char_offset, a.object_type, a.normalized_field_path))
    return out


def _segment_ids_for_annotation(annotation: NormalizedAnnotation, segment_order: dict[str, int]) -> list[str]:
    start = annotation.span.start_segment_id
    end = annotation.span.end_segment_id
    if start == end:
        return [start]
    start_order = segment_order.get(start, _segment_sort_key(start, segment_order)[0])
    end_order = segment_order.get(end, _segment_sort_key(end, segment_order)[0])
    if start_order > end_order:
        start_order, end_order = end_order, start_order
    covered = [
        segment_id
        for segment_id, order in segment_order.items()
        if start_order <= order <= end_order
    ]
    if covered:
        return sorted(covered, key=lambda sid: _segment_sort_key(sid, segment_order))
    return [start, end]


def _render_transcript_cell(segment_id: str, transcript_context: dict) -> None:
    texts = [
        text
        for (_interview_file, current_segment_id), text in transcript_context["segment_text"].items()
        if current_segment_id == segment_id
    ]
    text = texts[0] if texts else ""
    with ui.element("div").classes("sticky left-0 z-10 bg-white p-2 border-b border-r min-h-20"):
        ui.label(segment_id).classes("text-xs font-semibold text-slate-600")
        ui.label(_short_text(text, 320) if text else "Transcript text unavailable").classes(
            "text-sm whitespace-normal"
        )


def _render_annotation_cell(
    annotations: list[NormalizedAnnotation],
    *,
    annotation_clusters: dict[tuple[int, int], AgreementCluster],
    source_count: int,
) -> None:
    with ui.element("div").classes("p-2 border-b min-h-20 bg-slate-50/40"):
        if not annotations:
            ui.label("-").classes("text-xs text-gray-400")
            return
        for annotation in annotations:
            cluster = annotation_clusters.get((annotation.source_index, annotation.annotation_id))
            status_class = _cluster_status_class(cluster, source_count)
            agreement_label = _cluster_agreement_label(cluster, source_count)
            with ui.element("div").classes(f"rounded border p-2 mb-2 text-xs {status_class}"):
                with ui.row().classes("w-full items-center justify-between gap-2"):
                    ui.label(annotation.object_type or "unknown").classes("font-semibold")
                    ui.label(agreement_label).classes("text-[11px]")
                ui.label(_short_field(annotation.normalized_field_path)).classes("text-[11px] text-slate-700")
                ui.label(annotation.span.range_label).classes("text-[11px] text-slate-500")
                if annotation.span.selected_text:
                    ui.label(_short_text(annotation.span.selected_text, 140)).classes("text-xs")


def _cluster_status_class(cluster: AgreementCluster | None, source_count: int) -> str:
    if cluster is None or len(cluster.present_source_indices) <= 1:
        return "bg-gray-50 border-gray-300 text-gray-800"
    if len(cluster.present_source_indices) == source_count:
        return "bg-emerald-50 border-emerald-400 text-emerald-950"
    return "bg-sky-50 border-sky-400 text-sky-950"


def _cluster_agreement_label(cluster: AgreementCluster | None, source_count: int) -> str:
    if cluster is None:
        return "unique"
    present = len(cluster.present_source_indices)
    if present <= 1:
        return f"{present}/{source_count}"
    if present == source_count:
        return f"{present}/{source_count} full"
    return f"{present}/{source_count} shared"


def _short_field(field_path: str) -> str:
    if not field_path:
        return "-"
    prefixes = {
        "comparison.": "cmp.",
        "differentiation.": "diff.",
        "nuance.": "nu.",
    }
    for prefix, short in prefixes.items():
        if field_path.startswith(prefix):
            field_path = short + field_path[len(prefix) :]
            break
    return _short_text(field_path, 90)


def _segment_sort_key(segment_id: str, segment_order: dict[str, int]) -> tuple[int, str]:
    if segment_id in segment_order:
        return (segment_order[segment_id], segment_id)
    digits = "".join(ch for ch in segment_id if ch.isdigit())
    if digits:
        return (int(digits), segment_id)
    return (10**9, segment_id)


def _short_text(value: str, limit: int = 180) -> str:
    value = " ".join((value or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "..."
