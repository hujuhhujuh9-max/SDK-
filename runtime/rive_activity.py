"""A versioned Rive console activity: durable values, transient trigger/events."""

import json
import math


ACTIVITY_KIND = "rive_console"
MODEL_VERSION = 2
TREE_SOURCE = "rive/tree_loading_bar.riv"
SIGNAL_SOURCE = "rive/events_test.riv"
LOOP_SOURCE = "rive/off_road_car.riv"
FOREST_INPUT_MAX = 99.0
SIGNAL_PROPERTIES = {"SomeNumber": 11.0, "SomeBoolean": True, "SomeString": "Something"}


def forest_progress(progress):
    """Project the game percentage into the fixture's supported visual range.

    The unmodified forest asset repeatedly hits its native state-machine
    iteration limit at 100. Game progress and completion still reach 100;
    only this example's art input has a documented maximum of 99.
    """
    return min(progress, FOREST_INPUT_MAX)


def create_state():
    return {"progress": 25.0, "downloading": True, "receipt": None}


def validate_state(state):
    if not isinstance(state, dict) or set(state) != {"progress", "downloading", "receipt"}:
        return False
    progress = state["progress"]
    if type(progress) not in (int, float) or not math.isfinite(progress) or not 0 <= progress <= 100:
        return False
    if type(state["downloading"]) is not bool:
        return False
    return (state["receipt"] is None or
            (isinstance(state["receipt"], dict) and state["receipt"] == SIGNAL_PROPERTIES
             and type(state["receipt"].get("SomeBoolean")) is bool))


def migrate_v1(state):
    """The original model saved progress only; add explicit playback state."""
    if not isinstance(state, dict) or set(state) != {"progress"}:
        raise ValueError("Version 1 Rive state requires progress only")
    return {"progress": state["progress"], "downloading": True, "receipt": None}


def validate_result(result):
    value = result.value
    if not isinstance(value, dict):
        return False
    if result.status == "completed":
        return (set(value) == {"progress", "downloading", "signal"}
                and type(value["progress"]) in (int, float) and value["progress"] == 100
                and type(value["downloading"]) is bool
                and value["signal"] == SIGNAL_PROPERTIES
                and type(value["signal"].get("SomeBoolean")) is bool)
    progress = value.get("progress")
    return (result.status == "cancelled" and set(value) == {"progress", "reason"}
            and type(progress) in (int, float) and math.isfinite(progress) and 0 <= progress <= 100
            and value["reason"] == "user_cancelled")


def reduce_state(state, command, payload):
    # Imported here so pure state validation/migrations need neither Flet nor
    # a loaded Ren'Py interpreter.
    if __package__:
        from .story_activities import ActivityResult, ActivityTransition
    else:
        from story_activities import ActivityResult, ActivityTransition

    if command == "progress":
        if type(payload) not in (int, float) or not math.isfinite(payload) or not 0 <= payload <= 100:
            raise ValueError("Progress must be between 0 and 100")
        state["progress"] = float(payload)
        state["receipt"] = None
    elif command == "downloading":
        if type(payload) is not bool:
            raise ValueError("Downloading must be a boolean")
        state["downloading"] = payload
    elif command == "receipt":
        if not isinstance(payload, dict) or payload.get("name") != "SomeGeneralEvent" or payload.get("type") != "general":
            raise ValueError("Expected a Rive general event")
        properties = payload.get("properties")
        if properties != SIGNAL_PROPERTIES or type(properties.get("SomeBoolean")) is not bool:
            raise ValueError("Unexpected Rive event properties")
        state["receipt"] = dict(properties)
        if state["progress"] == 100:
            return ActivityTransition(state, ActivityResult("completed", {
                "progress": state["progress"], "downloading": state["downloading"],
                "signal": dict(properties),
            }))
    elif command == "cancel" and payload is None:
        return ActivityTransition(state, ActivityResult("cancelled", {
            "progress": state["progress"], "reason": "user_cancelled",
        }))
    else:
        raise ValueError("Unknown Rive console command: " + command)
    return state


def render(context):
    import flet as ft
    if __package__:
        from .rive_control import InteractiveRive, RivePlayback
    else:
        from rive_control import InteractiveRive, RivePlayback

    state = context.state
    status = ft.Text("Ready. Values survive a story save; controller playback restarts on load.")
    ready = {}
    profile_emitted = False

    def diagnostic(kind, role, event):
        print("SDK_CAP_RIVE_" + kind + " " + json.dumps({
            "role": role, "revision": context.revision, "data": event.data,
        }, sort_keys=True), flush=True)

    def controller_ready(role, event):
        nonlocal profile_emitted
        diagnostic("READY", role, event)
        ready[role] = event.data
        if set(ready) == {"forest", "signal", "loop"} and not profile_emitted:
            profile_emitted = True
            input_types = [kind for manifest in ready.values() for kind in manifest["inputs"].values()]
            print("SDK_2D_READY " + json.dumps({
                "workload": "rive", "tier": "nominal", "controllers": len(ready),
                "number_inputs": input_types.count("number"),
                "boolean_inputs": input_types.count("boolean"),
                "trigger_inputs": input_types.count("trigger"),
            }, sort_keys=True), flush=True)

    def signal_received(event):
        diagnostic("EVENT", "signal", event)
        context.command("receipt", event.data)

    signal = InteractiveRive(
        src=SIGNAL_SOURCE, artboard="New Artboard", state_machine="State Machine 1",
        key="rive-console-signal-" + str(context.revision), width=72, height=72,
        on_ready=lambda event: controller_ready("signal", event),
        on_event=signal_received,
        on_lifecycle=lambda event: diagnostic("LIFECYCLE", "signal", event),
        on_error=lambda event: show_status("Rive failed: " + str(event.data)),
    )

    def show_status(value):
        # A method reply may arrive after a published model or route replaced
        # this renderer. Removed controls are no longer a destination for UI.
        try:
            page = status.page
        except RuntimeError:
            return
        if page.session.index.get(status._i) is not status:
            return
        status.value = value
        status.update()

    async def transmit(event):
        try:
            await signal.fire("FireGeneralEvent")
            show_status("Signal sent; waiting for the state-machine event.")
        except (RuntimeError, TimeoutError) as error:
            show_status(str(error))

    async def open_menu(event):
        # The SDK menu performs Return with its native acknowledgement.
        await context.navigate("/menu")

    forest = InteractiveRive(
        key="rive-console-forest-" + str(context.revision), src=TREE_SOURCE, state_machine="Loading", height=220, fit=ft.BoxFit.CONTAIN,
        numbers={"Progress": forest_progress(state["progress"])}, booleans={"Downloading": state["downloading"]},
        on_ready=lambda event: controller_ready("forest", event),
        on_input_change=lambda event: diagnostic("INPUT", "forest", event),
        on_lifecycle=lambda event: diagnostic("LIFECYCLE", "forest", event),
        on_error=lambda event: show_status("Rive failed: " + str(event.data)),
    )
    loop = RivePlayback(
        key="rive-console-loop-" + str(context.revision), src=LOOP_SOURCE, animations=["bouncing"], width=140, height=140,
        fit=ft.BoxFit.CONTAIN, speed_multiplier=1.0 if state["downloading"] else 0.0,
        on_ready=lambda event: controller_ready("loop", event),
        on_lifecycle=lambda event: diagnostic("LIFECYCLE", "loop", event),
        on_error=lambda event: show_status("Rive failed: " + str(event.data)),
    )

    return [
        ft.Text("Rive transmission console", size=24 if context.large_text else 20),
        ft.Text("Set transmission progress, save halfway, reopen, then finish at 100%."),
        ft.Row([ft.Semantics(identifier="cap-rive-forest", content=forest, expand=True),
                ft.Semantics(identifier="cap-rive-loop", label="Looping rover", content=loop)]),
        ft.Text("Progress: " + str(int(state["progress"])) + "%"),
        ft.Slider(min=0, max=100, divisions=20, value=state["progress"],
                  on_change_end=lambda event: context.command("progress", event.control.value)),
        ft.Switch(label="Play the forest and looping rover", value=state["downloading"],
                  on_change=lambda event: context.command("downloading", event.control.value)),
        ft.Row([ft.Semantics(identifier="cap-rive-signal", content=signal),
                ft.Button("Send signal", on_click=transmit)]),
        status,
        ft.Text("Last event: " + ("none" if state["receipt"] is None else str(state["receipt"]))),
        ft.Row([ft.Button("Story menu", on_click=open_menu),
                ft.Button("Cancel transmission", on_click=lambda event: context.command("cancel"))]),
    ]


def register_rive_activity(registry=None):
    if __package__:
        from .story_activities import activities
    else:
        from story_activities import activities

    target = activities if registry is None else registry
    register = getattr(target, "register_activity", None) or target.register

    return register(
        ACTIVITY_KIND, version=MODEL_VERSION, create_state=create_state, renderer=render,
        reduce=reduce_state, validate_state=validate_state, validate_result=validate_result,
        migrations={1: migrate_v1},
        title="Rive transmission console", description="Saveable animation inputs and native event result",
    )
