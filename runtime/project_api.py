"""One project registration hook; callable factories never enter native saves."""

import inspect
import re
import threading
from importlib import import_module

if __package__:
    from .app_navigation import ScreenRegistry
else:
    from app_navigation import ScreenRegistry


class ProjectAPI:
    def __init__(self):
        self.screens = ScreenRegistry()

    def register_screen(self, path, renderer, **options):
        return self.screens.register(path, renderer, **options)

    def register_activity(self, name, **options):
        module = import_module(".story_activities", __package__) if __package__ else import_module("story_activities")
        return module.activities.register(name, **options)


_lock = threading.RLock()
_configured = None
_target = None
_api = None
_initializing = False


def ensure_project_setup():
    """Run a synchronous registration hook once before restoring or rendering.

    A changed configuration object is supported for isolated embedded sessions;
    normal builds have one module and one hook for the process lifetime.
    """
    global _api, _configured, _target, _initializing
    config = import_module(".project_config", __package__) if __package__ else import_module("project_config")
    target = getattr(config, "PROJECT_SETUP", None)
    with _lock:
        if _configured is config and _target == target and _api is not None:
            return _api
        if _initializing:
            raise RuntimeError("Project setup cannot recursively initialize the SDK")
        api = ProjectAPI()
        if target is not None:
            if not isinstance(target, str) or not re.fullmatch(
                    r"[A-Za-z_][A-Za-z0-9_]*:[A-Za-z_][A-Za-z0-9_]*", target):
                raise ValueError("PROJECT_SETUP must name a top-level module:function")
            module, name = target.split(":")
            hook = getattr(import_module(module), name, None)
            if not callable(hook) or inspect.iscoroutinefunction(hook):
                raise TypeError("PROJECT_SETUP must name a synchronous registration hook")
            _initializing = True
            try:
                module = import_module(".story_activities", __package__) if __package__ else import_module("story_activities")
                with module.activities.transaction():
                    result = hook(api)
                    if inspect.isawaitable(result):
                        if inspect.iscoroutine(result):
                            result.close()
                        raise TypeError("PROJECT_SETUP must finish synchronously")
            finally:
                _initializing = False
        _api, _configured, _target = api, config, target
        return api
