"""An opt-in, reusable Flet form/list view; routing stays with its caller."""

import logging
from dataclasses import dataclass

if __package__:
    from .application_data import DEFAULT_STORAGE_KEY, get_application_data_store
else:
    from application_data import DEFAULT_STORAGE_KEY, get_application_data_store


@dataclass(frozen=True)
class FormField:
    name: str
    label: str
    required: bool = False
    multiline: bool = False
    max_length: int = 2000

    def __post_init__(self):
        if (not isinstance(self.name, str) or not self.name.strip()
                or not isinstance(self.label, str) or not self.label.strip()):
            raise ValueError("Fields need nonempty names and labels")
        if type(self.max_length) is not int or self.max_length < 1:
            raise ValueError("Field max_length must be a positive integer")


DEFAULT_FIELDS = (
    FormField("title", "Title", required=True, max_length=200),
    FormField("details", "Details", multiline=True),
)


async def create_form_list_view(page, *, route="/records", title="Application records",
                                fields=DEFAULT_FIELDS, storage_key=DEFAULT_STORAGE_KEY,
                                on_back=None):
    """Return a loaded View without mounting it or changing page navigation.

    Call in a Flet page/event context. The caller owns page.views, route handlers
    and presentation. Give independent collections different storage keys.
    on_back, when supplied, is a normal Flet button event handler.
    """
    fields = tuple(fields)
    if (not fields or any(not isinstance(field, FormField) for field in fields)
            or len({field.name for field in fields}) != len(fields)):
        raise ValueError("Supply at least one FormField with unique names")

    import flet as ft

    store = get_application_data_store(page, storage_key)
    inputs = {field.name: ft.TextField(label=field.label, value="",
                                      multiline=field.multiline,
                                      min_lines=3 if field.multiline else 1,
                                      max_length=field.max_length)
              for field in fields}
    status = ft.Text("")
    record_list = ft.Column(spacing=12)
    records = []
    editing_id = None
    busy = False
    loaded = False
    row_buttons = []

    def set_enabled():
        for control in [*inputs.values(), save_button, *row_buttons]:
            control.disabled = busy or not loaded
        cancel_button.disabled = busy
        reload_button.disabled = busy

    def reset_form():
        nonlocal editing_id
        editing_id = None
        for control in inputs.values():
            control.value = ""
            control.error_text = None
        save_button.content = "Add record"
        cancel_button.visible = False

    def cancel_edit(event):
        if busy:
            return
        reset_form()
        status.value = "Edit cancelled"
        page.update()

    def edit_record(record):
        def clicked(event):
            nonlocal editing_id
            if busy or not loaded:
                return
            editing_id = record["id"]
            for name, control in inputs.items():
                control.value = record["values"].get(name, "")
                control.error_text = None
            save_button.content = "Save changes"
            cancel_button.visible = True
            status.value = "Editing record"
            page.update()
        return clicked

    def render_records():
        row_buttons.clear()
        record_list.controls = []
        for record in records:
            edit = ft.TextButton("Edit", on_click=edit_record(record))
            delete = ft.TextButton("Delete", on_click=delete_record(record["id"]))
            row_buttons.extend([edit, delete])
            lines = [ft.Text(f"{field.label}: {record['values'].get(field.name, '')}")
                     for field in fields]
            record_list.controls.append(ft.Container(
                content=ft.Column([*lines, ft.Row([edit, delete], wrap=True)]),
                padding=12, border_radius=8))
        if not records:
            record_list.controls = [ft.Text("No records yet. Add your first record above.")]

    async def perform(operation, message, *, clear_form=False, loading=False, update=True):
        nonlocal busy, loaded, records
        if busy:
            return
        busy = True
        set_enabled()
        try:
            if update:
                page.update()
            records = await operation()
            loaded = True
            if clear_form:
                reset_form()
            render_records()
            status.value = message
        except Exception:
            logging.exception("Application record operation failed")
            if loading:
                loaded = False
                status.value = "Saved records could not be loaded. Reload to try again."
            else:
                status.value = "Changes could not be saved. Your form is kept. Try again."
        finally:
            busy = False
            set_enabled()
            if update:
                page.update()

    async def save_record(event):
        if busy or not loaded:
            return
        values = {name: (control.value or "").strip() for name, control in inputs.items()}
        valid = True
        for field in fields:
            error = None
            if field.required and not values[field.name]:
                error = f"{field.label} is required"
            elif len(values[field.name]) > field.max_length:
                error = f"Use at most {field.max_length} characters"
            inputs[field.name].error_text = error
            valid = valid and error is None
        if not valid:
            status.value = "Check the highlighted fields"
            page.update()
            return
        await perform(lambda: store.save(values, editing_id), "Record saved", clear_form=True)

    def delete_record(record_id):
        async def clicked(event):
            if busy or not loaded:
                return
            await perform(lambda: store.delete(record_id), "Record deleted",
                          clear_form=editing_id == record_id)
        return clicked

    async def reload_records(event):
        await perform(store.load, "Records loaded", loading=True)

    save_button = ft.Button("Add record", on_click=save_record)
    cancel_button = ft.TextButton("Cancel edit", on_click=cancel_edit, visible=False)
    reload_button = ft.TextButton("Reload", on_click=reload_records)
    heading = [ft.Text(title, size=28, expand=True)]
    if on_back is not None:
        heading.append(ft.TextButton("Back", on_click=on_back))
    view = ft.View(route=route, padding=24, controls=[ft.Column([
        ft.Row(heading, wrap=True),
        *inputs.values(),
        ft.Row([save_button, cancel_button, reload_button], wrap=True),
        status,
        record_list,
    ], spacing=16, expand=True, scroll=ft.ScrollMode.AUTO)])
    await perform(store.load, "Records loaded", loading=True, update=False)
    return view
