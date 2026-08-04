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
    IGNORED_AGREEMENT_FIELD_PATHS,
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
                mermaid_full_text = ui.switch(
                    "Mermaid full text",
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
                status.set_text("Upload an exported analysis to visualize it, or upload two or more to compare agreement.")
                return

            report = build_agreement_report(sources, current_rules())
            if len(sources) == 1:
                status.set_text(
                    f"Loaded 1 export with {report.total_annotations} annotations. "
                    "Upload another exported analysis to compare agreement."
                )
            else:
                status.set_text(
                    f"Compared {len(report.sources)} exports, {report.total_annotations} annotations, "
                    f"{len(report.clusters)} agreement clusters."
            )
            with report_container:
                _render_summary(report)
                _render_coding_object_view(report)
                _render_field_confusion_matrix(report)
                _render_mermaid_visualizations(report, full_text=bool(mermaid_full_text.value))
                _render_agreement_grid(report, show_full_transcript=bool(show_full_transcript.value))
                if len(report.sources) >= 2:
                    _render_pair_table(report)
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
            _metric("Coding objects", str(sum(len(source.codings) for source in report.sources)))
            if source_count >= 2:
                _metric("Clusters", str(len(report.clusters)))
                _metric("Full agreement", f"{report.full_agreement_clusters}/{len(report.clusters)}")
        if source_count >= 2:
            ui.label(
                "Full agreement means at least one matching annotation from every uploaded export is present "
                "in the same cluster."
            ).classes("text-xs text-gray-600")
        else:
            ui.label("Single-export mode shows analysis structure and transcript-aligned annotations.").classes(
                "text-xs text-gray-600"
            )


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
                "root_splits": pair.graph_diagnostics.root_splits,
                "root_merges": pair.graph_diagnostics.root_merges,
                "embedded_splits": pair.graph_diagnostics.embedded_splits,
                "embedded_merges": pair.graph_diagnostics.embedded_merges,
                "graph_issues": pair.graph_diagnostics.total_issues,
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
                {"name": "graph_issues", "label": "Graph issues", "field": "graph_issues", "align": "right"},
                {"name": "root_splits", "label": "Root splits", "field": "root_splits", "align": "right"},
                {"name": "root_merges", "label": "Root merges", "field": "root_merges", "align": "right"},
                {
                    "name": "embedded_splits",
                    "label": "Embedded splits",
                    "field": "embedded_splits",
                    "align": "right",
                },
                {
                    "name": "embedded_merges",
                    "label": "Embedded merges",
                    "field": "embedded_merges",
                    "align": "right",
                },
            ],
            rows=rows,
        ).classes("w-full")
        ui.label(
            "F1 uses one-to-one annotation matching under the current matching rules, so duplicate overlaps "
            "are not double-counted."
        ).classes("text-xs text-gray-600")
        graph_warnings = [
            f"{pair.left_label} <-> {pair.right_label}: {warning}"
            for pair in report.pair_agreements
            for warning in pair.graph_diagnostics.warnings
        ]
        if graph_warnings:
            with ui.expansion("Graph connection diagnostics", icon="account_tree").classes("w-full"):
                ui.label(
                    "These warnings mean annotations can match by span/field while being connected to different "
                    "root or embedded coding objects."
                ).classes("text-xs text-gray-600")
                for warning in graph_warnings[:40]:
                    ui.label(warning).classes("text-xs text-orange-800")
                if len(graph_warnings) > 40:
                    ui.label(f"+{len(graph_warnings) - 40} more graph warnings").classes(
                        "text-xs text-orange-800"
                    )


def _render_coding_object_view(report: AgreementReport) -> None:
    agreed_paths = _agreed_field_paths_by_coding(report)
    with ui.card().classes("w-full shadow-sm gap-3"):
        ui.label("Coding Object Agreement").classes("font-medium")
        ui.label(
            "Schema-style read-only view of each coding object. Green lines have agreement under the current "
            "matching rules; gray lines do not."
        ).classes("text-xs text-gray-600")

        if len(report.sources) < 2:
            ui.label("Upload at least two exports to mark fields as agreed.").classes("text-xs text-gray-600")

        for source in report.sources:
            with ui.expansion(
                f"{source.label} ({source.source_name})",
                icon="data_object",
                value=True,
            ).classes("w-full"):
                if not source.codings:
                    ui.label("No coding objects in this export.").classes("text-sm text-gray-600")
                    continue
                for coding_index, coding in enumerate(source.codings, start=1):
                    object_type, payload = _coding_payload(coding)
                    root_key = _coding_root_key(coding, coding_index)
                    field_paths = agreed_paths.get((source.source_index, root_key), set())
                    agreed_count = _count_agreed_payload_fields(payload, object_type, field_paths)
                    field_count = _count_payload_fields(payload)
                    title = f"{coding_index}. {object_type or 'coding object'}"
                    if coding.segment_id:
                        title += f" ({coding.segment_id})"
                    with ui.expansion(
                        f"{title} - {agreed_count}/{field_count} agreed",
                        icon="schema",
                    ).classes("w-full"):
                        if not payload:
                            ui.label("No text fields found for this coding object.").classes(
                                "text-sm text-gray-600"
                            )
                            continue
                        _render_schema_object(
                            object_type or "coding",
                            object_type or "coding",
                            payload,
                            agreed_field_paths=field_paths,
                            depth=0,
                        )


def _agreed_field_paths_by_coding(report: AgreementReport) -> dict[tuple[int, str], set[str]]:
    agreed: dict[tuple[int, str], set[str]] = {}
    for cluster in report.clusters:
        if len(cluster.present_source_indices) <= 1:
            continue
        for annotation in cluster.annotations:
            key = (annotation.source_index, annotation.root_object_key)
            agreed.setdefault(key, set()).add(annotation.field_path)
    return agreed


def _coding_payload(coding) -> tuple[str, dict]:
    dumped = coding.model_dump(mode="json", exclude_none=True)
    object_type = str(dumped.get("object_type") or "")
    if object_type and isinstance(dumped.get(object_type), dict):
        return object_type, _agreement_visible_payload(object_type, dumped[object_type])
    for candidate in ("comparison", "differentiation", "nuance"):
        if isinstance(dumped.get(candidate), dict):
            return candidate, _agreement_visible_payload(candidate, dumped[candidate])
    return object_type or "coding", {}


def _agreement_visible_payload(object_type: str, payload: dict) -> dict:
    visible = dict(payload)
    prefix = f"{object_type}."
    for field_path in IGNORED_AGREEMENT_FIELD_PATHS:
        if field_path.startswith(prefix):
            visible.pop(field_path[len(prefix) :], None)
    return visible


def _coding_root_key(coding, fallback_index: int) -> str:
    if coding.coding_id:
        return coding.coding_id
    return f"{coding.object_type or 'coding'}:{fallback_index}"


def _render_field_confusion_matrix(report: AgreementReport) -> None:
    if len(report.sources) != 2:
        return

    left, right = report.sources
    matrix = _field_confusion_counts(report)
    row_labels = _sorted_confusion_labels(matrix["rows"], missing_label=matrix["missing_left"])
    column_labels = _sorted_confusion_labels(matrix["columns"], missing_label=matrix["missing_right"])

    with ui.card().classes("w-full shadow-sm gap-3"):
        ui.label("Field-Type Confusion Matrix").classes("font-medium")
        ui.label(
            "Rows are field types from the first export; columns are field types from the second export. "
            "Matching here uses span overlap only under the current span mode, ignoring object graph and field agreement."
        ).classes("text-xs text-gray-600")
        ui.label(
            f"Vertical rows: {left.label} ({left.source_name}). "
            f"Horizontal columns: {right.label} ({right.source_name})."
        ).classes("text-xs text-gray-600")
        with ui.row().classes("flex-wrap gap-3"):
            _metric("Matched spans", str(matrix["matched"]))
            _metric("Unmatched first", str(matrix["unmatched_left"]))
            _metric("Unmatched second", str(matrix["unmatched_right"]))
            _metric("Off diagonal", str(matrix["off_diagonal"]))

        max_count = max(matrix["counts"].values(), default=0)
        ui.label(
            "Cell color scales by count. Green is same field type; orange is a field-type confusion; "
            "gray is unmatched/missing."
        ).classes("text-xs text-gray-600")
        _render_confusion_heatmap(
            matrix,
            row_labels=row_labels,
            column_labels=column_labels,
            left_label=left.label,
            right_label=right.label,
            max_count=max_count,
        )

        if matrix["confusions"]:
            with ui.expansion("Off-diagonal examples", icon="warning").classes("w-full"):
                for left_field, right_field, count in matrix["confusions"][:30]:
                    ui.label(f"{count}: {left_field} -> {right_field}").classes("text-xs text-orange-800")
                if len(matrix["confusions"]) > 30:
                    ui.label(f"+{len(matrix['confusions']) - 30} more").classes("text-xs text-orange-800")


def _render_confusion_heatmap(
    matrix: dict,
    *,
    row_labels: list[str],
    column_labels: list[str],
    left_label: str,
    right_label: str,
    max_count: int,
) -> None:
    grid_template = "minmax(320px, 1.5fr) minmax(72px, 0.4fr) " + " ".join(
        "minmax(130px, 0.8fr)" for _column in column_labels
    )
    with ui.element("div").classes("w-full overflow-auto border rounded"):
        with ui.element("div").style(
            f"display: grid; grid-template-columns: {grid_template}; min-width: {520 + 140 * len(column_labels)}px;"
        ):
            ui.label(f"Vertical: {left_label} field").classes(
                "sticky left-0 z-20 bg-slate-100 font-semibold p-2 border-b border-r text-xs"
            )
            ui.label("Total").classes("bg-slate-100 font-semibold p-2 border-b border-r text-xs text-right")
            for column_label in column_labels:
                ui.label(f"Horizontal: {right_label}\n{column_label}").classes(
                    "bg-slate-100 font-semibold p-2 border-b border-r text-[11px] break-words"
                )

            for row_label in row_labels:
                row_total = sum(matrix["counts"].get((row_label, column_label), 0) for column_label in column_labels)
                ui.label(row_label).classes(
                    "sticky left-0 z-10 bg-white p-2 border-b border-r text-[11px] break-words"
                )
                ui.label(str(row_total)).classes("p-2 border-b border-r text-xs text-right font-semibold bg-slate-50")
                for column_label in column_labels:
                    count = matrix["counts"].get((row_label, column_label), 0)
                    style = _confusion_cell_style(
                        count,
                        max_count=max_count,
                        row_label=row_label,
                        column_label=column_label,
                        missing_left=matrix["missing_left"],
                        missing_right=matrix["missing_right"],
                    )
                    with ui.element("div").classes("p-2 border-b border-r text-center text-xs").style(style):
                        if count:
                            ui.label(str(count)).classes("font-semibold")
                        else:
                            ui.label("").classes("text-gray-300")


def _confusion_cell_style(
    count: int,
    *,
    max_count: int,
    row_label: str,
    column_label: str,
    missing_left: str,
    missing_right: str,
) -> str:
    if count <= 0 or max_count <= 0:
        return "background: #ffffff;"
    intensity = count / max_count
    alpha = 0.12 + (0.60 * intensity)
    if row_label == missing_left or column_label == missing_right:
        color = f"rgba(100, 116, 139, {alpha:.2f})"
    elif row_label == column_label:
        color = f"rgba(16, 185, 129, {alpha:.2f})"
    else:
        color = f"rgba(249, 115, 22, {alpha:.2f})"
    return f"background: {color};"


def _field_confusion_counts(report: AgreementReport) -> dict:
    left, right = report.sources
    missing_left = f"missing in {left.label}"
    missing_right = f"missing in {right.label}"
    matches = _span_only_annotation_matches(left.annotations, right.annotations, span_mode=report.rules.span_mode)
    matched_left = {left_index for _quality, left_index, _right_index in matches}
    matched_right = {right_index for _quality, _left_index, right_index in matches}
    counts: dict[tuple[str, str], int] = {}

    for _quality, left_index, right_index in matches:
        left_field = left.annotations[left_index].normalized_field_path
        right_field = right.annotations[right_index].normalized_field_path
        counts[(left_field, right_field)] = counts.get((left_field, right_field), 0) + 1

    for left_index, annotation in enumerate(left.annotations):
        if left_index in matched_left:
            continue
        left_field = annotation.normalized_field_path
        counts[(left_field, missing_right)] = counts.get((left_field, missing_right), 0) + 1

    for right_index, annotation in enumerate(right.annotations):
        if right_index in matched_right:
            continue
        right_field = annotation.normalized_field_path
        counts[(missing_left, right_field)] = counts.get((missing_left, right_field), 0) + 1

    rows = {row for row, _column in counts}
    columns = {column for _row, column in counts}
    confusions = sorted(
        [
            (row, column, count)
            for (row, column), count in counts.items()
            if row != missing_left and column != missing_right and row != column
        ],
        key=lambda item: (-item[2], item[0], item[1]),
    )
    return {
        "counts": counts,
        "rows": rows,
        "columns": columns,
        "missing_left": missing_left,
        "missing_right": missing_right,
        "matched": len(matches),
        "unmatched_left": len(left.annotations) - len(matched_left),
        "unmatched_right": len(right.annotations) - len(matched_right),
        "off_diagonal": sum(count for _row, _column, count in confusions),
        "confusions": confusions,
    }


def _span_only_annotation_matches(
    left_annotations: list[NormalizedAnnotation],
    right_annotations: list[NormalizedAnnotation],
    *,
    span_mode: str,
) -> list[tuple[float, int, int]]:
    candidates: list[tuple[float, int, int]] = []
    for left_index, left in enumerate(left_annotations):
        for right_index, right in enumerate(right_annotations):
            if left.interview_file and right.interview_file and left.interview_file != right.interview_file:
                continue
            quality = _span_match_quality(left, right, span_mode=span_mode)
            if quality <= 0:
                continue
            candidates.append((quality, left_index, right_index))

    candidates.sort(reverse=True)
    matched_left: set[int] = set()
    matched_right: set[int] = set()
    matches: list[tuple[float, int, int]] = []
    for quality, left_index, right_index in candidates:
        if left_index in matched_left or right_index in matched_right:
            continue
        matched_left.add(left_index)
        matched_right.add(right_index)
        matches.append((quality, left_index, right_index))
    return matches


def _span_match_quality(
    left: NormalizedAnnotation,
    right: NormalizedAnnotation,
    *,
    span_mode: str,
) -> float:
    if span_mode == "exact":
        return 1.0 if _same_span_coordinates(left, right) else 0.0
    return _span_overlap_ratio_for_matrix(left, right)


def _same_span_coordinates(left: NormalizedAnnotation, right: NormalizedAnnotation) -> bool:
    return (
        left.span.start_segment_id == right.span.start_segment_id
        and left.span.start_char_offset == right.span.start_char_offset
        and left.span.end_segment_id == right.span.end_segment_id
        and left.span.end_char_offset == right.span.end_char_offset
    )


def _span_overlap_ratio_for_matrix(left: NormalizedAnnotation, right: NormalizedAnnotation) -> float:
    left_start = _span_matrix_point(left.span.start_segment_id, left.span.start_char_offset)
    left_end = _span_matrix_point(left.span.end_segment_id, left.span.end_char_offset)
    right_start = _span_matrix_point(right.span.start_segment_id, right.span.start_char_offset)
    right_end = _span_matrix_point(right.span.end_segment_id, right.span.end_char_offset)

    if left_start > left_end:
        left_start, left_end = left_end, left_start
    if right_start > right_end:
        right_start, right_end = right_end, right_start

    overlap_start = max(left_start, right_start)
    overlap_end = min(left_end, right_end)
    if overlap_start >= overlap_end:
        return 0.0

    overlap = _span_matrix_distance(overlap_start, overlap_end)
    union = _span_matrix_distance(min(left_start, right_start), max(left_end, right_end))
    return (overlap / union) if union else 0.0


def _span_matrix_point(segment_id: str, char_offset: int) -> tuple[int, str, int]:
    digits = "".join(ch for ch in str(segment_id) if ch.isdigit())
    segment_order = int(digits) if digits else 0
    return (segment_order, str(segment_id), int(char_offset))


def _span_matrix_distance(left: tuple[int, str, int], right: tuple[int, str, int]) -> int:
    if left[0] == right[0] and left[1] == right[1]:
        return max(0, right[2] - left[2])
    return 1


def _sorted_confusion_labels(labels: set[str], *, missing_label: str) -> list[str]:
    return sorted(labels, key=lambda label: (label != missing_label, label))


def _confusion_column_key(label: str) -> str:
    return "c_" + "".join(ch if ch.isalnum() else "_" for ch in label)


def _render_schema_object(
    title: str,
    path: str,
    payload: dict,
    *,
    agreed_field_paths: set[str],
    depth: int,
) -> None:
    has_agreement = _path_has_agreement(path, agreed_field_paths)
    with ui.element("div").classes(
        f"rounded border p-2 mb-2 font-mono text-xs {_schema_status_class(has_agreement)}"
    ).style(f"margin-left: {depth * 14}px;"):
        with ui.row().classes("w-full items-center justify-between gap-2"):
            ui.label(f"{title} {{").classes("font-semibold")
            ui.label("agree" if has_agreement else "not agreed").classes(
                "text-[10px] uppercase tracking-wide"
            )
        rendered_any = False
        for field_name, value in payload.items():
            if _schema_value_is_empty(value):
                continue
            child_path = f"{path}.{field_name}" if path else field_name
            rendered_any = True
            _render_schema_value(
                field_name,
                child_path,
                value,
                agreed_field_paths=agreed_field_paths,
                depth=depth + 1,
            )
        if not rendered_any:
            ui.label("  empty").classes("text-slate-500")
        ui.label("}").classes("font-semibold")


def _render_schema_value(
    field_name: str,
    path: str,
    value,
    *,
    agreed_field_paths: set[str],
    depth: int,
) -> None:
    if isinstance(value, dict):
        _render_schema_object(
            field_name,
            path,
            value,
            agreed_field_paths=agreed_field_paths,
            depth=depth,
        )
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            item_path = f"{path}[{index}]"
            if _schema_value_is_empty(item):
                continue
            if isinstance(item, dict):
                _render_schema_object(
                    f"{field_name}[{index}]",
                    item_path,
                    item,
                    agreed_field_paths=agreed_field_paths,
                    depth=depth,
                )
            else:
                _render_schema_field(
                    f"{field_name}[{index}]",
                    item_path,
                    item,
                    agreed_field_paths=agreed_field_paths,
                    depth=depth,
                )
        return
    _render_schema_field(
        field_name,
        path,
        value,
        agreed_field_paths=agreed_field_paths,
        depth=depth,
    )


def _render_schema_field(
    field_name: str,
    path: str,
    value,
    *,
    agreed_field_paths: set[str],
    depth: int,
) -> None:
    is_agreed = path in agreed_field_paths
    text = str(value)
    with ui.element("div").classes(
        f"rounded border px-2 py-1 my-1 {_schema_status_class(is_agreed)}"
    ).style(f"margin-left: {depth * 14}px;"):
        with ui.row().classes("w-full items-center justify-between gap-2"):
            ui.label(f"{field_name}:").classes("font-semibold")
            ui.label("agree" if is_agreed else "not agreed").classes("text-[10px] uppercase tracking-wide")
        ui.label(text).classes("whitespace-pre-wrap")


def _schema_status_class(is_agreed: bool) -> str:
    if is_agreed:
        return "bg-emerald-50 border-emerald-300 text-emerald-950"
    return "bg-slate-50 border-slate-200 text-slate-700"


def _schema_value_is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return all(_schema_value_is_empty(item) for item in value)
    if isinstance(value, dict):
        return all(_schema_value_is_empty(item) for item in value.values())
    return False


def _path_has_agreement(path: str, agreed_field_paths: set[str]) -> bool:
    return any(
        field_path == path
        or field_path.startswith(f"{path}.")
        or field_path.startswith(f"{path}[")
        for field_path in agreed_field_paths
    )


def _count_payload_fields(payload: dict) -> int:
    return sum(1 for _path, _value in _iter_payload_field_paths("", payload))


def _count_agreed_payload_fields(payload: dict, root_path: str, agreed_field_paths: set[str]) -> int:
    return sum(
        1
        for path, _value in _iter_payload_field_paths(root_path, payload)
        if path in agreed_field_paths
    )


def _iter_payload_field_paths(path: str, value):
    if _schema_value_is_empty(value):
        return
    if isinstance(value, dict):
        for field_name, child in value.items():
            child_path = f"{path}.{field_name}" if path else field_name
            yield from _iter_payload_field_paths(child_path, child)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            item_path = f"{path}[{index}]"
            yield from _iter_payload_field_paths(item_path, item)
        return
    yield path, value


def _render_mermaid_visualizations(report: AgreementReport, *, full_text: bool) -> None:
    has_agreement = len(report.sources) >= 2
    with ui.card().classes("w-full shadow-sm gap-3"):
        ui.label("Mermaid Visualizations").classes("font-medium")
        ui.label(
            "These diagrams are generated from the uploaded exports in memory. They are read-only views."
        ).classes("text-xs text-gray-600")
        mode = "full extracted text" if full_text else "compact readable labels"
        ui.label(f"Mermaid text mode: {mode}.").classes("text-xs text-gray-600")

        with ui.expansion("Individual analysis graph", icon="account_tree", value=True).classes("w-full"):
            ui.label(
                "Shows one exported analysis at a time as: analysis -> coding object -> embedded object -> annotation span."
            ).classes("text-xs text-gray-600")
            for source in report.sources:
                with ui.expansion(f"{source.label} ({source.source_name})", icon="description").classes("w-full"):
                    _render_mermaid(_individual_analysis_mermaid(source, full_text=full_text))

        if has_agreement:
            with ui.expansion("Agreement graph", icon="hub").classes("w-full"):
                ui.label(
                    "Shows matched annotation clusters across uploaded exports. Root coding objects still appear, "
                    "so split/merge patterns can be inspected visually."
                ).classes("text-xs text-gray-600")
                _render_mermaid(_agreement_graph_mermaid(report, full_text=full_text))

            with ui.expansion("Object mapping Sankey", icon="schema").classes("w-full"):
                ui.label(
                    "Shows pairwise object mappings used by graph diagnostics. Thick links mean more matched annotations "
                    "connect the same pair of coding/embedded objects."
                ).classes("text-xs text-gray-600")
                for pair in report.pair_agreements:
                    with ui.expansion(f"{pair.left_label} <-> {pair.right_label}", icon="compare_arrows").classes(
                        "w-full"
                    ):
                        root_code = _object_mapping_sankey(
                            pair.annotation_matches,
                            embedded=False,
                            full_text=full_text,
                        )
                        embedded_code = _object_mapping_sankey(
                            pair.annotation_matches,
                            embedded=True,
                            full_text=full_text,
                        )
                        if root_code:
                            ui.label("Root coding objects").classes("text-xs font-semibold text-gray-700")
                            _render_mermaid(root_code)
                        else:
                            ui.label("No root object matches for this pair.").classes("text-xs text-gray-600")
                        if embedded_code:
                            ui.label("Embedded list objects").classes("text-xs font-semibold text-gray-700")
                            _render_mermaid(embedded_code)
                        else:
                            ui.label("No embedded object matches for this pair.").classes("text-xs text-gray-600")


def _render_mermaid(code: str) -> None:
    width, height = _mermaid_dimensions(code)
    with ui.element("div").classes("w-full overflow-auto border rounded bg-white p-2"):
        ui.mermaid(
            code,
            config={
                "maxTextSize": 2_000_000,
                "flowchart": {"htmlLabels": True},
            },
        ).style(f"min-width: {width}px; min-height: {height}px;")


def _individual_analysis_mermaid(source: AgreementSource, *, full_text: bool) -> str:
    lines = [
        "flowchart LR",
        "classDef analysis fill:#f8fafc,stroke:#334155,stroke-width:2px,color:#0f172a;",
        "classDef coding fill:#ecfeff,stroke:#0891b2,stroke-width:1.5px,color:#164e63;",
        "classDef embedded fill:#fff7ed,stroke:#f97316,stroke-width:1.5px,color:#7c2d12;",
        "classDef annotation fill:#f0fdf4,stroke:#22c55e,color:#14532d;",
    ]
    analysis = source.analyses[0] if source.analyses else None
    analysis_node = _mermaid_node_id("analysis", source.source_index, 0)
    source_subtitle = source.source_name
    if analysis and analysis.name:
        source_subtitle = f"{analysis.name} ({source.source_name})"
    lines.append(
        f'{analysis_node}["{_mermaid_label(source.label or "Unknown coder", source_subtitle, full_text=full_text)}"]'
    )
    lines.append(f"class {analysis_node} analysis;")

    annotations_by_root: dict[str, list[NormalizedAnnotation]] = {}
    for annotation in source.annotations:
        annotations_by_root.setdefault(annotation.root_object_key, []).append(annotation)

    for root_index, (root_key, annotations) in enumerate(annotations_by_root.items(), start=1):
        root_node = _mermaid_node_id("root", source.source_index, root_index)
        root_label = _mermaid_label(
            annotations[0].object_type or "coding object",
            _annotation_text_summary(annotations, full_text=full_text),
            full_text=full_text,
        )
        lines.append(f'{root_node}["{root_label}"]')
        lines.append(f"{analysis_node} --> {root_node}")
        lines.append(f"class {root_node} coding;")

        embedded_nodes: dict[str, str] = {}
        for annotation in annotations:
            parent_node = root_node
            if annotation.embedded_parent_path:
                embedded_key = annotation.embedded_parent_path
                if embedded_key not in embedded_nodes:
                    embedded_node = _mermaid_node_id("embedded", source.source_index, len(embedded_nodes), root_index)
                    embedded_nodes[embedded_key] = embedded_node
                    embedded_annotations = [
                        candidate
                        for candidate in annotations
                        if candidate.embedded_parent_path == embedded_key
                    ]
                    lines.append(
                        f'{embedded_node}["{_mermaid_label(_short_field(embedded_key), _annotation_text_summary(embedded_annotations, full_text=full_text), full_text=full_text)}"]'
                    )
                    lines.append(f"{root_node} --> {embedded_node}")
                    lines.append(f"class {embedded_node} embedded;")
                parent_node = embedded_nodes[embedded_key]

            annotation_node = _mermaid_node_id("ann", source.source_index, annotation.annotation_id)
            annotation_label = _mermaid_label(
                _short_field(annotation.normalized_field_path),
                _annotation_node_text(annotation, full_text=full_text),
                full_text=full_text,
            )
            lines.append(f'{annotation_node}["{annotation_label}"]')
            lines.append(f"{parent_node} --> {annotation_node}")
            lines.append(f"class {annotation_node} annotation;")

    return "\n".join(lines)


def _agreement_graph_mermaid(report: AgreementReport, *, full_text: bool) -> str:
    lines = [
        "flowchart LR",
        "classDef source fill:#f8fafc,stroke:#334155,stroke-width:2px,color:#0f172a;",
        "classDef coding fill:#ecfeff,stroke:#0891b2,color:#164e63;",
        "classDef annotation fill:#f0fdf4,stroke:#22c55e,color:#14532d;",
        "classDef full fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#14532d;",
        "classDef shared fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#1e3a8a;",
        "classDef unique fill:#f3f4f6,stroke:#6b7280,color:#374151;",
    ]
    included_clusters = report.clusters
    included_annotations = {
        (annotation.source_index, annotation.annotation_id): cluster
        for cluster in included_clusters
        for annotation in cluster.annotations
    }
    for source in report.sources:
        source_node = _mermaid_node_id("src", source.source_index)
        lines.append(f'{source_node}["{_mermaid_label(source.label, source.source_name, full_text=full_text)}"]')
        lines.append(f"class {source_node} source;")
        source_annotations = [
            annotation
            for annotation in source.annotations
            if (annotation.source_index, annotation.annotation_id) in included_annotations
        ]
        root_nodes: dict[str, str] = {}
        for annotation in source_annotations:
            root_node = root_nodes.get(annotation.root_object_key)
            if root_node is None:
                root_node = _mermaid_node_id("agr_root", source.source_index, len(root_nodes))
                root_nodes[annotation.root_object_key] = root_node
                lines.append(
                    f'{root_node}["{_mermaid_label(annotation.object_type or "coding object", _root_text_summary(source, annotation.root_object_key, full_text=full_text), full_text=full_text)}"]'
                )
                lines.append(f"{source_node} --> {root_node}")
                lines.append(f"class {root_node} coding;")

            annotation_node = _mermaid_node_id("agr_ann", source.source_index, annotation.annotation_id)
            lines.append(
                f'{annotation_node}["{_mermaid_label(_short_field(annotation.normalized_field_path), _annotation_node_text(annotation, full_text=full_text), full_text=full_text)}"]'
            )
            lines.append(f"{root_node} --> {annotation_node}")
            lines.append(f"class {annotation_node} annotation;")

    for cluster in included_clusters:
        cluster_node = _mermaid_node_id("cluster", cluster.cluster_id)
        status_class = "full" if len(cluster.present_source_indices) == len(report.sources) else "shared"
        if len(cluster.present_source_indices) <= 1:
            status_class = "unique"
        lines.append(
            f'{cluster_node}["{_mermaid_label(f"Cluster {cluster.cluster_id}", f"{len(cluster.present_source_indices)}/{len(report.sources)} exports", full_text=full_text)}"]'
        )
        lines.append(f"class {cluster_node} {status_class};")
        for annotation in cluster.annotations:
            annotation_node = _mermaid_node_id("agr_ann", annotation.source_index, annotation.annotation_id)
            lines.append(f"{annotation_node} -.-> {cluster_node}")

    return "\n".join(lines)


def _object_mapping_sankey(matches, *, embedded: bool, full_text: bool) -> str:
    counts: dict[tuple[str, str], int] = {}
    labels: dict[tuple, str] = {}
    for match in matches:
        if embedded:
            left_key = match.left.embedded_parent_path
            right_key = match.right.embedded_parent_path
            if not left_key or not right_key:
                continue
            left = ("embedded", match.left.source_index, match.left.root_object_key, left_key)
            right = ("embedded", match.right.source_index, match.right.root_object_key, right_key)
            labels.setdefault(left, _sankey_object_label(match.left, embedded=True, full_text=full_text))
            labels.setdefault(right, _sankey_object_label(match.right, embedded=True, full_text=full_text))
        else:
            left = ("root", match.left.source_index, match.left.root_object_key)
            right = ("root", match.right.source_index, match.right.root_object_key)
            labels.setdefault(left, _sankey_object_label(match.left, embedded=False, full_text=full_text))
            labels.setdefault(right, _sankey_object_label(match.right, embedded=False, full_text=full_text))
        counts[(left, right)] = counts.get((left, right), 0) + 1

    if not counts:
        return ""
    lines = ["sankey-beta"]
    for (left, right), count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"{_csv_cell(labels[left])},{_csv_cell(labels[right])},{count}")
    return "\n".join(lines)


def _render_agreement_grid(report: AgreementReport, *, show_full_transcript: bool) -> None:
    transcript_context = _load_transcript_context(report)
    annotation_clusters = _annotation_cluster_map(report)
    row_segment_ids = _grid_segment_ids(report, transcript_context, show_full_transcript=show_full_transcript)
    source_labels = {
        source.source_index: f"{source.label} ({source.source_name})"
        for source in report.sources
    }
    aligned_rows_by_segment = _aligned_rows_by_segment(
        row_segment_ids,
        sources=report.sources,
        annotation_clusters=annotation_clusters,
        segment_order=transcript_context["segment_order"],
    )

    with ui.card().classes("w-full shadow-sm gap-3"):
        heading = "Transcript-Aligned Agreement" if len(report.sources) >= 2 else "Transcript-Aligned Annotations"
        ui.label(heading).classes("font-medium")
        if transcript_context["missing_files"]:
            ui.label(
                "Missing local transcript files: " + ", ".join(transcript_context["missing_files"])
            ).classes("text-xs text-orange-700")
        if not row_segment_ids:
            ui.label("No span annotations available to visualize.").classes("text-sm text-gray-600")
            return

        ui.label(
            "Rows are transcript segments. Within each segment, matched annotations are aligned horizontally by "
            "agreement cluster; unique annotations get their own row."
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
                    aligned_rows = aligned_rows_by_segment.get(segment_id, [])
                    if not aligned_rows:
                        _render_transcript_cell(segment_id, transcript_context)
                        for _source in report.sources:
                            _render_empty_aligned_cell()
                        continue
                    for row_index, aligned_row in enumerate(aligned_rows):
                        _render_transcript_cell(
                            segment_id,
                            transcript_context,
                            row_label=aligned_row["label"],
                            repeated=row_index > 0,
                        )
                        for source in report.sources:
                            annotations = aligned_row["annotations_by_source"].get(source.source_index, [])
                            _render_aligned_annotation_cell(
                                annotations,
                                cluster=aligned_row["cluster"],
                                source_count=len(report.sources),
                                is_continuation=aligned_row["is_continuation"],
                                primary_segment_id=aligned_row["primary_segment_id"],
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


def _aligned_rows_by_segment(
    row_segment_ids: list[str],
    *,
    sources: list[AgreementSource],
    annotation_clusters: dict[tuple[int, int], AgreementCluster],
    segment_order: dict[str, int],
) -> dict[str, list[dict]]:
    # Multi-segment spans are shown once on a primary row, then as compact continuation
    # chips on other covered segments. Reverting this helper restores repeated cards.
    out: dict[str, dict[tuple, dict]] = {segment_id: {} for segment_id in row_segment_ids}
    visible_segments = set(row_segment_ids)
    source_count = len(sources)
    cluster_primary_segments = {
        cluster.cluster_id: _cluster_primary_segment(cluster, segment_order)
        for cluster in annotation_clusters.values()
        if len(cluster.present_source_indices) > 1
    }

    for source in sources:
        for annotation in source.annotations:
            cluster = annotation_clusters.get((annotation.source_index, annotation.annotation_id))
            if cluster and len(cluster.present_source_indices) > 1:
                primary_segment_id = cluster_primary_segments[cluster.cluster_id]
                row_key = ("cluster", cluster.cluster_id, "primary")
                _add_aligned_row_annotation(
                    out,
                    visible_segments,
                    segment_id=primary_segment_id,
                    row_key=row_key,
                    annotation=annotation,
                    cluster=cluster,
                    is_continuation=False,
                    primary_segment_id=primary_segment_id,
                )
                for segment_id in _segment_ids_for_annotation(annotation, segment_order):
                    if segment_id == primary_segment_id:
                        continue
                    _add_aligned_row_annotation(
                        out,
                        visible_segments,
                        segment_id=segment_id,
                        row_key=("cluster", cluster.cluster_id, "continuation"),
                        annotation=annotation,
                        cluster=cluster,
                        is_continuation=True,
                        primary_segment_id=primary_segment_id,
                    )
            else:
                primary_segment_id = annotation.span.start_segment_id
                row_key = ("unique", annotation.source_index, annotation.annotation_id, "primary")
                _add_aligned_row_annotation(
                    out,
                    visible_segments,
                    segment_id=primary_segment_id,
                    row_key=row_key,
                    annotation=annotation,
                    cluster=None,
                    is_continuation=False,
                    primary_segment_id=primary_segment_id,
                )
                for segment_id in _segment_ids_for_annotation(annotation, segment_order):
                    if segment_id == primary_segment_id:
                        continue
                    _add_aligned_row_annotation(
                        out,
                        visible_segments,
                        segment_id=segment_id,
                        row_key=("unique", annotation.source_index, annotation.annotation_id, "continuation"),
                        annotation=annotation,
                        cluster=None,
                        is_continuation=True,
                        primary_segment_id=primary_segment_id,
                    )

    finalized: dict[str, list[dict]] = {}
    for segment_id, rows_by_key in out.items():
        rows = list(rows_by_key.values())
        for row in rows:
            for source_annotations in row["annotations_by_source"].values():
                source_annotations.sort(key=lambda a: (a.span.start_char_offset, a.object_type, a.normalized_field_path))
            group = [
                annotation
                for annotations in row["annotations_by_source"].values()
                for annotation in annotations
            ]
            row["label"] = _aligned_row_label(
                row["cluster"],
                group,
                source_count,
                is_continuation=row["is_continuation"],
                primary_segment_id=row["primary_segment_id"],
            )
            row["sort_key"] = _aligned_row_sort_key(
                row["cluster"],
                group,
                is_continuation=row["is_continuation"],
            )
        finalized[segment_id] = sorted(rows, key=lambda row: row["sort_key"])
    return finalized


def _add_aligned_row_annotation(
    rows_by_segment: dict[str, dict[tuple, dict]],
    visible_segments: set[str],
    *,
    segment_id: str,
    row_key: tuple,
    annotation: NormalizedAnnotation,
    cluster: AgreementCluster | None,
    is_continuation: bool,
    primary_segment_id: str,
) -> None:
    if segment_id not in visible_segments:
        return
    segment_rows = rows_by_segment.setdefault(segment_id, {})
    row = segment_rows.get(row_key)
    if row is None:
        row = {
            "cluster": cluster,
            "annotations_by_source": {},
            "label": "",
            "sort_key": (),
            "is_continuation": is_continuation,
            "primary_segment_id": primary_segment_id,
        }
        segment_rows[row_key] = row
    annotations = row["annotations_by_source"].setdefault(annotation.source_index, [])
    annotation_key = (annotation.source_index, annotation.annotation_id)
    if annotation_key not in {(a.source_index, a.annotation_id) for a in annotations}:
        annotations.append(annotation)


def _aligned_row_label(
    cluster: AgreementCluster | None,
    annotations: list[NormalizedAnnotation],
    source_count: int,
    *,
    is_continuation: bool,
    primary_segment_id: str,
) -> str:
    prefix = "continues " if is_continuation else ""
    if cluster is None:
        label = "unique"
    else:
        label = f"cluster {cluster.cluster_id} ({len(cluster.present_source_indices)}/{source_count})"
    if is_continuation:
        return f"{prefix}{label} from {primary_segment_id}"
    return label


def _aligned_row_sort_key(
    cluster: AgreementCluster | None,
    annotations: list[NormalizedAnnotation],
    *,
    is_continuation: bool,
) -> tuple:
    first = min(annotations, key=lambda a: (a.span.start_char_offset, a.object_type, a.normalized_field_path))
    if cluster and len(cluster.present_source_indices) > 1:
        shared_rank = 1 if is_continuation else 0
    else:
        shared_rank = 3 if is_continuation else 2
    cluster_id = cluster.cluster_id if cluster else 10**9
    return (
        shared_rank,
        first.span.start_char_offset,
        first.object_type,
        first.normalized_field_path,
        cluster_id,
        first.source_index,
        first.annotation_id,
    )


def _cluster_primary_segment(cluster: AgreementCluster, segment_order: dict[str, int]) -> str:
    first = min(
        cluster.annotations,
        key=lambda annotation: _segment_sort_key(annotation.span.start_segment_id, segment_order),
    )
    return first.span.start_segment_id


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


def _render_transcript_cell(
    segment_id: str,
    transcript_context: dict,
    *,
    row_label: str | None = None,
    repeated: bool = False,
) -> None:
    texts = [
        text
        for (_interview_file, current_segment_id), text in transcript_context["segment_text"].items()
        if current_segment_id == segment_id
    ]
    text = texts[0] if texts else ""
    bg = "bg-slate-50" if repeated else "bg-white"
    with ui.element("div").classes(f"sticky left-0 z-10 {bg} p-2 border-b border-r min-h-20"):
        ui.label(segment_id if not repeated else f"{segment_id} continued").classes(
            "text-xs font-semibold text-slate-600"
        )
        if row_label:
            ui.label(row_label).classes("text-[11px] text-slate-500")
        if not repeated:
            ui.label(_short_text(text, 320) if text else "Transcript text unavailable").classes(
                "text-sm whitespace-normal"
            )


def _render_empty_aligned_cell() -> None:
    with ui.element("div").classes("p-2 border-b min-h-20 bg-slate-50/40"):
        ui.label("-").classes("text-xs text-gray-400")


def _render_aligned_annotation_cell(
    annotations: list[NormalizedAnnotation],
    *,
    cluster: AgreementCluster | None,
    source_count: int,
    is_continuation: bool,
    primary_segment_id: str,
) -> None:
    with ui.element("div").classes("p-2 border-b min-h-20 bg-slate-50/40"):
        if not annotations:
            ui.label("-").classes("text-xs text-gray-400")
            return
        for annotation in annotations:
            status_class = _cluster_status_class(cluster, source_count)
            agreement_label = _cluster_agreement_label(cluster, source_count)
            if is_continuation:
                with ui.element("div").classes(f"rounded border px-2 py-1 mb-2 text-[11px] {status_class}"):
                    ui.label(f"continues from {primary_segment_id}").classes("font-semibold")
                    ui.label(annotation.object_type or "unknown").classes("text-slate-700")
                    ui.label(_short_field(annotation.normalized_field_path)).classes("text-slate-600")
                    ui.label(annotation.span.range_label).classes("text-slate-500")
                continue
            with ui.element("div").classes(f"rounded border p-2 mb-2 text-xs {status_class}"):
                with ui.row().classes("w-full items-center justify-between gap-2"):
                    ui.label(annotation.object_type or "unknown").classes("font-semibold")
                    ui.label(agreement_label).classes("text-[11px]")
                ui.label(_short_field(annotation.normalized_field_path)).classes("text-[11px] text-slate-700")
                ui.label(annotation.span.range_label).classes("text-[11px] text-slate-500")
                if annotation.span.selected_text:
                    ui.label(annotation.span.selected_text).classes("text-xs whitespace-pre-wrap")


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


def _annotation_text_summary(annotations: list[NormalizedAnnotation], *, full_text: bool) -> str:
    seen: list[str] = []
    for annotation in annotations:
        text = " ".join((annotation.span.selected_text or "").split())
        if text and text not in seen:
            seen.append(text)
        if not full_text and seen:
            break
    if not seen:
        return "No extracted text"
    if full_text:
        return "\n---\n".join(seen)
    return seen[0]


def _root_text_summary(source: AgreementSource, root_object_key: str, *, full_text: bool) -> str:
    return _annotation_text_summary(
        [annotation for annotation in source.annotations if annotation.root_object_key == root_object_key],
        full_text=full_text,
    )


def _annotation_node_text(annotation: NormalizedAnnotation, *, full_text: bool) -> str:
    if full_text:
        return annotation.span.selected_text or annotation.span.range_label
    return annotation.span.selected_text or annotation.span.range_label


def _sankey_object_label(annotation: NormalizedAnnotation, *, embedded: bool, full_text: bool) -> str:
    if embedded:
        object_label = _short_field(annotation.embedded_parent_path or "embedded object")
    else:
        object_label = annotation.object_type or "coding object"
    text = " ".join((annotation.span.selected_text or annotation.span.range_label).split())
    if not full_text:
        text = _short_text(text, 90)
    return f"{annotation.source_label} | {object_label} | {text}"


def _mermaid_node_id(*parts) -> str:
    raw = "_".join(str(part) for part in parts)
    return "m_" + "".join(ch if ch.isalnum() else "_" for ch in raw)


def _mermaid_label(title: str, subtitle: str | None = None, *, full_text: bool) -> str:
    parts = [f"<b>{_escape_mermaid_text(title)}</b>"]
    if subtitle:
        parts.extend(_escape_mermaid_text(line) for line in _wrap_mermaid_text(subtitle, full_text=full_text))
    return "<br>".join(parts)


def _escape_mermaid_text(value: str | None) -> str:
    text = str(value or "")
    return (
        text.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("[", "(")
        .replace("]", ")")
    )


def _wrap_mermaid_text(value: str | None, *, full_text: bool, width: int = 46) -> list[str]:
    text = " ".join(str(value or "").split())
    if not text:
        return []
    if not full_text:
        text = _short_text(text, 110)

    lines: list[str] = []
    for paragraph in text.split(" --- "):
        words = paragraph.split()
        current = ""
        for word in words:
            if not current:
                current = word
                continue
            if len(current) + 1 + len(word) <= width:
                current += " " + word
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        if paragraph != text.split(" --- ")[-1]:
            lines.append("---")
    return lines


def _mermaid_dimensions(code: str) -> tuple[int, int]:
    line_count = len(code.splitlines())
    node_count = code.count('["')
    sankey_link_count = max(0, line_count - 1) if code.startswith("sankey-beta") else 0
    width = max(900, min(24000, 900 + (node_count * 120) + (sankey_link_count * 40)))
    height = max(420, min(18000, 320 + (node_count * 36) + (sankey_link_count * 28)))
    return width, height


def _csv_cell(value: str) -> str:
    escaped = value.replace('"', '""')
    return f'"{escaped}"'


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
