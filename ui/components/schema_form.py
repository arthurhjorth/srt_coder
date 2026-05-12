from __future__ import annotations

from typing import Callable

from nicegui import ui

from models import CodingEntry, ComparatorDetail, Comparison


def render_schema_form(
    *,
    selected_entry: CodingEntry | None,
    on_save: Callable[[Comparison | None, str | None], None],
) -> Callable[[CodingEntry | None], None]:
    container = ui.column().classes("w-full border rounded p-3 bg-white gap-3")

    def redraw(entry: CodingEntry | None) -> None:
        container.clear()
        with container:
            ui.label("Schema Form (Comparison)").classes("text-lg font-semibold")
            if entry is None:
                ui.label("Select a coding entry to edit schema fields.").classes("text-sm text-gray-600")
                return

            note_input = ui.textarea("Coding note").props("autogrow").classes("w-full")
            note_input.set_value(entry.note or "")

            comparand = ui.input("Comparand").classes("w-full")
            comparand_comment = ui.textarea("Comparand comment").props("rows=3").classes("w-full")

            comparison = entry.comparison
            comparand.set_value(comparison.comparand if comparison else "")
            comparand_comment.set_value(comparison.comparand_comment if comparison else "")

            comparator_rows = ui.column().classes("w-full gap-2")
            comparator_state: list[dict] = []

            def add_comparator(initial: ComparatorDetail | None = None) -> None:
                item = {
                    "comparator": (initial.comparator if initial else "") or "",
                    "comparator_comment": (initial.comparator_comment if initial else "") or "",
                    "adjective": (initial.adjective if initial else "") or "",
                    "adjective_comment": (initial.adjective_comment if initial else "") or "",
                    "dimensions_or_examples": ",".join(initial.dimensions_or_examples or []) if initial else "",
                    "dimensions_or_examples_comment": (
                        initial.dimensions_or_examples_comment if initial else ""
                    ) or "",
                }
                comparator_state.append(item)
                redraw_comparator_rows()

            def remove_comparator(index: int) -> None:
                if 0 <= index < len(comparator_state):
                    comparator_state.pop(index)
                    redraw_comparator_rows()

            def redraw_comparator_rows() -> None:
                comparator_rows.clear()
                with comparator_rows:
                    for idx, row_state in enumerate(comparator_state):
                        with ui.card().classes("w-full shadow-sm"):
                            ui.label(f"Comparator #{idx + 1}").classes("text-sm font-medium")
                            inp_comp = ui.input("Comparator").classes("w-full")
                            inp_comp.set_value(row_state["comparator"])
                            inp_comp.on(
                                "update:model-value",
                                lambda e, i=idx: _update_row(
                                    i, "comparator", getattr(e, "value", None) or e.args
                                ),
                            )

                            inp_comp_c = ui.textarea("Comparator comment").props("rows=3").classes("w-full")
                            inp_comp_c.set_value(row_state["comparator_comment"])
                            inp_comp_c.on(
                                "update:model-value",
                                lambda e, i=idx: _update_row(
                                    i, "comparator_comment", getattr(e, "value", None) or e.args
                                ),
                            )

                            inp_adj = ui.input("Adjective").classes("w-full")
                            inp_adj.set_value(row_state["adjective"])
                            inp_adj.on(
                                "update:model-value",
                                lambda e, i=idx: _update_row(
                                    i, "adjective", getattr(e, "value", None) or e.args
                                ),
                            )

                            inp_adj_c = ui.textarea("Adjective comment").props("rows=3").classes("w-full")
                            inp_adj_c.set_value(row_state["adjective_comment"])
                            inp_adj_c.on(
                                "update:model-value",
                                lambda e, i=idx: _update_row(
                                    i, "adjective_comment", getattr(e, "value", None) or e.args
                                ),
                            )

                            inp_dims = ui.textarea("Dimensions or Examples (comma-separated)").props("autogrow").classes("w-full")
                            inp_dims.set_value(row_state["dimensions_or_examples"])
                            inp_dims.on(
                                "update:model-value",
                                lambda e, i=idx: _update_row(
                                    i, "dimensions_or_examples", getattr(e, "value", None) or e.args
                                ),
                            )

                            inp_dims_c = ui.textarea("Dimensions/Examples comment").props("rows=3").classes("w-full")
                            inp_dims_c.set_value(row_state["dimensions_or_examples_comment"])
                            inp_dims_c.on(
                                "update:model-value",
                                lambda e, i=idx: _update_row(
                                    i, "dimensions_or_examples_comment", getattr(e, "value", None) or e.args
                                ),
                            )

                            ui.button("Remove comparator", on_click=lambda _e, i=idx: remove_comparator(i))

            def _update_row(index: int, key: str, value) -> None:
                if 0 <= index < len(comparator_state):
                    comparator_state[index][key] = value or ""

            if comparison and comparison.comparators:
                for cmp_item in comparison.comparators:
                    add_comparator(cmp_item)
            else:
                redraw_comparator_rows()

            ui.button("Add comparator", on_click=lambda: add_comparator())
            save_error = ui.label("").classes("text-sm text-red-600")

            def save_click() -> None:
                built_comparators: list[ComparatorDetail] = []
                for row in comparator_state:
                    dims = [
                        d.strip()
                        for d in (row["dimensions_or_examples"] or "").split(",")
                        if d.strip()
                    ]
                    comparator_obj = ComparatorDetail(
                        comparator=(row["comparator"] or "").strip() or None,
                        comparator_comment=(row["comparator_comment"] or "").strip() or None,
                        adjective=(row["adjective"] or "").strip() or None,
                        adjective_comment=(row["adjective_comment"] or "").strip() or None,
                        dimensions_or_examples=dims or None,
                        dimensions_or_examples_comment=(
                            row["dimensions_or_examples_comment"] or ""
                        ).strip() or None,
                    )
                    # keep row only if something is filled
                    if any(
                        [
                            comparator_obj.comparator,
                            comparator_obj.comparator_comment,
                            comparator_obj.adjective,
                            comparator_obj.adjective_comment,
                            comparator_obj.dimensions_or_examples,
                            comparator_obj.dimensions_or_examples_comment,
                        ]
                    ):
                        built_comparators.append(comparator_obj)

                comparison_obj = Comparison(
                    comparand=(comparand.value or "").strip() or None,
                    comparand_comment=(comparand_comment.value or "").strip() or None,
                    comparators=built_comparators or None,
                )
                if not any(
                    [
                        comparison_obj.comparand,
                        comparison_obj.comparand_comment,
                        comparison_obj.comparators,
                    ]
                ):
                    comparison_obj = None
                try:
                    on_save(comparison_obj, (note_input.value or "").strip() or None)
                except Exception as exc:  # pragma: no cover - ui path
                    save_error.set_text(str(exc))
                    return
                save_error.set_text("")

            ui.button("Save schema fields", on_click=save_click)

    redraw(selected_entry)
    return redraw
