"""Project screens and their state, independent of Flet views and story saves.

Factories receive ScreenContext and return a View or ScreenView. The SDK owns
mounting and presentation; projects own only their plain working state.
"""

import inspect
import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, unquote, urlsplit


RESERVED_ROUTES = frozenset({"/", "/app", "/menu", "/history", "/settings", "/restart",
                             "/diagnostics", "/capabilities", "/records", "/recipes", "/saves",
                             "/app/records", "/app/recipes", "/app/saves"})


def plain_state(value):
    if not isinstance(value, dict):
        raise TypeError("Screen state_factory must return a plain dictionary")
    # Round-trip validation also rejects services, controls and non-finite numbers.
    return json.loads(json.dumps(value, allow_nan=False))


def _pattern(path):
    if (not isinstance(path, str) or not path.startswith("/") or path == "/"
            or path.endswith("/") or "//" in path or any(c in path for c in "?#%\\")
            or any(part in (".", "..") for part in path.split("/"))):
        raise ValueError("Screen paths must be absolute paths without queries or trailing slashes")
    names, pieces = [], []
    for part in path.split("/"):
        if part.startswith("{") and part.endswith("}"):
            name = part[1:-1]
            if not name.isidentifier() or name in names:
                raise ValueError("Route parameters must be unique identifiers")
            names.append(name)
            pieces.append("([^/]+)")
        else:
            if "{" in part or "}" in part or not part.isprintable():
                raise ValueError("Route parameters must occupy a complete path segment")
            pieces.append(re.escape(part))
    return re.compile("^" + "/".join(pieces) + "$"), tuple(names)


@dataclass(frozen=True)
class ScreenDefinition:
    path: str
    renderer: object
    state_factory: object = dict
    state_key: str | None = None
    parent: str = "/app"
    aliases: tuple = ()


@dataclass(frozen=True)
class RouteMatch:
    definition: ScreenDefinition
    params: dict
    route: str

    @property
    def canonical_path(self):
        result = self.definition.path
        for name, value in self.params.items():
            result = result.replace("{" + name + "}", quote(value, safe=""))
        return result

    @property
    def parent(self):
        result = self.definition.parent
        for name, value in self.params.items():
            result = result.replace("{" + name + "}", quote(value, safe=""))
        return result


class ScreenRegistry:
    def __init__(self):
        self._definitions = []
        self._patterns = []

    def register(self, path, renderer, *, state_factory=dict, state_key=None,
                 parent="/app", aliases=(), _builtin=False):
        paths = (path, *tuple(aliases))
        compiled = [_pattern(candidate) for candidate in paths]
        if not _builtin and any(pattern.fullmatch(reserved)
                                for pattern, _ in compiled for reserved in RESERVED_ROUTES):
            raise ValueError("Project screen conflicts with an SDK route: " + path)
        if not callable(renderer) or not callable(state_factory) or inspect.iscoroutinefunction(state_factory):
            raise TypeError("Screens require a renderer and synchronous state_factory")
        if state_key is not None and (not isinstance(state_key, str) or not state_key):
            raise ValueError("state_key must be a nonempty string")
        if not _builtin and state_key is not None and state_key.startswith("sdk."):
            raise ValueError("The sdk. state-key namespace belongs to built-in screens")
        if not isinstance(parent, str) or not parent.startswith("/") or parent == path:
            raise ValueError("Screens need a distinct absolute Back parent")
        names = compiled[0][1]
        if any(item[1] != names for item in compiled):
            raise ValueError("Screen aliases must have the same route parameters")
        parent_names = re.findall(r"\{([^}]+)\}", parent)
        if any(name not in names for name in parent_names):
            raise ValueError("Back parent uses a parameter absent from the screen")
        signatures = [item[0].pattern for item in compiled]
        if len(set(signatures)) != len(signatures) or any(
                item[0].pattern in signatures for item in self._patterns):
            raise ValueError("Duplicate or ambiguous screen path: " + path)
        definition = ScreenDefinition(path, renderer, state_factory, state_key, parent, tuple(aliases))
        self._definitions.append(definition)
        self._patterns.extend((pattern, params, definition) for pattern, params in compiled)
        return definition

    def extend(self, registry):
        for definition in registry.definitions:
            self.register(definition.path, definition.renderer, state_factory=definition.state_factory,
                          state_key=definition.state_key, parent=definition.parent, aliases=definition.aliases)

    @property
    def definitions(self):
        return tuple(self._definitions)

    def match(self, route):
        path = urlsplit(route).path
        candidates = []
        for pattern, names, definition in self._patterns:
            match = pattern.fullmatch(path)
            if match is not None:
                values = tuple(unquote(value) for value in match.groups())
                if any(not value or "/" in value or "\\" in value or not value.isprintable()
                       or value in (".", "..") for value in values):
                    continue
                candidates.append((len(names), RouteMatch(definition, dict(zip(names, values)), route)))
        if not candidates:
            return None
        # Literal screens win over parameter screens; equal-specificity overlaps
        # fail visibly instead of depending on project registration order.
        candidates.sort(key=lambda item: item[0])
        if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
            raise ValueError("Ambiguous project route: " + path)
        return candidates[0][1]


@dataclass
class ScreenView:
    view: object
    dispose: object = None
    refresh: object = None


class NavigationState:
    """One page session's models and app return address, never in native saves."""

    def __init__(self):
        self.states = {}
        self.app_history = []
        self.return_route = "/app"

    def state_for(self, match):
        key = match.definition.state_key or match.canonical_path
        if key not in self.states:
            self.states[key] = plain_state(match.definition.state_factory())
        return self.states[key]

    def visit(self, route):
        if self.app_history and urlsplit(self.app_history[-1]).path == urlsplit(route).path:
            self.app_history[-1] = route
            return
        if not self.app_history or self.app_history[-1] != route:
            self.app_history.append(route)
            self.app_history[:] = self.app_history[-100:]

    def back_target(self, match):
        if self.app_history:
            self.app_history.pop()
        return self.app_history[-1] if self.app_history else match.parent


class ScreenContext:
    def __init__(self, page, match, state, *, navigate, back, request_story, story_status,
                 is_current, refresh, show_dialog, dismiss_dialog, large_text=False):
        self.page, self.route, self.state = page, match.route, state
        self.params = dict(match.params)
        self.query = parse_qs(urlsplit(match.route).query, keep_blank_values=True)
        self.large_text = large_text
        self._navigate, self._back = navigate, back
        self._request_story, self._story_status = request_story, story_status
        self.is_current, self._refresh = is_current, refresh
        self._show_dialog, self._dismiss_dialog = show_dialog, dismiss_dialog

    @property
    def story_status(self):
        return self._story_status()

    async def navigate(self, route):
        if self.is_current():
            await self._navigate(route)

    async def back(self, event=None):
        if self.is_current():
            await self._back(event)

    async def refresh(self):
        if self.is_current():
            await self._refresh()

    def request_story(self, action, revision=None, *, replace=False):
        if not self.is_current():
            return False
        if revision is None:
            revision = self.story_status["revision"]
        return self._request_story(action, revision, replace=replace)

    def start_story(self, *, replace=False):
        return self.request_story("start", replace=replace)

    def resume_story(self):
        return self.request_story("resume")

    def show_dialog(self, dialog):
        if self.is_current():
            self._show_dialog(dialog)

    def dismiss_dialog(self):
        if self.is_current():
            return self._dismiss_dialog()
        return False
