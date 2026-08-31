from __future__ import annotations

from nicegui import ui

from auth.service import require_auth_or_redirect
from auth.views import top_nav
from coding_books.simplified_v4.labels import (
    CODE_TYPE_LABELS,
    EXPRESSED_CERTAINTY_LABELS,
    FIELD_LABELS,
    NUANCE_RELATION_TYPE_LABELS,
    PERSPECTIVE_TYPE_LABELS,
)
from coding_books.simplified_v4.models import SimplifiedCodingEntry
from domain.simplified_agreement_service import (
    AgreementReport,
    AgreementRules,
    AgreementSource,
    build_agreement_report,
    load_agreement_export,
    normalize_field_path,
)


def render_agreement_page() -> None:
    if not require_auth_or_redirect():
        return

    top_nav()
    with ui.column().classes("w-full max-w-[1800px] mx-auto mt-6 gap-4"):
        with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap"):
            with ui.column().classes("gap-0"):
                ui.label("Agreement Tool").classes("text-2xl font-semibold")
                ui.label(
                    "Compare transcript spans and inspect the flat v4 coding fields side by side."
                ).classes("text-sm text-gray-700")
            ui.badge("Coding book v4 only", color="primary").props("outline")
        ui.button("Back to interview list", on_click=lambda: ui.navigate.to("/")).props("flat")

        state: dict = {"sources": [], "next_source_index": 0}
        status = ui.label("").classes("text-sm text-gray-700")

        with ui.card().classes("w-full gap-2"):
            ui.label("Agreement rules").classes("font-medium")
            with ui.row().classes("w-full flex-wrap gap-4 items-center"):
                span_mode = ui.select(
                    options={"partial": "Partial span overlap", "exact": "Exact span"},
                    value="partial",
                    label="Span matching",
                ).classes("min-w-[220px]")
                field_mode = ui.select(
                    options={
                        "normalized": "Same field; ignore list index",
                        "exact": "Exact field path",
                        "ignore": "Ignore fields",
                    },
                    value="normalized",
                    label="Field matching",
                ).classes("min-w-[250px]")
                same_type = ui.switch("Require same code type", value=True)
            ui.label(
                "Metrics use transcript spans. Enum selections and coder notes remain visible in the "
                "schema comparison but are not counted as span annotations."
            ).classes("text-xs text-gray-600")

        with ui.card().classes("w-full gap-2"):
            ui.label("Upload v4 exports").classes("font-medium")
            ui.label(
                "Files stay in memory on this page. Legacy exports are rejected without being modified."
            ).classes("text-xs text-gray-600")

            async def on_upload(event) -> None:
                source_name = getattr(event.file, "name", "") or "agreement-export-v4.json"
                try:
                    source = load_agreement_export(
                        await event.file.text(),
                        source_name=source_name,
                        source_index=state["next_source_index"],
                    )
                except Exception as exc:
                    status.set_text(f"Could not load {source_name}: {exc}")
                    return
                state["next_source_index"] += 1
                state["sources"].append(source)
                status.set_text(
                    f"Loaded {source_name}: {len(source.codings)} coding objects and "
                    f"{len(source.annotations)} transcript annotations."
                )
                redraw()

            ui.upload(
                label="Drop v4 analysis exports or click to upload",
                multiple=True,
                on_upload=on_upload,
                auto_upload=True,
            ).props('accept=".json"')

        report_container = ui.column().classes("w-full gap-4")

        def current_rules() -> AgreementRules:
            return AgreementRules(
                span_mode=span_mode.value or "partial",
                field_mode=field_mode.value or "normalized",
                require_same_object_type=bool(same_type.value),
            )

        def remove_source(source_index: int) -> None:
            state["sources"] = [
                source for source in state["sources"] if source.source_index != source_index
            ]
            redraw()

        def redraw() -> None:
            report_container.clear()
            sources: list[AgreementSource] = state["sources"]
            with report_container:
                if not sources:
                    ui.label("No v4 agreement exports loaded.").classes("text-sm text-gray-600")
                    return

                with ui.card().classes("w-full gap-2"):
                    ui.label("Loaded sources").classes("font-medium")
                    for source in sources:
                        with ui.row().classes("w-full items-center justify-between gap-2"):
                            ui.label(
                                f"{source.label} · {source.source_name} · "
                                f"{len(source.codings)} objects · {len(source.annotations)} spans"
                            ).classes("text-sm")
                            ui.button(
                                "Remove",
                                on_click=lambda _e, index=source.source_index: remove_source(index),
                            ).props("flat dense color=negative")
                        for warning in source.warnings:
                            ui.label(warning).classes("text-xs text-amber-700")

                report = build_agreement_report(sources, current_rules())
                _render_summary(report)
                _render_schema_comparison(report)
                _render_clusters(report)

        span_mode.on("update:model-value", lambda _event: redraw())
        field_mode.on("update:model-value", lambda _event: redraw())
        same_type.on("update:model-value", lambda _event: redraw())
        redraw()


def _metric(label: str, value: str) -> None:
    with ui.card().classes("min-w-[150px] gap-0 p-3"):
        ui.label(value).classes("text-xl font-semibold")
        ui.label(label).classes("text-xs text-gray-600")


def _render_summary(report: AgreementReport) -> None:
    with ui.card().classes("w-full gap-3"):
        ui.label("Summary").classes("text-lg font-semibold")
        with ui.row().classes("w-full flex-wrap gap-2"):
            _metric("Sources", str(len(report.sources)))
            _metric("Transcript annotations", str(report.total_annotations))
            _metric("Agreement clusters", str(len(report.clusters)))
            if len(report.sources) >= 2:
                _metric(
                    "Full-agreement clusters",
                    f"{report.full_agreement_clusters}/{len(report.clusters)}",
                )

        if not report.pair_agreements:
            ui.label("Upload at least two exports to calculate pairwise agreement.").classes(
                "text-sm text-gray-600"
            )
            return
        ui.label("Pairwise span agreement").classes("font-medium")
        for pair in report.pair_agreements:
            with ui.element("div").classes("w-full rounded border p-3"):
                ui.label(f"{pair.left_label} ↔ {pair.right_label}").classes("font-medium")
                with ui.row().classes("flex-wrap gap-4 text-sm"):
                    ui.label(f"F1: {pair.f1:.1%}")
                    ui.label(f"Precision: {pair.precision:.1%}")
                    ui.label(f"Recall: {pair.recall:.1%}")
                    ui.label(
                        f"Matches: {pair.true_positives} · left-only: {pair.false_positives} · "
                        f"right-only: {pair.false_negatives}"
                    )


def _render_schema_comparison(report: AgreementReport) -> None:
    agreed_paths = {
        field_path
        for cluster in report.clusters
        if len(cluster.present_source_indices) >= 2
        for field_path in cluster.field_paths
    }
    with ui.card().classes("w-full gap-3"):
        ui.label("Coding-book comparison").classes("text-lg font-semibold")
        ui.label(
            "The complete flat coding objects are shown side by side. Green fields have at least one "
            "matching transcript span under the selected rules; amber fields do not."
        ).classes("text-xs text-gray-600")
        with ui.row().classes("w-full items-start no-wrap gap-3"):
            for source in report.sources:
                with ui.column().classes("flex-1 min-w-[360px] gap-2"):
                    ui.label(f"{source.label} · {source.source_name}").classes("font-semibold")
                    if not source.codings:
                        ui.label("No coding objects in this export.").classes(
                            "text-sm text-gray-600"
                        )
                    for coding in source.codings:
                        _render_coding_object(coding, agreed_paths, len(report.sources))


def _render_coding_object(
    entry: SimplifiedCodingEntry,
    agreed_paths: set[str],
    source_count: int,
) -> None:
    with ui.element("div").classes("w-full rounded border bg-white p-3"):
        ui.label(CODE_TYPE_LABELS[entry.object_type]).classes("font-medium")
        ui.label(entry.coding_id).classes("text-[10px] text-gray-500")
        fields = entry.coding.fields.model_dump(mode="json")
        for field_name, value in fields.items():
            if field_name == "perspectives":
                for index, perspective in enumerate(value or []):
                    path = f"differentiation.perspectives[{index}]"
                    _render_schema_field(
                        f"{FIELD_LABELS[field_name]} {index + 1}",
                        perspective,
                        path,
                        entry,
                        agreed_paths,
                        source_count,
                    )
                if not value:
                    _render_schema_field(
                        FIELD_LABELS[field_name],
                        None,
                        "differentiation.perspectives[]",
                        entry,
                        agreed_paths,
                        source_count,
                    )
                continue
            path = f"{entry.object_type}.{field_name}"
            _render_schema_field(
                FIELD_LABELS.get(field_name, field_name),
                _display_value(field_name, value),
                path,
                entry,
                agreed_paths,
                source_count,
            )


def _render_schema_field(
    label: str,
    value,
    path: str,
    entry: SimplifiedCodingEntry,
    agreed_paths: set[str],
    source_count: int,
) -> None:
    normalized = normalize_field_path(path)
    if source_count < 2 or label == FIELD_LABELS["coder_note"]:
        color = "bg-gray-50 border-gray-200"
        status = "not included in span agreement" if label == FIELD_LABELS["coder_note"] else "single source"
    elif normalized in agreed_paths:
        color = "bg-green-50 border-green-300"
        status = "matching span"
    else:
        color = "bg-amber-50 border-amber-300"
        status = "no matching span"
    span_count = len(entry.field_spans.get(path, []))
    with ui.element("div").classes(f"w-full mt-2 rounded border p-2 {color}"):
        with ui.row().classes("w-full items-center justify-between gap-2"):
            ui.label(label).classes("text-xs font-medium")
            ui.label(f"{status} · {span_count} span(s)").classes("text-[10px] text-gray-600")
        ui.label(_text_value(value)).classes("text-xs whitespace-pre-wrap")


def _display_value(field_name: str, value):
    if field_name == "perspective_types":
        reverse = {enum_value.value: label for enum_value, label in PERSPECTIVE_TYPE_LABELS.items()}
        return [reverse.get(item, item) for item in (value or [])]
    if field_name == "relation_type":
        reverse = {
            enum_value.value: label for enum_value, label in NUANCE_RELATION_TYPE_LABELS.items()
        }
        return reverse.get(value, value)
    if field_name == "expressed_certainty":
        reverse = {
            enum_value.value: label for enum_value, label in EXPRESSED_CERTAINTY_LABELS.items()
        }
        return reverse.get(value, value)
    return value


def _text_value(value) -> str:
    if value is None or value == "" or value == []:
        return "—"
    if isinstance(value, list):
        return " · ".join(str(item) for item in value)
    return str(value)


def _render_clusters(report: AgreementReport) -> None:
    with ui.card().classes("w-full gap-3"):
        ui.label("Transcript-span clusters").classes("text-lg font-semibold")
        if not report.clusters:
            ui.label("No transcript spans to compare.").classes("text-sm text-gray-600")
            return
        for cluster in report.clusters:
            agreement = f"{len(cluster.present_source_indices)}/{len(report.sources)} sources"
            color = (
                "border-green-300 bg-green-50"
                if len(report.sources) >= 2
                and len(cluster.present_source_indices) == len(report.sources)
                else "border-gray-200 bg-gray-50"
            )
            with ui.element("div").classes(f"w-full rounded border p-3 {color}"):
                with ui.row().classes("w-full items-center justify-between gap-2"):
                    ui.label(f"Cluster {cluster.cluster_id}").classes("font-medium")
                    ui.label(agreement).classes("text-xs text-gray-600")
                ui.label(" · ".join(cluster.field_paths)).classes("text-xs text-gray-700")
                for annotation in cluster.annotations:
                    with ui.element("div").classes("w-full mt-1 rounded border bg-white px-2 py-1"):
                        ui.label(
                            f"{annotation.source_label} · {annotation.object_type} · "
                            f"{annotation.field_path} · {annotation.span.range_label}"
                        ).classes("text-[10px] text-gray-500")
                        ui.label(annotation.span.selected_text or "—").classes(
                            "text-xs whitespace-pre-wrap"
                        )
