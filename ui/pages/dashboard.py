from __future__ import annotations

from pathlib import Path

from nicegui import ui

from auth.service import current_username, require_auth_or_redirect
from auth.views import top_nav
from config import INTERVIEW_DATA_DIR
from domain.analysis_service import create_analysis, list_analyses_for_interview
from domain.analysis_exchange_service import (
    export_analysis_to_file,
    import_analyses_from_json_text,
)
from domain.transcript_service import list_interview_files


def render_dashboard() -> None:
    if not require_auth_or_redirect():
        return

    top_nav()
    with ui.column().classes("w-full max-w-5xl mx-auto mt-8 gap-4"):
        ui.label("Interview Files").classes("text-2xl font-semibold")
        ui.label("Pick an existing analysis or create a new one for a file.").classes(
            "text-sm text-gray-700"
        )
        import_status = ui.label("").classes("text-sm text-gray-700")
        srt_upload_status = ui.label("").classes("text-sm text-gray-700")

        list_container = ui.column().classes("w-full gap-3")

        def redraw_file_list() -> None:
            list_container.clear()
            files = list_interview_files()
            with list_container:
                if not files:
                    ui.label("No interview files found in interview_data/.").classes("text-gray-600")
                    return
                for filename in files:
                    analyses = list_analyses_for_interview(filename)
                    with ui.card().classes("w-full shadow-sm"):
                        ui.label(filename).classes("font-medium")
                        ui.label(f"Existing analyses: {len(analyses)}").classes("text-sm text-gray-600")

                        with ui.row().classes("flex-wrap gap-2"):
                            if analyses:
                                for analysis in analyses:
                                    if not analysis.analysis_id:
                                        continue
                                    label = analysis.name or analysis.analysis_id
                                    owner = analysis.owner_username or "unknown"
                                    ui.button(
                                        f"Open: {label} ({owner})",
                                        on_click=lambda _e, aid=analysis.analysis_id: ui.navigate.to(
                                            f"/analysis/{aid}"
                                        ),
                                    ).props("outline")
                                    ui.button(
                                        f"Export: {label}",
                                        on_click=lambda _e, aid=analysis.analysis_id: _export_analysis(aid),
                                    ).props("flat")
                            else:
                                ui.label("No analyses yet").classes("text-sm text-gray-500")

                            def _open_create_dialog(target_file: str) -> None:
                                dialog = ui.dialog()
                                with dialog, ui.card().classes("w-[480px]"):
                                    ui.label(f"New analysis for {target_file}").classes("text-lg font-semibold")
                                    name_input = ui.input("Analysis name").classes("w-full")
                                    desc_input = ui.textarea("Description (optional)").props("autogrow").classes(
                                        "w-full"
                                    )
                                    error = ui.label("").classes("text-sm text-red-600")

                                    def create_click() -> None:
                                        try:
                                            created = create_analysis(
                                                owner_username=current_username() or "unknown",
                                                interview_file=target_file,
                                                name=name_input.value or "",
                                                description=desc_input.value or None,
                                            )
                                        except ValueError as exc:
                                            error.set_text(str(exc))
                                            return
                                        dialog.close()
                                        redraw_file_list()
                                        if created.analysis_id:
                                            ui.navigate.to(f"/analysis/{created.analysis_id}")

                                    with ui.row().classes("justify-end gap-2"):
                                        ui.button("Cancel", on_click=dialog.close).props("flat")
                                        ui.button("Create", on_click=create_click)
                                dialog.open()

                            ui.button(
                                "New analysis",
                                on_click=lambda _e, f=filename: _open_create_dialog(f),
                            )

        def _export_analysis(analysis_id: str | None) -> None:
            if not analysis_id:
                import_status.set_text("Export failed: invalid analysis id.")
                return
            try:
                path = export_analysis_to_file(analysis_id=analysis_id)
            except Exception as exc:
                import_status.set_text(f"Export failed: {exc}")
                return
            import_status.set_text(f"Exported analysis to {path.name}")
            ui.download(str(path))

        with ui.card().classes("w-full shadow-sm gap-2"):
            ui.label("Upload Interview SRT Files").classes("font-medium")
            ui.label(
                "Drop .srt files here to add them to interview_data/. "
                "Files with an existing name are rejected."
            ).classes("text-xs text-gray-600")

            async def on_srt_upload(event) -> None:
                raw_name = getattr(event.file, "name", "") or ""
                filename = Path(raw_name).name
                if not filename:
                    srt_upload_status.set_text("Upload failed: missing filename.")
                    return
                if not filename.lower().endswith(".srt"):
                    srt_upload_status.set_text(f"Rejected '{filename}': only .srt files are allowed.")
                    return

                existing_names = {name.lower() for name in list_interview_files()}
                if filename.lower() in existing_names:
                    srt_upload_status.set_text(f"Rejected '{filename}': file already exists.")
                    return

                try:
                    content = await event.file.read()
                    INTERVIEW_DATA_DIR.mkdir(parents=True, exist_ok=True)
                    target_path = INTERVIEW_DATA_DIR / filename
                    target_path.write_bytes(content)
                except Exception as exc:
                    srt_upload_status.set_text(f"Upload failed for '{filename}': {exc}")
                    return

                srt_upload_status.set_text(f"Uploaded '{filename}' to interview_data/.")
                redraw_file_list()

            ui.upload(
                label="Drop SRT files or click to upload",
                on_upload=on_srt_upload,
                auto_upload=True,
            ).props('accept=".srt"')

        redraw_file_list()

        with ui.card().classes("w-full shadow-sm gap-2"):
            ui.label("Import / Export Analyses").classes("font-medium")
            ui.label(
                "Import JSON bundle to restore users, analyses, and codings by names (IDs are regenerated). "
                "Analyses with missing transcript files are skipped."
            ).classes("text-xs text-gray-600")

            async def on_upload(event) -> None:
                try:
                    text = await event.file.text()
                    report = import_analyses_from_json_text(text)
                except Exception as exc:
                    import_status.set_text(f"Import failed: {exc}")
                    return
                import_status.set_text(
                    "Imported users={imported_users}, analyses={imported_analyses}, codings={imported_codings}; "
                    "skipped missing transcript={skipped_missing_transcript}, existing analyses={skipped_existing_analysis}, "
                    "codings without mapped analysis={skipped_codings_without_analysis}".format(**report)
                )
                redraw_file_list()

            ui.upload(
                label="Import analysis JSON",
                on_upload=on_upload,
                auto_upload=True,
            ).props('accept=".json"')
