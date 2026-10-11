# Project application navigation

An app project can set `project_setup` to `my_app:register` in `renfletpy.json`.
The SDK calls this synchronous hook once before native restoration or first
rendering, passing `ProjectAPI`. Keep registration free of native operations and
running services. The existing optional `app_home` factory continues to work.

```python
def register(api):
    api.register_screen('/app/editor', editor,
                        state_factory=lambda: {'draft': '', 'selected': None})
    api.register_screen('/app/item/{item_id}', detail, parent='/app/editor')

def editor(ctx):
    # Build a Flet View with route=ctx.route; update ctx.state on input events.
    ...
```

Factories may be async. They return a Flet `View` or `ScreenView(view,
dispose=cancel_work, refresh=refresh_status)`. A disposer is synchronous and
cancels work/releases subscriptions; running work and controls belong to a mount,
never to `ctx.state`. The SDK cancels pending async factories on removal, rejects
late mounting and retires old contexts. Use `ctx.is_current()` before publishing
async results or processing an event that changes application state.

`ctx.state` is a mutable plain dictionary owned by the navigation session. Its
factory runs once per canonical path. Query changes reuse the screen, and aliases
share its state. Parameter paths have independent state by default. An explicit
`state_key` shares a model across screens, as in the notebook/detail example.
Views reconstruct controls from this model. State survives rebuilding, settings
changes, disconnect/reconnect and story transitions in that page session. Durable
app records still use application storage; drafts are session data, not promised
across process termination. Native story saves never rewind app data or drafts.

The context exposes `page`, `route`, `params`, `query` (lists of query values),
`large_text`, `story_status`, async `navigate`, `back`, `refresh`,
`request_story`, `start_story`, `resume_story`, `show_dialog`, `dismiss_dialog` and
`is_current`. Start/Resume use the existing revision-guarded native mailbox;
acceptance does not navigate before the native acknowledgement.

| Action | Behavior |
| --- | --- |
| Direct link | Registered literal/parameter route opens through normal SDK routing. Unknown app links fall back to Home; they cannot reveal a returned story. |
| Back | Dismiss the newest open project dialog first; then visit the preceding app screen. A cold direct link uses its declared `parent`. Query changes replace the current history entry. |
| Dialog | `ctx.show_dialog` uses Flet's managed dialog lifecycle. Removal/rebuilding dismisses it; a save confirmation must revalidate current data, not survive a story load. |
| Start story | Available from any registered app screen. Replacing a live/saved story requires the existing explicit `replace=True` confirmation. Capture the invoking route, then wait for native acknowledgement. |
| Return / completion | Return to the invoking app route and reconstruct its view from the retained model. Newer explicit navigation wins over a delayed acknowledgement. Completion publishes the existing plain result. |
| Automatic recovery | Keeps registered app routes. Explicit Saved games load opens the loaded story, and Return goes back to that browser. |

Records and Saved games register `ScreenView` factories through the same screen
interface. Their draft fields use independent app-owned models; Records/Edit
selection survives remounting. Save confirmations remain transient and retain
native slot/revision checks. The default story-first entry and SDK menus remain.

Create a real external example without editing SDK routing:

```sh
python examples/project_app/create.py ../notebook
python build_android.py --project ../notebook/renfletpy.json
```

It registers a notebook, an alias and parameterized entry pages. Edit a draft,
change selection, start the story, Return, open a detail link, and use Back. The
draft and selection remain. Dart/native changes still require rebuilding the APK.
