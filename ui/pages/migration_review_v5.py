from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nicegui import ui

from auth.service import require_auth_or_redirect
from auth.views import top_nav
from config import CODED_DATA_DIR, SIMPLIFIED_CODINGS_JSON
from domain.simplified_migration_review_service_v5 import (
    V5MigrationChange,
    build_v5_migration_review,
    list_simplified_migration_backups,
)


def _pretty(value: Any) -> str:
    if isinstance(value, str):
        return value or "(empty)"
    return json.dumps(value, ensure_ascii=False, indent=2)


def _panel(title: str, value: Any, classes: str) -> None:
    with ui.element("div").classes(f"w-full min-h-28 rounded border p-3 {classes}"):
        ui.label(title).classes("text-xs font-semibold uppercase tracking-wide")
        ui.label(_pretty(value)).classes("text-xs whitespace-pre-wrap font-mono")


def _render_change(change: V5MigrationChange) -> None:
    badge = "Matches expected migration" if change.current_matches_expected else "Current value differs"
    badge_class = (
        "bg-emerald-100 text-emerald-900"
        if change.current_matches_expected
        else "bg-amber-100 text-amber-900"
    )
    with ui.card().classes("w-full shadow-sm gap-2"):
        with ui.row().classes("w-full items-center justify-between gap-2"):
            with ui.column().classes("gap-0"):
                ui.label(change.change_type).classes("font-semibold")
                ui.label(
                    f"{change.object_type} · coding ID {change.coding_id}"
                ).classes("font-mono text-[10px] text-gray-500")
            ui.badge(badge).classes(badge_class)
        with ui.row().classes("w-full items-stretch no-wrap gap-3"):
            with ui.column().classes("w-1/3"):
                _panel("Exact backed-up source", change.before, "bg-sky-50 border-sky-300")
            with ui.column().classes("w-1/3"):
                _panel("Expected v5 result", change.expected_after, "bg-emerald-50 border-emerald-300")
            with ui.column().classes("w-1/3"):
                _panel("Current neutral store", change.current_after, "bg-slate-50 border-slate-300")


def render_migration_review_page() -> None:
    if not require_auth_or_redirect():
        return
    top_nav()
    root = CODED_DATA_DIR / "old_schema_analyses"
    backups = list_simplified_migration_backups(root)
    with ui.column().classes("w-full max-w-[1700px] mx-auto mt-8 gap-4"):
        with ui.row().classes("w-full items-center justify-between"):
            with ui.column().classes("gap-0"):
                ui.label("Schema Migration Review").classes("text-2xl font-semibold")
                ui.label(
                    "Read-only review of verified backups, deterministic migration results, "
                    "checksums, and possible later edits."
                ).classes("text-sm text-gray-700")
            ui.button("Back to dashboard", on_click=lambda: ui.navigate.to("/")).props("flat")
        if not backups:
            ui.label("No schema-migration backups are available.").classes("text-sm text-gray-600")
            return
        options = {str(item.directory): item.label for item in backups}
        selector = ui.select(
            options=options, value=str(backups[0].directory), label="Migration backup"
        ).classes("w-full max-w-4xl")
        status = ui.label("").classes("text-sm text-red-700")
        container = ui.column().classes("w-full gap-3")

        def redraw() -> None:
            container.clear()
            selected = Path(str(selector.value or "")).resolve()
            summaries = {item.directory.resolve(): item for item in backups}
            summary = summaries.get(selected)
            if summary is None:
                status.set_text("Selected backup is outside the configured backup folder.")
                return
            status.set_text("")
            with container:
                manifest = summary.manifest
                with ui.card().classes("w-full shadow-sm gap-1"):
                    ui.label(summary.label).classes("font-semibold")
                    ui.label(
                        f"Applied steps: {', '.join(manifest.get('applied_steps') or ['historical migration'])}"
                    ).classes("text-xs text-gray-600")
                    checksums = manifest.get("sha256") or {}
                    ui.label(
                        f"Backup checksum records: {len(checksums)} · status: {manifest.get('status', 'unknown')}"
                    ).classes("text-xs text-gray-600")
                    counts = manifest.get("migration_counts") or {}
                    if counts:
                        ui.label(_pretty(counts)).classes("text-xs font-mono whitespace-pre-wrap")
                if not summary.is_v4_to_v5:
                    ui.label(
                        "This is a historical hierarchical v1–v3 backup. Its manifest remains "
                        "readable here, but the retired hierarchical coding interface is not active."
                    ).classes("rounded bg-slate-100 px-3 py-2 text-sm text-slate-700")
                    return
                try:
                    review = build_v5_migration_review(summary, SIMPLIFIED_CODINGS_JSON)
                except Exception as exc:
                    status.set_text(f"Could not build v5 migration review: {exc}")
                    return
                if review.live_checksum_matches is True:
                    ui.label("The live v5 store still exactly matches the post-migration checksum.").classes(
                        "rounded bg-emerald-100 px-3 py-2 text-sm text-emerald-900"
                    )
                elif review.live_checksum_matches is False:
                    ui.label(
                        "The live v5 checksum differs from the original migration output. This normally "
                        "means later coding edits; each transformed value is checked below."
                    ).classes("rounded bg-amber-100 px-3 py-2 text-sm text-amber-900")
                else:
                    ui.label("No comparable live post-migration checksum is available.").classes(
                        "rounded bg-slate-100 px-3 py-2 text-sm text-slate-700"
                    )
                for change in review.changes:
                    _render_change(change)
                if not review.changes:
                    ui.label("The backup contains no v4 fields requiring visible transformation.").classes(
                        "text-sm text-gray-600"
                    )

        selector.on_value_change(lambda _event: redraw())
        redraw()
