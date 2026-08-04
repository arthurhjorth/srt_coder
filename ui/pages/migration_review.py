from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from nicegui import ui

from auth.service import require_auth_or_redirect
from auth.views import top_nav
from config import CODED_DATA_DIR, CODINGS_JSON
from domain.migration_review_service import FieldMigrationChange, build_migration_review, list_migration_backups


def _metric(label: str, value: str) -> None:
    with ui.card().classes("min-w-40 bg-slate-50 shadow-none"):
        ui.label(value).classes("text-xl font-semibold")
        ui.label(label).classes("text-xs text-gray-600")


def _span_chip(span: dict, *, color_class: str) -> None:
    text = str(span.get("selected_text") or "(no selected text)")
    if len(text) > 180:
        text = text[:179] + "…"
    start = f"{span.get('start_segment_id', '?')}:{span.get('start_char_offset', '?')}"
    end = f"{span.get('end_segment_id', '?')}:{span.get('end_char_offset', '?')}"
    with ui.element("div").classes(f"w-full rounded border px-2 py-1 text-xs {color_class}"):
        ui.label(text).classes("whitespace-pre-wrap")
        ui.label(f"{start} → {end}").classes("text-[10px] opacity-70")


def _text_panel(title: str, value: str | None, *, classes: str) -> None:
    with ui.element("div").classes(f"w-full min-h-28 rounded border p-3 {classes}"):
        ui.label(title).classes("text-xs font-semibold uppercase tracking-wide")
        ui.label(value or "(empty)").classes("text-sm whitespace-pre-wrap")


def _render_change(
    change: FieldMigrationChange,
    *,
    store_changed: bool | None,
    later_schema: bool,
) -> None:
    status_text = "Matches expected migration" if change.current_matches_expected else "Current value differs"
    status_class = (
        "bg-emerald-100 text-emerald-900"
        if change.current_matches_expected
        else "bg-red-100 text-red-900"
    )
    with ui.card().classes("w-full shadow-sm gap-3"):
        with ui.row().classes("w-full items-center justify-between gap-2 flex-wrap"):
            with ui.column().classes("gap-0"):
                ui.label(change.object_label).classes("font-semibold")
                ui.label(f"{change.source_label} → {change.target_label}").classes("text-sm text-gray-700")
            ui.badge(status_text).classes(status_class)

        with ui.row().classes("w-full items-stretch gap-2 flex-wrap"):
            with ui.column().classes("flex-1 min-w-[260px] gap-2"):
                _text_panel(
                    "Before · retained field",
                    change.retained_before,
                    classes="bg-sky-50 border-sky-300 text-sky-950",
                )
            with ui.column().classes("flex-1 min-w-[260px] gap-2"):
                _text_panel(
                    "Moved from retiring field",
                    change.migrated_from_legacy,
                    classes="bg-amber-50 border-amber-300 text-amber-950",
                )
            with ui.column().classes("flex-1 min-w-[260px] gap-2"):
                _text_panel(
                    "Expected under the current schema",
                    change.expected_after,
                    classes="bg-emerald-50 border-emerald-300 text-emerald-950",
                )

        if not change.current_matches_expected:
            if later_schema:
                explanation = (
                    "The live store is on a later schema than this backup's migration target. "
                    "The difference may come from a later schema migration."
                )
            elif store_changed is False:
                explanation = "The live store has changed since migration, so this may be a later user edit."
            else:
                explanation = "The live value does not match the deterministic migration result and should be reviewed."
            ui.label(explanation).classes("text-xs text-red-700")
            _text_panel(
                "Current live value",
                change.current_after,
                classes="bg-red-50 border-red-300 text-red-950",
            )

        if change.retained_spans_before or change.legacy_spans or change.expected_spans:
            with ui.expansion(
                f"Span movement · {len(change.legacy_spans)} moved, {len(change.expected_spans)} after",
                icon="format_quote",
            ).classes("w-full"):
                with ui.row().classes("w-full items-start gap-3 flex-wrap"):
                    with ui.column().classes("flex-1 min-w-[250px] gap-1"):
                        ui.label("Retained spans before").classes("text-xs font-semibold text-sky-900")
                        for span in change.retained_spans_before:
                            _span_chip(span, color_class="bg-sky-50 border-sky-300")
                        if not change.retained_spans_before:
                            ui.label("None").classes("text-xs text-gray-500")
                    with ui.column().classes("flex-1 min-w-[250px] gap-1"):
                        ui.label("Legacy spans moved").classes("text-xs font-semibold text-amber-900")
                        for span in change.legacy_spans:
                            _span_chip(span, color_class="bg-amber-50 border-amber-300")
                        if not change.legacy_spans:
                            ui.label("None").classes("text-xs text-gray-500")
                    with ui.column().classes("flex-1 min-w-[250px] gap-1"):
                        ui.label("Expected span order after").classes("text-xs font-semibold text-emerald-900")
                        for span in change.expected_spans:
                            _span_chip(span, color_class="bg-emerald-50 border-emerald-300")
                        if not change.expected_spans:
                            ui.label("None").classes("text-xs text-gray-500")

        with ui.expansion("Technical paths", icon="code").classes("w-full"):
            ui.label(f"From: {change.source_path}").classes("font-mono text-xs")
            ui.label(f"To: {change.target_path}").classes("font-mono text-xs")
            ui.label(f"Coding ID: {change.coding_id}").classes("font-mono text-xs")


def render_migration_review_page() -> None:
    if not require_auth_or_redirect():
        return

    top_nav()
    backup_root = CODED_DATA_DIR / "old_schema_analyses"
    backups = list_migration_backups(backup_root)

    with ui.column().classes("w-full max-w-[1600px] mx-auto mt-8 gap-4"):
        with ui.row().classes("w-full items-center justify-between"):
            with ui.column().classes("gap-1"):
                ui.label("Schema Migration Review").classes("text-2xl font-semibold")
                ui.label(
                    "Read-only comparison of the immutable old-schema backup, the deterministic expected migration, "
                    "and the current live coding data."
                ).classes("text-sm text-gray-700")
            ui.button("Back to dashboard", on_click=lambda: ui.navigate.to("/")).props("flat")

        if not backups:
            with ui.card().classes("w-full bg-slate-50 shadow-sm"):
                ui.label("No completed migration backups are available yet.").classes("font-medium")
                ui.label(
                    "This page will populate after startup detects an older coding schema and completes the "
                    "mandatory backup and migration."
                ).classes("text-sm text-gray-600")
            return

        options = {str(item.directory): item.label for item in backups}
        backup_select = ui.select(
            options=options,
            value=str(backups[0].directory),
            label="Migration backup",
        ).classes("w-full max-w-3xl")
        status = ui.label("").classes("text-sm text-red-700")
        container = ui.column().classes("w-full gap-4")

        def redraw() -> None:
            container.clear()
            selected = Path(str(backup_select.value or ""))
            allowed = {item.directory.resolve() for item in backups}
            try:
                if selected.resolve() not in allowed:
                    raise ValueError("Selected backup is outside the configured migration backup folder")
                review = build_migration_review(selected, CODINGS_JSON)
            except Exception as exc:
                status.set_text(f"Could not load migration review: {exc}")
                return
            status.set_text("")

            with container:
                with ui.card().classes("w-full shadow-sm gap-3"):
                    with ui.row().classes("w-full flex-wrap gap-3"):
                        _metric("Analyses with changes", str(len(review.analyses)))
                        _metric("Coding objects", str(review.changed_coding_count))
                        _metric("Changed fields/comments", str(review.changed_field_count))
                        _metric("Moved spans", str(review.moved_span_count))
                    counts = review.manifest.get("migration_counts") or {}
                    recorded_steps = review.manifest.get("applied_steps")
                    target_version = review.manifest.get("target_schema_version")
                    counts_are_compatible = isinstance(recorded_steps, list) or (
                        isinstance(target_version, int)
                        and not isinstance(target_version, bool)
                        and target_version < 3
                    )
                    if counts and counts_are_compatible:
                        ui.label(
                            "Manifest audit: values={values}, comments={comments}, legacy span paths={paths}, spans={spans}."
                            .format(
                                values=counts.get("values_with_content", 0),
                                comments=counts.get("comments_with_content", 0),
                                paths=counts.get("legacy_span_paths", 0),
                                spans=counts.get("legacy_spans", 0),
                            )
                        ).classes("text-xs text-gray-600")
                    elif counts:
                        ui.label(
                            "This transitional manifest predates per-step v3 audit counts; the reconstructed change "
                            "and span totals above are authoritative."
                        ).classes("text-xs text-amber-700")
                    steps = review.applied_steps
                    if steps:
                        ui.label(f"Applied migration steps: {', '.join(str(step) for step in steps)}.").classes(
                            "text-xs text-gray-600"
                        )

                    if review.live_store_matches_migration_checksum is True:
                        ui.label(
                            "The live codings file still has the exact checksum produced by this migration."
                        ).classes("rounded bg-emerald-100 px-3 py-2 text-sm text-emerald-900")
                    elif review.live_store_matches_migration_checksum is False:
                        if review.live_store_is_later_schema:
                            ui.label(
                                "The live codings file is on a later schema than this historical backup's migration "
                                "target. The checksum difference is therefore expected; individual values are compared "
                                "against the current deterministic migration result below."
                            ).classes("rounded bg-sky-100 px-3 py-2 text-sm text-sky-900")
                        else:
                            ui.label(
                                "The live codings file has changed since this migration. Individual differences may be "
                                "legitimate later edits."
                            ).classes("rounded bg-amber-100 px-3 py-2 text-sm text-amber-900")
                    else:
                        ui.label(
                            "This older manifest has no post-migration checksum; individual values can still be compared."
                        ).classes("rounded bg-slate-100 px-3 py-2 text-sm text-slate-700")

                if not review.analyses:
                    ui.label("No populated retiring fields or legacy spans were found in this backup.").classes(
                        "text-sm text-gray-600"
                    )
                    return

                for analysis in review.analyses:
                    with ui.expansion(
                        f"{analysis.name} · {analysis.owner} · {len(analysis.changes)} changes",
                        icon="difference",
                        value=True,
                    ).classes("w-full border rounded bg-white"):
                        ui.label(analysis.interview_file).classes("text-xs text-gray-600")
                        by_coding: dict[str, list[FieldMigrationChange]] = defaultdict(list)
                        for change in analysis.changes:
                            by_coding[change.coding_id].append(change)
                        for coding_id, changes in by_coding.items():
                            with ui.expansion(
                                f"{changes[0].object_label.split(' ·')[0]} object · {len(changes)} changed fields/comments",
                                icon="account_tree",
                                value=True,
                            ).classes("w-full"):
                                ui.label(f"Coding ID: {coding_id}").classes("font-mono text-[11px] text-gray-500")
                                for change in changes:
                                    _render_change(
                                        change,
                                        store_changed=review.live_store_matches_migration_checksum,
                                        later_schema=review.live_store_is_later_schema,
                                    )

        backup_select.on("update:model-value", lambda _event: redraw())
        redraw()
