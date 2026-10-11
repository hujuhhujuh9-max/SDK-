"""Acceptance-only progress model written before the version 2 Rive activity."""


def reduce(state, command, payload):
    if command != "progress" or type(payload) not in (int, float) or not 0 <= payload <= 100:
        raise ValueError("Invalid version 1 progress command")
    return {"progress": float(payload)}


def setup(api):
    api.register_activity("rive_console", version=1, create_state=lambda: {"progress": 25.0},
                          renderer=lambda context: [], reduce=reduce)
