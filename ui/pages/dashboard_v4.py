from __future__ import annotations

from pathlib import Path

from nicegui import ui

from auth.service import current_username, require_auth_or_redirect
from auth.views import top_nav
from config import INTERVIEW_DATA_DIR
from domain.analysis_service import create_analysis, list_analyses_for_interview
from domain.simplified_analysis_exchange_service import (
    export_analysis_to_file,
    import_analyses_from_json_text,
)
from domain.transcript_service import list_interview_files


def render_dashboard() -> None:
    if not require_auth_or_redirect():
        return

    top_nav()
    with ui.column().classes("w-full max-w-5xl mx-auto mt-8 gap-4"):
        with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap"):
            with ui.column().classes("gap-0"):
                ui.label("Interview Files").classes("text-2xl font-semibold")
                ui.label("Pick an existing analysis or create a new one for a file.").classes(
                    "text-sm text-gray-700"
                )
            ui.badge("Coding book v4 · simplified manual", color="primary").props("outline")

        ui.label(
            "The active interface reads and writes only v4 codings. Legacy codings and their "
            "migration backups remain untouched."
        ).classes("text-xs text-gray-600")
        ui.button("Open agreement tool", on_click=lambda: ui.navigate.to("/agreement")).props(
            "outline"
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
                        ui.label(f"Existing analyses: {len(analyses)}").classes(
                            "text-sm text-gray-600"
                        )
                        with ui.row().classes("flex-wrap gap-2"):
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
                                    f"Export v4: {label}",
                                    on_click=lambda _e, aid=analysis.analysis_id: _export_analysis(aid),
                                ).props("flat")
                            if not analyses:
                                ui.label("No analyses yet").classes("text-sm text-gray-500")
                            ui.button(
                                "New analysis",
                                on_click=lambda _e, target=filename: _open_create_dialog(target),
                            )

        def _open_create_dialog(target_file: str) -> None:
            dialog = ui.dialog()
            with dialog, ui.card().classes("w-[480px]"):
                ui.label(f"New analysis for {target_file}").classes("text-lg font-semibold")
                name_input = ui.input("Analysis name").classes("w-full")
                description_input = ui.textarea("Description (optional)").props(
                    "autogrow"
                ).classes("w-full")
                error = ui.label("").classes("text-sm text-red-600")

                def create_click() -> None:
                    try:
                        created = create_analysis(
                            owner_username=current_username() or "unknown",
                            interview_file=target_file,
                            name=name_input.value or "",
                            description=description_input.value or None,
                        )
                    except ValueError as exc:
                        error.set_text(str(exc))
                        return
                    dialog.close()
                    if created.analysis_id:
                        ui.navigate.to(f"/analysis/{created.analysis_id}")
                    else:
                        redraw_file_list()

                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button("Cancel", on_click=dialog.close).props("flat")
                    ui.button("Create", on_click=create_click)
            dialog.open()

        def _export_analysis(analysis_id: str | None) -> None:
            if not analysis_id:
                import_status.set_text("Export failed: invalid analysis id.")
                return
            try:
                path = export_analysis_to_file(analysis_id=analysis_id)
            except Exception as exc:
                import_status.set_text(f"Export failed: {exc}")
                return
            import_status.set_text(f"Exported v4 analysis to {path.name}")
            ui.download(str(path))

        with ui.card().classes("w-full shadow-sm gap-2"):
            ui.label("Upload Interview SRT Files").classes("font-medium")
            ui.label(
                "Drop .srt files here to add them to interview_data/. Existing filenames are rejected."
            ).classes("text-xs text-gray-600")
            srt_batch = {"total": 0, "uploaded": 0, "rejected": 0, "failed": 0, "messages": []}

            def on_srt_begin_upload(_event) -> None:
                srt_batch.update(total=0, uploaded=0, rejected=0, failed=0, messages=[])
                srt_upload_status.set_text("Uploading SRT files...")

            async def on_srt_upload(event) -> None:
                filename = Path(getattr(event.file, "name", "") or "").name
                srt_batch["total"] += 1
                if not filename or not filename.lower().endswith(".srt"):
                    srt_batch["rejected"] += 1
                    srt_batch["messages"].append(f"Rejected '{filename}': only .srt files are allowed.")
                    return
                if filename.lower() in {name.lower() for name in list_interview_files()}:
                    srt_batch["rejected"] += 1
                    srt_batch["messages"].append(f"Rejected '{filename}': file already exists.")
                    return
                try:
                    content = await event.file.read()
                    INTERVIEW_DATA_DIR.mkdir(parents=True, exist_ok=True)
                    (INTERVIEW_DATA_DIR / filename).write_bytes(content)
                except Exception as exc:
                    srt_batch["failed"] += 1
                    srt_batch["messages"].append(f"Upload failed for '{filename}': {exc}")
                    return
                srt_batch["uploaded"] += 1
                srt_batch["messages"].append(f"Uploaded '{filename}'.")

            def on_srt_multi_upload(event) -> None:
                total = len(getattr(event, "files", []) or [])
                if total:
                    srt_batch["total"] = total
                redraw_file_list()
                summary = (
                    "SRT upload finished: uploaded={uploaded}, rejected={rejected}, "
                    "failed={failed}, total={total}."
                ).format(**srt_batch)
                details = " ".join(srt_batch["messages"][:6])
                srt_upload_status.set_text(f"{summary} {details}".strip())

            ui.upload(
                label="Drop SRT files or click to upload",
                multiple=True,
                on_begin_upload=on_srt_begin_upload,
                on_upload=on_srt_upload,
                on_multi_upload=on_srt_multi_upload,
                auto_upload=True,
            ).props('accept=".srt"')

        redraw_file_list()

        with ui.card().classes("w-full shadow-sm gap-2"):
            ui.label("Import / Export v4 Analyses").classes("font-medium")
            ui.label(
                "Only exports marked coding_book_version=4 are accepted. Legacy exports are rejected "
                "without being changed."
            ).classes("text-xs text-gray-600")

            async def on_upload(event) -> None:
                try:
                    report = import_analyses_from_json_text(await event.file.text())
                except Exception as exc:
                    import_status.set_text(f"Import failed: {exc}")
                    return
                import_status.set_text(
                    "Imported users={imported_users}, analyses={imported_analyses}, "
                    "codings={imported_codings}; skipped missing transcript="
                    "{skipped_missing_transcript}, existing analyses={skipped_existing_analysis}, "
                    "codings without mapped analysis={skipped_codings_without_analysis}".format(**report)
                )
                redraw_file_list()

            ui.upload(
                label="Import v4 analysis JSON",
                on_upload=on_upload,
                auto_upload=True,
            ).props('accept=".json"')
