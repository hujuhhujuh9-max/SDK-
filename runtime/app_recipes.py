"""A copyable app-control page using the runner's pinned Flet extensions.

The caller owns mounting, navigation and lifecycle. Sample rows are ephemeral;
this page never reads or writes application records or native story saves.
"""

import asyncio
import json
import logging
import re


DEFAULT_ROWS = [
    {"name": "Harbor", "count": 5},
    {"name": "Lighthouse", "count": 2},
    {"name": "Observatory", "count": 1},
]
DEFAULT_SOURCE = json.dumps(DEFAULT_ROWS, indent=2)


def validate_rows(value):
    """Return bounded plain rows, or a useful error for edited/loaded data."""
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise ValueError("Use a list containing 1 to 8 rows.")
    rows = []
    names = set()
    for index, item in enumerate(value, 1):
        if not isinstance(item, dict) or set(item) != {"name", "count"}:
            raise ValueError(f"Row {index} needs only name and count.")
        name = item["name"]
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError(f"Row {index} needs a name of 1 to 80 characters.")
        name = name.strip()
        if name in names:
            raise ValueError(f"Duplicate name: {name}.")
        count = item["count"]
        if type(count) is not int or not 0 <= count <= 999:
            raise ValueError(f"Row {index} count must be an integer from 0 to 999.")
        names.add(name)
        rows.append({"name": name, "count": count})
    return rows


async def _load_sample():
    # Keep the real animated pending state observable without a network service.
    await asyncio.sleep(3)
    return validate_rows(DEFAULT_ROWS)


def create_app_recipes_view(page, *, route="/recipes", on_back=None,
                            is_current=lambda: True, load_sample=None):
    """Return an unmounted View and synchronous, idempotent disposer.

    ``is_current`` must describe the caller's mounted view identity/lifecycle.
    An optional async ``load_sample`` returns rows using the same name/count
    schema as the editor. Only the current operation may publish after awaiting.
    """
    import flet as ft
    from flet_code_editor import CodeEditor, CodeLanguage
    from flet_color_pickers import BlockPicker
    from flet_datatable2 import DataColumn2, DataRow2, DataTable2
    from flet_spinkit import ThreeBounce

    rows = validate_rows(DEFAULT_ROWS)
    selected = None
    section = "Editor"
    disposed = False
    load_task = None
    load_generation = 0
    loader = _load_sample if load_sample is None else load_sample

    def current():
        return not disposed and is_current()

    def update():
        if current():
            page.update()

    def result(identifier, text):
        return ft.Semantics(identifier=identifier, content=text)

    editor_result = ft.Text("Edit the sample, then apply it to the table.")
    table_result = ft.Text()
    color_result = ft.Text("Selected color: #1565c0")
    loading_result = ft.Text("Ready to load sample.")
    spinner = ft.Semantics(identifier="recipe-loading", label="Loading sample",
                           content=ThreeBounce(color="#1565c0", size=36), visible=False)

    def table_status():
        table_result.value = ("Order: " + ", ".join(item["name"] for item in rows)
                              + "; Selected: " + (selected or "none"))

    async def select_row(event):
        nonlocal selected
        if (not current() or section != "Table" or type(event.data) is not bool
                or not any(item is event.control for item in table.rows)):
            return
        name = event.control.cells[0].content.value
        if event.data:
            selected = name
        elif selected == name:
            selected = None
        for item in table.rows:
            item.selected = item.cells[0].content.value == selected
        table_status()
        update()

    def render_rows():
        table.rows = [DataRow2(cells=[ft.DataCell(ft.Text(item["name"])),
                                     ft.DataCell(ft.Text(str(item["count"])))],
                              selected=item["name"] == selected,
                              on_select_change=select_row)
                      for item in rows]
        table_status()

    async def sort_rows(event):
        if (not current() or section != "Table" or type(event.column_index) is not int
                or event.column_index not in (0, 1) or type(event.ascending) is not bool):
            return
        field = "name" if event.column_index == 0 else "count"
        rows.sort(key=lambda item: item[field], reverse=not event.ascending)
        table.sort_column_index = event.column_index
        table.sort_ascending = event.ascending
        render_rows()
        update()

    table = DataTable2(columns=[DataColumn2(ft.Text("Name"), on_sort=sort_rows),
                               DataColumn2(ft.Text("Count"), numeric=True,
                                           on_sort=sort_rows)],
                       height=240, min_width=260, show_heading_checkbox=False,
                       data_row_height=48)
    render_rows()

    def replace_rows(replacement):
        nonlocal rows, selected
        rows = replacement
        selected = None
        table.sort_column_index = None
        table.sort_ascending = True
        render_rows()

    def stop_load():
        nonlocal load_task, load_generation
        # Invalidate before cancellation: a real loader may swallow CancelledError.
        load_generation += 1
        task, load_task = load_task, None
        if task is not None:
            task.cancel()
        load_button.disabled = False
        cancel_button.disabled = True
        spinner.visible = False
        return task is not None

    async def editor_changed(event):
        if current() and section == "Editor" and isinstance(event.data, str):
            editor.value = event.data

    editor = CodeEditor(value=DEFAULT_SOURCE, language=CodeLanguage.JSON,
                        height=220, on_change=editor_changed)

    async def apply_json(event):
        if not current() or section != "Editor":
            return
        source = editor.value
        try:
            if not isinstance(source, str) or len(source) > 4096:
                raise ValueError("Use at most 4096 characters of JSON.")
            replacement = validate_rows(json.loads(source))
        except json.JSONDecodeError as error:
            editor_result.value = f"Invalid JSON at line {error.lineno}: {error.msg}."
        except RecursionError:
            editor_result.value = "Use a simple list of name/count rows."
        except ValueError as error:
            editor_result.value = str(error)
        else:
            if stop_load():
                loading_result.value = "Loading cancelled"
            replace_rows(replacement)
            editor_result.value = f"Applied {len(rows)} rows"
        update()

    async def reset_sample(event):
        if not current() or section != "Editor":
            return
        if stop_load():
            loading_result.value = "Loading cancelled"
        editor.value = DEFAULT_SOURCE
        replace_rows(validate_rows(DEFAULT_ROWS))
        editor_result.value = "Applied 3 rows"
        update()

    async def color_changed(event):
        if not current() or section != "Color" or not isinstance(event.data, str):
            return
        color = event.data.lower()
        if re.fullmatch(r"#ff[0-9a-f]{6}", color):
            color = "#" + color[3:]
        if color not in palette:
            return
        picker.color = color
        preview.bgcolor = color
        color_result.value = "Selected color: " + color
        update()

    palette = ["#e91e63", "#1565c0", "#4caf50"]
    picker = BlockPicker(color="#1565c0", available_colors=palette,
                         width=280, height=140, on_color_change=color_changed)
    preview = ft.Container(width=120, height=64, bgcolor="#1565c0", border_radius=8)

    async def finish_load(generation):
        nonlocal load_task
        try:
            replacement = validate_rows(await loader())
        except asyncio.CancelledError:
            return
        except Exception:
            if not current() or generation != load_generation:
                return
            logging.exception("App recipe sample could not be loaded")
            loading_result.value = "Could not load sample. Try again."
        else:
            if not current() or generation != load_generation:
                return
            replace_rows(replacement)
            editor.value = json.dumps(rows, indent=2)
            editor_result.value = f"Applied {len(rows)} rows"
            loading_result.value = f"Loaded {len(rows)} rows"
        finally:
            if current() and generation == load_generation:
                load_task = None
                load_button.disabled = False
                cancel_button.disabled = True
                spinner.visible = False
                update()

    async def start_load(event):
        nonlocal load_task, load_generation
        if not current() or section != "Loading" or load_task is not None:
            return
        load_generation += 1
        load_button.disabled = True
        cancel_button.disabled = False
        spinner.visible = True
        loading_result.value = "Loading sample"
        load_task = asyncio.create_task(finish_load(load_generation))
        update()

    async def cancel_load(event):
        if current() and section == "Loading" and load_task is not None:
            stop_load()
            loading_result.value = "Loading cancelled"
            update()

    load_button = ft.Button("Load sample", on_click=start_load)
    cancel_button = ft.TextButton("Cancel load", disabled=True, on_click=cancel_load)
    sections = {
        "Editor": ft.Column([
            ft.Text("JSON editor", size=22),
            ft.Semantics(identifier="recipe-editor", content=editor),
            ft.Row([ft.Button("Apply JSON", on_click=apply_json),
                    ft.TextButton("Reset sample", on_click=reset_sample)], wrap=True),
            result("recipe-editor-result", editor_result),
        ], spacing=12),
        "Table": ft.Column([
            ft.Text("Sortable table", size=22),
            ft.Semantics(identifier="recipe-table", content=table),
            result("recipe-table-result", table_result),
        ], spacing=12, visible=False),
        "Color": ft.Column([
            ft.Text("Choose a color", size=22),
            ft.Semantics(identifier="recipe-color-picker", content=picker),
            ft.Semantics(identifier="recipe-color-preview", content=preview),
            result("recipe-color-result", color_result),
        ], spacing=12, visible=False),
        "Loading": ft.Column([
            ft.Text("Async loading", size=22),
            ft.Row([load_button, cancel_button], wrap=True), spinner,
            result("recipe-loading-result", loading_result),
        ], spacing=12, visible=False),
    }

    async def select_section(event):
        nonlocal section
        if not current():
            return
        section = event.control.content
        for name, content in sections.items():
            content.visible = name == section
        update()

    async def back(event):
        if current() and on_back is not None:
            await on_back(event)

    view = ft.View(route=route, bgcolor="#101b2b", padding=24, controls=[ft.Column([
        ft.Row([ft.Text("App controls", size=28), ft.TextButton("Back", on_click=back)],
               wrap=True),
        ft.Text("Try these controls with sample data. Changes stay on this page."),
        ft.Row([ft.Button(name, on_click=select_section) for name in sections], wrap=True),
        *sections.values(),
    ], spacing=16, expand=True, scroll=ft.ScrollMode.AUTO)])

    def dispose():
        nonlocal disposed
        disposed = True
        stop_load()

    return view, dispose
