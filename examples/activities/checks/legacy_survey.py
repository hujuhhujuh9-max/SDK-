"""Acceptance-only version 1 of the same project activity."""


def create_state():
    return {"found": [], "note": ""}


def reduce(state, name, payload):
    if name == "draft" and isinstance(payload, str):
        state["note"] = payload
    elif name == "record" and payload is None:
        if "telescope" not in state["found"]:
            state["found"].append("telescope")
    else:
        raise ValueError("Invalid legacy survey command")
    return state


def register(api):
    api.register_activity("field_survey", version=1, create_state=create_state,
                          renderer=lambda context: [], reduce=reduce,
                          title="Field survey", description="Version 1 native save fixture.")
