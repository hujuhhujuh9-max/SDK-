"""The packaged startup contract; Ren'Py still owns the host and interpreter."""

import json

STARTUP_MODES = ("story", "app")
DEFAULT_STARTUP_MODE = "story"
STARTUP_ASSET = "assets/runner-startup.json"


def startup_config(mode=DEFAULT_STARTUP_MODE):
    if mode not in STARTUP_MODES:
        raise ValueError("Unknown runner startup mode: " + str(mode))
    return {"schema_version": 1, "mode": mode,
            "initial_route": "/records" if mode == "app" else "/"}


def parse_startup_config(data):
    config = json.loads(data)
    if (not isinstance(config, dict) or type(config.get("schema_version")) is not int
            or config != startup_config(config.get("mode"))):
        raise ValueError("Invalid runner startup configuration")
    return config
