"""Project story activities: transient factories around versioned plain game data.

Renderers run on Flet's loop. They submit commands, never call Ren'Py. Reducers
run when the native story owner drains the mailbox. Only validated model data
and terminal results enter saves; controls, listeners and services do not.
"""

import inspect
import json
import math
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import MappingProxyType


MAX_DATA_BYTES = 1024 * 1024
BUILTIN_KINDS = frozenset(("panel", "star_map", "tactics"))


def _call(callback, *args):
    value = callback(*args)
    if inspect.isawaitable(value):
        if inspect.iscoroutine(value):
            value.close()
        raise TypeError("Activity factories, renderers and reducers must finish synchronously")
    return value


def plain_copy(value):
    """Detach finite JSON data and reject live objects, cycles and oversized data."""
    path = set()
    nodes = 0

    def copy(item, depth=0):
        nonlocal nodes
        nodes += 1
        if depth > 32 or nodes > 100000:
            raise ValueError("Activity data exceeds its nesting or item limit")
        if item is None:
            return None
        if isinstance(item, str):
            return str(item)
        if isinstance(item, bool):
            return bool(item)
        if isinstance(item, int):
            return int(item)
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError("Activity numbers must be finite")
            return float(item)
        if not isinstance(item, (dict, list)):
            raise ValueError("Activity data must contain only JSON values")
        identity = id(item)
        if identity in path:
            raise ValueError("Activity data cannot contain a cycle")
        path.add(identity)
        try:
            if isinstance(item, dict):
                if any(not isinstance(key, str) for key in item):
                    raise ValueError("Activity object keys must be strings")
                return {str(key): copy(child, depth + 1) for key, child in item.items()}
            return [copy(child, depth + 1) for child in item]
        finally:
            path.remove(identity)

    result = copy(value)
    if len(json.dumps(result, ensure_ascii=True, allow_nan=False).encode("utf-8")) > MAX_DATA_BYTES:
        raise ValueError("Activity data exceeds its 1 MiB limit")
    return result


@dataclass(frozen=True)
class ActivityResult:
    """One native return value. Cancellation is explicit, never a missing result."""

    status: str
    value: object = None

    def snapshot(self):
        if self.status not in ("completed", "cancelled"):
            raise ValueError("Activity result requires completed or cancelled status")
        return {"status": self.status, "value": plain_copy(self.value)}

    @classmethod
    def from_snapshot(cls, data):
        if not isinstance(data, dict) or set(data) != {"status", "value"}:
            raise ValueError("Invalid activity result")
        result = cls(data["status"], plain_copy(data["value"]))
        result.snapshot()
        return result


@dataclass(frozen=True)
class ActivityTransition:
    state: dict
    result: ActivityResult | None = None


@dataclass(frozen=True)
class ActivityDefinition:
    name: str
    version: int
    create_state: object
    renderer: object
    reduce: object
    validate_state: object = None
    migrations: dict = field(default_factory=dict)
    validate_result: object = None
    title: str | None = None
    description: str | None = None

    def state(self, value):
        state = plain_copy(value)
        if not isinstance(state, dict):
            raise ValueError("An activity model must be an object")
        if self.validate_state is not None:
            valid = _call(self.validate_state, plain_copy(state))
            if valid is not None and valid is not True:
                raise ValueError("Invalid state for activity " + self.name)
        return state

    def result(self, value):
        if not isinstance(value, ActivityResult):
            raise ValueError("An activity result must be ActivityResult")
        result = ActivityResult.from_snapshot(value.snapshot())
        if self.validate_result is not None:
            valid = _call(self.validate_result, ActivityResult.from_snapshot(result.snapshot()))
            if valid is not None and valid is not True:
                raise ValueError("Invalid result for activity " + self.name)
        return result

    def initial(self, value=None):
        return self.state(_call(self.create_state) if value is None else value)

    def restore(self, data):
        if (not isinstance(data, dict) or set(data) != {"version", "state", "result"}
                or type(data["version"]) is not int or not 1 <= data["version"] <= self.version):
            raise ValueError("Invalid or future activity save for " + self.name)
        state, version = plain_copy(data["state"]), data["version"]
        if not isinstance(state, dict):
            raise ValueError("An activity model must be an object")
        while version < self.version:
            migrate = self.migrations.get(version)
            if migrate is None:
                raise ValueError(f"No {self.name} migration from version {version}")
            state = plain_copy(_call(migrate, state))
            if not isinstance(state, dict):
                raise ValueError("An activity migration must return an object")
            version += 1
        state = self.state(state)
        result = (None if data["result"] is None else
                  self.result(ActivityResult.from_snapshot(data["result"])).snapshot())
        return {"version": version, "state": state, "result": result}

    def transition(self, state, name, payload):
        value = _call(self.reduce, plain_copy(state), name, plain_copy(payload))
        if isinstance(value, ActivityTransition):
            state = self.state(value.state)
            result = None if value.result is None else self.result(value.result).snapshot()
        else:
            state, result = self.state(value), None
        return {"version": self.version, "state": state, "result": result}


class ActivityRenderError(RuntimeError):
    pass


class ActivityRegistry:
    """Factories are registered once per interpreter, outside native save stores."""

    def __init__(self):
        self._lock = threading.RLock()
        self._definitions = {}

    @contextmanager
    def transaction(self):
        """Make one startup hook's registrations atomic; no gameplay state moves."""
        with self._lock:
            before = dict(self._definitions)
            try:
                yield self
            except BaseException:
                self._definitions = before
                raise

    def register(self, name, *, version, create_state, renderer, reduce,
                 validate_state=None, migrations=None, validate_result=None,
                 title=None, description=None):
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,95}", name)
                or name in BUILTIN_KINDS):
            raise ValueError("Activity names must be unique project IDs, outside built-in kinds")
        if type(version) is not int or version < 1:
            raise ValueError("Activity version must be a positive integer")
        for label, callback in (("create_state", create_state), ("renderer", renderer),
                                ("reduce", reduce), ("validate_state", validate_state),
                                ("validate_result", validate_result)):
            if ((callback is None and label in ("create_state", "renderer", "reduce"))
                    or (callback is not None and (not callable(callback)
                                                or inspect.iscoroutinefunction(callback)))):
                raise TypeError(label + " must be a synchronous callable")
        migrations = dict(migrations or {})
        if any(type(old) is not int or not 1 <= old < version or not callable(callback)
               or inspect.iscoroutinefunction(callback) for old, callback in migrations.items()):
            raise ValueError("Migrations must map older positive versions to synchronous functions")
        if any(value is not None and (not isinstance(value, str) or not value)
               for value in (title, description)):
            raise ValueError("Activity titles and descriptions must be nonempty strings")
        definition = ActivityDefinition(name, version, create_state, renderer, reduce,
                                        validate_state, MappingProxyType(migrations), validate_result,
                                        title, description)
        with self._lock:
            if name in self._definitions:
                raise ValueError("Activity already registered: " + name)
            self._definitions[name] = definition
        return definition

    def contains(self, name):
        with self._lock:
            return name in self._definitions

    def get(self, name):
        with self._lock:
            definition = self._definitions.get(name)
        if definition is None:
            raise ValueError("Unregistered story activity: " + str(name))
        return definition

    def render(self, context):
        try:
            controls = _call(self.get(context.kind).renderer, context)
            if not isinstance(controls, list):
                raise TypeError("Activity renderer must return a list of Flet controls")
            return controls
        except Exception as error:
            raise ActivityRenderError("Could not render activity " + context.kind) from error


activities = ActivityRegistry()
register_activity = activities.register


@dataclass(frozen=True)
class ActivityContext:
    """A renderer's detached model and revision-guarded command surface."""

    story: object
    revision: int
    navigate: object
    large_text: bool = False
    state: dict = field(init=False)
    kind: str = field(init=False)
    result: ActivityResult | None = field(init=False)
    error: str = field(init=False)

    def __post_init__(self):
        current = self.story.current()
        if current is None or current.revision != self.revision or current.activity is None:
            raise ValueError("ActivityContext requires the current activity revision")
        object.__setattr__(self, "kind", current.kind)
        object.__setattr__(self, "state", plain_copy(current.activity["state"]))
        object.__setattr__(self, "error", current.feedback)
        object.__setattr__(self, "result", None if current.activity["result"] is None else
                           ActivityResult.from_snapshot(current.activity["result"]))

    def command(self, name, payload=None):
        return self.story.activity_command(self.revision, name, payload)

    def complete(self, value=None):
        return self.story.complete_activity(self.revision, value)

    def cancel(self, value=None):
        return self.story.cancel_activity(self.revision, value)
