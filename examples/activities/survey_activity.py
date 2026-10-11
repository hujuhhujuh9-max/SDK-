"""Project-owned field survey. Registration needs no SDK kind or route edits."""

try:
    from story_activities import ActivityResult, ActivityTransition
except ImportError:
    from runtime.story_activities import ActivityResult, ActivityTransition


SAMPLES = {"telescope": "Telescope", "spectrograph": "Spectrograph", "lens": "Lens"}


def create_state():
    return {"samples": [], "draft": "", "selected": "telescope", "notes": {}}


def validate_state(state):
    return (set(state) == {"samples", "draft", "selected", "notes"}
            and isinstance(state["samples"], list)
            and all(isinstance(sample, str) and sample in SAMPLES for sample in state["samples"])
            and len(set(state["samples"])) == len(state["samples"])
            and isinstance(state["draft"], str) and len(state["draft"]) <= 4000
            and isinstance(state["selected"], str) and state["selected"] in SAMPLES
            and isinstance(state["notes"], dict)
            and set(state["notes"]) == set(state["samples"])
            and all(isinstance(note, str) and len(note) <= 4000 for note in state["notes"].values()))


def migrate_v1(state):
    """Version 1 stored collected IDs and one unfinished note, without selection."""
    if set(state) != {"found", "note"} or not isinstance(state["found"], list):
        raise ValueError("Invalid version 1 field survey")
    return {"samples": state["found"], "draft": state["note"], "selected": "telescope",
            "notes": {sample: "" for sample in state["found"]}}


def validate_result(result):
    if result.status == "cancelled":
        return result.value is None or result.value == {"reason": "later"}
    value = result.value
    return (isinstance(value, dict) and set(value) == {"samples", "notes"}
            and validate_state({**create_state(), **value}) and len(value["samples"]) >= 2)


def reduce(state, name, payload):
    if name == "select" and isinstance(payload, str) and payload in SAMPLES:
        state["selected"] = payload
    elif name == "draft" and isinstance(payload, str) and len(payload) <= 4000:
        state["draft"] = payload
    elif name == "record" and payload is None:
        selected = state["selected"]
        if selected not in state["samples"]:
            state["samples"].append(selected)
        state["notes"][selected] = state["draft"]
    elif name == "finish" and payload is None and len(state["samples"]) >= 2:
        return ActivityTransition(state, ActivityResult("completed", {
            "samples": state["samples"], "notes": state["notes"]}))
    else:
        raise ValueError("Unknown or unavailable survey command")
    return state


def render(context):
    import flet as ft

    state = context.state
    finished = context.result is not None

    def submit(name, payload=None):
        async def clicked(event):
            context.command(name, payload)
        return clicked

    async def edit(event):
        context.command("draft", event.control.value or "")

    async def menu(event):
        await context.navigate("/menu")

    async def cancel(event):
        context.cancel({"reason": "later"})

    return [ft.Container(ft.Column([
        ft.Row([ft.Text("Field survey", size=30 if context.large_text else 24, expand=True),
                ft.TextButton("Menu", on_click=menu)]),
        ft.Text("Record notes for at least two instruments, then bring the survey back to the story."),
        ft.Row([ft.Button(label, on_click=submit("select", sample), disabled=finished,
                          bgcolor="#42685e" if sample == state["selected"] else "#294559")
                for sample, label in SAMPLES.items()], wrap=True),
        ft.TextField(value=state["draft"], label="Unfinished observation", multiline=True,
                     key="survey-draft", on_change=edit, disabled=finished),
        ft.Text("Selected: " + SAMPLES[state["selected"]]),
        ft.Button("Record observation", on_click=submit("record"), disabled=finished),
        ft.Text("Recorded: " + (", ".join(SAMPLES[sample] for sample in state["samples"]) or "none")),
        ft.Text(context.error, color="#e5a0a0"),
        ft.Row([ft.Button("Finish survey", on_click=submit("finish"),
                          disabled=finished or len(state["samples"]) < 2),
                ft.TextButton("Do this later", on_click=cancel, disabled=finished)], wrap=True),
    ], spacing=14, scroll=ft.ScrollMode.AUTO), padding=20, bgcolor="#101b2b", expand=True)]


def register(api):
    return api.register_activity("field_survey", version=2, create_state=create_state,
                                 renderer=render, reduce=reduce, validate_state=validate_state,
                                 migrations={1: migrate_v1}, validate_result=validate_result,
                                 title="Field survey", description="Record the instruments before sunrise.")
