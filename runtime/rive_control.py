"""Interactive Rive controls for the runner's pinned Rive 0.14.11 adapter.

Persist ``numbers`` and ``booleans`` in a game model. Reconstruct this control
from those values after navigation/load. Triggers are immediate commands: they
are rejected while loading/paused and are never queued or replayed on remount.
"""

import math
from dataclasses import field
from typing import Optional

import flet as ft


@ft.control("sdk_rive_interactive")
class InteractiveRive(ft.LayoutControl):
    """One state machine with application inputs and plain event callbacks.

    Sources resolve through Flet's normal asset source resolver. ``artboard``
    and ``use_artboard_size`` use the same canonical names as ``flet_rive.Rive``.
    Input names belong to the selected state machine; unknown names or a wrong
    input type produce ``on_error`` and an error control. The adapter uses the
    pinned native Rive renderer on Android.

    ``on_ready`` reports artboard/machine names, bounds and input names/types.
    ``on_event`` reports name, type, machine, seconds_delay and scalar custom
    properties (plus URL/target for URL events). URLs are reported, never opened
    automatically. ``on_input_change`` reports the current number/boolean values
    after a machine or pointer changes them. ``on_state_change`` reports machine
    layer state names. ``on_lifecycle`` reports effective playback transitions.
    Event data is a plain dictionary; no native event/controller objects cross
    the Python boundary.
    """

    src: str
    artboard: Optional[str] = None
    state_machine: Optional[str] = None
    numbers: dict[str, float] = field(default_factory=dict)
    booleans: dict[str, bool] = field(default_factory=dict)
    use_artboard_size: bool = False
    fit: ft.BoxFit = ft.BoxFit.CONTAIN
    alignment: Optional[ft.Alignment] = None
    playing: bool = True
    speed_multiplier: float = 1.0
    headers: Optional[dict[str, str]] = None
    placeholder: Optional[ft.Control] = None
    clip_rect: Optional[ft.Rect] = None
    on_ready: Optional[ft.ControlEventHandler["InteractiveRive"]] = None
    on_event: Optional[ft.ControlEventHandler["InteractiveRive"]] = None
    on_input_change: Optional[ft.ControlEventHandler["InteractiveRive"]] = None
    on_state_change: Optional[ft.ControlEventHandler["InteractiveRive"]] = None
    on_lifecycle: Optional[ft.ControlEventHandler["InteractiveRive"]] = None
    on_error: Optional[ft.ControlEventHandler["InteractiveRive"]] = None

    def before_update(self):
        if not isinstance(self.src, str) or not self.src:
            raise ValueError("Rive requires a nonempty asset path or URL")
        if not isinstance(self.numbers, dict) or not isinstance(self.booleans, dict):
            raise ValueError("Rive input values must be dictionaries keyed by input name")
        for name, value in self.numbers.items():
            if not isinstance(name, str) or not name:
                raise ValueError("Rive number input names must be nonempty strings")
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("Rive number inputs must be finite numbers")
        for name, value in self.booleans.items():
            if not isinstance(name, str) or not name or type(value) is not bool:
                raise ValueError("Rive boolean inputs need a name and boolean value")
        if (type(self.speed_multiplier) not in (int, float)
                or not math.isfinite(self.speed_multiplier)
                or self.speed_multiplier < 0):
            raise ValueError("Rive playback speed must be finite and nonnegative")

    async def fire(self, name: str, *, timeout: float = 10.0) -> dict:
        """Fire a root trigger once and return the runtime acknowledgement.

        A rejected trigger raises ``RuntimeError`` with the runtime reason.
        It has no saved representation and is not retained until a later frame,
        source, foreground transition or control mount.
        """
        if not isinstance(name, str) or not name:
            raise ValueError("Rive trigger name must be a nonempty string")
        result = await self._invoke_method("fire", {"name": name}, timeout=timeout)
        if not isinstance(result, dict) or result.get("accepted") is not True:
            reason = result.get("reason", "invalid response") if isinstance(result, dict) else "invalid response"
            raise RuntimeError("Rive trigger rejected: " + str(reason))
        return result

    async def snapshot(self, *, timeout: float = 10.0) -> dict:
        """Read current scalar values for diagnostics or a defined model command.

        Story saves use the owning activity model. Calling this method does not
        save a story or serialize a running state machine.
        """
        result = await self._invoke_method("snapshot", timeout=timeout)
        if not isinstance(result, dict) or result.get("ready") is not True:
            raise RuntimeError("Rive control is not ready")
        return result
