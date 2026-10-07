# Optional application form/list screen

The combined runner opens this optional screen from **Device diagnostics →
Application records**, or with `sdk-runner:///records` (including query strings).
Back returns to diagnostics; **Return to story** resumes the existing native
story. Ordinary startup still opens the current demo. Repeated query links keep
the mounted form draft; leaving and reopening reloads persisted records. Automatic
story recovery respects an explicit records link.

The integration entry function is
`async create_form_list_view(page, *, route="/records", title="Application records",
fields=DEFAULT_FIELDS, storage_key=DEFAULT_STORAGE_KEY, on_back=None)` in
`runtime/form_list.py`. It returns a loaded Flet `View`. Call it from the current
page's Flet app or event context, then mount the returned view in the integration
layer. The function leaves `page.views`, `page.route`, route/pop callbacks and
the runner's presentation alone.

An integration route can use:

```python
from form_list import FormField, create_form_list_view

async def back(event):
    await navigate("/menu")

# Inside the integration agent's chosen route branch:
view = await create_form_list_view(
    page,
    route=route,
    title="Field notes",
    storage_key="sdk.runner.application.field_notes",
    fields=(
        FormField("title", "Title", required=True, max_length=200),
        FormField("notes", "Notes", multiline=True, max_length=2000),
    ),
    on_back=back,
)
set_presentation("page")
page.views.append(view)
page.update()
```

The caller decides the route, view stack, navigation links and native/Flet
presentation, including restoration when leaving the screen. Reuse the mounted
view when only its route query changes. No route, SDK registration, dependency,
component pin or Android/Flutter file is changed by this feature. Android assembly
already copies every top-level `runtime/*.py` module into the private payload.
Package imports such as `from runtime.form_list import create_form_list_view`
also work for host code.

The default form has a required Title and optional multiline Details. A custom
schema consists of one or more `FormField` objects with unique, stable names.
Labels, required fields, multiline input and maximum lengths are configurable.
Text is trimmed on submission, validated inline, and displayed in a scrollable
list. Users can add, edit, cancel edits, delete and reload records. Cancelling an
edit leaves persisted data intact; reloading preserves the current form draft.
If the edited record was deleted elsewhere, Reload keeps the draft and switches
the form to Add record, allowing the user to save it with a new ID or cancel.

`runtime/application_data.py` stores small local collections as versioned JSON
strings through the existing asynchronous `ft.SharedPreferences.get/set` APIs.
The default key is `sdk.runner.application.records`. Assign each independent
collection a distinct key. Keys are separate from diagnostic challenges and
Ren'Py save data, so loading an older story save keeps current application records.
Native preferences retain records across page replacement and app restarts on
the same installation; clearing app data or uninstalling removes them.

One preferences service is retained per page and one `ApplicationDataStore` per
key. Each mutation reads current persisted records under that store's async lock
before writing, preventing lost updates between views sharing it. Separate pages
or processes need their own coordination if they edit the same key. Stable IDs
identify edits/deletes. Edits preserve fields absent from the visible schema;
unknown schema versions, corrupt JSON and duplicate IDs block writes. A missing
edited ID raises an error instead of recreating a deleted record.

Load failures disable mutation controls until Reload succeeds. Write failures
keep the form and displayed records available for retry. Duplicate submissions
are ignored while an operation is running, and cancellation releases the busy
guard. A cancelled native write can still complete on the device, so an
interrupted mutation disables further mutations and prompts the user to Reload.
After a successful reload, the persisted result is visible and the user can
decide whether to edit a saved record, add the remaining draft, or cancel it.

Dedicated host tests:

```sh
python3 -m unittest discover -s tests -p 'test_application_data.py' -v
python3 -m unittest discover -s tests -p 'test_form_list.py' -v
```

After preparing the patched Flet source with the existing runtime workflow,
the dedicated Flet tests use real controls, event dispatch, service registration
and method messages, with native preference replies emulated on the host:

```sh
.android-build/venv/bin/python scripts/check_runtime.py
PYTHONPATH=.android-build/runtime-inspection/flet/sdk/python/packages/flet/src \
  .android-build/venv/bin/python -m unittest discover -s tests -p 'test_form_list_flet.py' -v
```
