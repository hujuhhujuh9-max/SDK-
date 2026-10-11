"""Project-owned wire API for an animated, interactive Flutter dial."""

import math
from dataclasses import dataclass
from typing import Optional

import flet as ft


@dataclass
class PulseChangeEvent(ft.Event["PulseDial"]):
    value: float
    source: str


@dataclass
class PulseLifecycleEvent(ft.Event["PulseDial"]):
    phase: str
    running: bool


@dataclass
class PulseErrorEvent(ft.Event["PulseDial"]):
    message: str


@ft.control("project_pulse.PulseDial")
class PulseDial(ft.LayoutControl):
    """Paint locally on Flutter's ticker; keep selection in the Python model.

    Tap selects 0..100 clockwise from twelve o'clock. The component never writes
    a selection behind the Python model's back. Removal releases its ticker and
    listeners; navigation can rebuild it from these plain properties.
    """

    value: float = 25.0
    intensity: float = 0.7
    running: bool = True
    period_ms: int = 1600
    palette_asset: str = "assets/palette.json"
    on_change: Optional[ft.EventHandler[PulseChangeEvent]] = None
    on_lifecycle: Optional[ft.EventHandler[PulseLifecycleEvent]] = None
    on_error: Optional[ft.EventHandler[PulseErrorEvent]] = None

    def before_update(self):
        if (type(self.value) not in (int, float) or not math.isfinite(self.value)
                or not 0 <= self.value <= 100):
            raise ValueError("PulseDial.value must be finite and between 0 and 100.")
        if (type(self.intensity) not in (int, float) or not math.isfinite(self.intensity)
                or not 0 <= self.intensity <= 1):
            raise ValueError("PulseDial.intensity must be finite and between 0 and 1.")
        if type(self.period_ms) is not int or not 200 <= self.period_ms <= 10000:
            raise ValueError("PulseDial.period_ms must be an integer from 200 to 10000.")
        if type(self.running) is not bool:
            raise ValueError("PulseDial.running must be a boolean.")
        if not isinstance(self.palette_asset, str) or not self.palette_asset:
            raise ValueError("PulseDial.palette_asset must name a package asset.")


__all__ = ["PulseDial", "PulseChangeEvent", "PulseLifecycleEvent", "PulseErrorEvent"]
