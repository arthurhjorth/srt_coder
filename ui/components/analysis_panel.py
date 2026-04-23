from __future__ import annotations

from typing import Callable

from nicegui import ui

from auth.service import current_username
from domain.analysis_service import create_analysis, list_analyses_for_interview
from state.session_state import get_selected_analysis_id


def render_analysis_panel(
    *,
    selected_file: str | None,
    on_analysis_selected: Callable[[str | None], None],
) -> Callable[[str | None], None]:
    container = ui.column().classes("w-full border rounded p-3 bg-white gap-3")

    def redraw(current_file: str | None) -> None:
        container.clear()
        with container:
            ui.label("Analyses").classes("text-lg font-semibold")

            if not current_file:
                ui.label("Select an interview file to view or create analyses.").classes(
                    "text-sm text-gray-600"
                )
                return

            analyses = list_analyses_for_interview(current_file)
            options = {
                a.analysis_id: f"{a.name or '(unnamed)'} · {a.owner_username or 'unknown'}"
                for a in analyses
                if a.analysis_id
            }
            current_selected = get_selected_analysis_id()
            selected_value = current_selected if current_selected in options else None
            if selected_value is None and analyses and analyses[0].analysis_id:
                selected_value = analyses[0].analysis_id

            select = ui.select(
                options=options,
                value=selected_value,
                label="Active analysis",
            ).classes("w-full")

            def on_select_change() -> None:
                on_analysis_selected(select.value)

            select.on("update:model-value", lambda _e: on_select_change())
            on_analysis_selected(selected_value)

            if analyses:
                with ui.column().classes("w-full gap-2"):
                    for a in analyses:
                        label = a.name or "(unnamed)"
                        owner = a.owner_username or "unknown"
                        ui.label(f"• {label} ({owner})").classes("text-sm text-gray-700")
            else:
                ui.label("No analyses yet for this interview.").classes("text-sm text-gray-600")

            ui.separator()
            ui.label("Create analysis").classes("text-sm font-medium")
            name_input = ui.input("Name").classes("w-full")
            desc_input = ui.textarea("Description (optional)").props("autogrow").classes("w-full")
            error = ui.label("").classes("text-sm text-red-600")

            def create_click() -> None:
                try:
                    created = create_analysis(
                        owner_username=current_username() or "unknown",
                        interview_file=current_file,
                        name=name_input.value or "",
                        description=desc_input.value or None,
                    )
                except ValueError as exc:
                    error.set_text(str(exc))
                    return

                error.set_text("")
                name_input.set_value("")
                desc_input.set_value("")
                on_analysis_selected(created.analysis_id)
                redraw(current_file)

            ui.button("Create analysis", on_click=create_click)

    redraw(selected_file)
    return redraw
