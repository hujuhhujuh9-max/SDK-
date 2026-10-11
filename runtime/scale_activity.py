"""The project-defined Canvas activity, using the same reducer as its app screen."""

import copy

if __package__:
    from .scale_workloads import canvas_state, canvas_command, validate_canvas
else:
    from scale_workloads import canvas_state, canvas_command, validate_canvas


def render_scale_activity(ctx):
    import flet as ft
    if __package__:
        from .scale_ui import CanvasPanel, marker
        from .story_activities import ActivityView
    else:
        from scale_ui import CanvasPanel, marker
        from story_activities import ActivityView

    # Retain controls and gesture tracking for ordinary commits. Navigation,
    # load and process reopening reconstruct this presentation from plain data.
    panel = CanvasPanel(ft.context.page, ctx.state, ctx.command, allow_run=False)

    def refresh(current):
        nonlocal ctx
        if not panel.active():
            return
        ctx = current
        panel.command = current.command
        # A later gesture packet may already be optimistic while native code
        # publishes an earlier acknowledgement. Do not roll back its camera
        # while retaining the newer cumulative gesture scale. Native rejection
        # explicitly restores the last committed state.
        if current.error or current.state["revision"] >= panel.state["revision"]:
            committed = copy.deepcopy(current.state)
            panel.state.clear()
            panel.state.update(committed)
        panel.redraw()
        marker("ACTIVITY_STATE", kind="scale_canvas", phase="rendered", revision=current.revision,
               state=current.state)

    def complete(event):
        if panel.active():
            ctx.complete({"selected": panel.state["selected"], "camera": dict(panel.state["camera"]),
                          "input_receipts": panel.state["input_receipts"]})

    def cancel(event):
        if panel.active():
            ctx.cancel({"reason": "user"})

    controls = [ft.Text("Story Canvas", size=26), *panel.controls,
                ft.Row([ft.Button("Return selection", on_click=complete),
                        ft.TextButton("Cancel Canvas", on_click=cancel)], wrap=True)]
    marker("ACTIVITY_STATE", kind="scale_canvas", phase="rendered", revision=ctx.revision, state=ctx.state)
    return ActivityView(controls, refresh, dispose=panel.close)


def migrate_scale_v1(state):
    # Version 1 saved camera/selection but did not count input acknowledgements.
    state = dict(state)
    state.setdefault("input_receipts", 0)
    state.setdefault("revision", 0)
    return state


def validate_scale_state(state):
    validate_canvas(state)
    return True


def validate_scale_result(result):
    value = result.value
    if result.status == "cancelled":
        if value != {"reason": "user"}:
            raise ValueError("Canvas cancellation requires its explicit user reason")
        return True
    if result.status != "completed" or not isinstance(value, dict) or set(value) != {
            "selected", "camera", "input_receipts"}:
        raise ValueError("Canvas completion requires selected node, camera and input count")
    state = canvas_state()
    state.update(value)
    return validate_scale_state(state)


def register_scale_activity(api=None):
    if api is None:
        if __package__:
            from .story_activities import register_activity
        else:
            from story_activities import register_activity
    else:
        register_activity = api.register_activity
    return register_activity("scale_canvas", version=2, create_state=canvas_state,
                             renderer=render_scale_activity, reduce=canvas_command,
                             validate_state=validate_scale_state, migrations={1: migrate_scale_v1},
                             validate_result=validate_scale_result,
                             title="Story Canvas", description="Saveable camera and node selection")
