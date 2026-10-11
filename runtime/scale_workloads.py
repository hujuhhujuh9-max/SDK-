"""Deterministic 2D workload data. Saved/app state contains only plain values."""

import asyncio
import copy
import inspect
import math


SEED = 20261011
CANVAS_SIZES = {"nominal": (2000, 500), "stress": (10000, 2500)}
TABLE_SIZES = {"nominal": (10000, 1000, 100), "stress": (100000, 5000, 250)}
NATIVE_SIZES = {"nominal": (128, 8, 2), "stress": (512, 16, 4)}
PROBE_COLORS = ("#08ccf0", "#f04620")


def _tier(sizes, tier):
    try:
        return sizes[tier]
    except (KeyError, TypeError):
        raise ValueError("Choose workload tier 'nominal' or 'stress'") from None


def canvas_state(tier="nominal"):
    primitives, nodes = _tier(CANVAS_SIZES, tier)
    return {"tier": tier, "primitives": primitives, "nodes": nodes,
            "camera": {"x": 0.0, "y": 0.0, "scale": 0.3},
            "selected": None, "input_receipts": 0, "revision": 0}


def validate_canvas(state):
    if not isinstance(state, dict):
        raise ValueError("Canvas game state must be a dictionary")
    expected = _tier(CANVAS_SIZES, state.get("tier"))
    if (state.get("primitives"), state.get("nodes")) != expected:
        raise ValueError("Canvas workload size must match its tier")
    camera = state.get("camera")
    if not isinstance(camera, dict) or set(camera) != {"x", "y", "scale"}:
        raise ValueError("Canvas camera needs x, y and scale")
    for value in camera.values():
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("Canvas camera values must be finite numbers")
    if not 0.1 <= camera["scale"] <= 4.0 or max(abs(camera[key]) for key in ("x", "y")) > 100000:
        raise ValueError("Canvas camera is outside supported limits")
    selected = state.get("selected")
    if selected is not None and (type(selected) is not int or not 0 <= selected < expected[1]):
        raise ValueError("Canvas selected node does not exist")
    if any(type(state.get(key)) is not int or state[key] < 0
           for key in ("input_receipts", "revision")):
        raise ValueError("Canvas counters must be nonnegative integers")
    return state


def node_position(index, nodes):
    columns = math.ceil(math.sqrt(nodes))
    return (index % columns + 0.5) * 36.0, (index // columns + 0.5) * 36.0


def canvas_primitives(state):
    """Always generate all declared primitives, including those outside the view.

    A node contributes a link, an outlined rectangle and two filled circles.
    Pure descriptors are reconstructed, never stored in a game save.
    """
    validate_canvas(state)
    camera = state["camera"]
    scale = camera["scale"]
    for index in range(state["nodes"]):
        world_x, world_y = node_position(index, state["nodes"])
        x, y = world_x * scale + camera["x"], world_y * scale + camera["y"]
        selected = index == state["selected"]
        color = "#ffe08a" if selected else ("#00d4c8", "#8ebcf0", "#f09f96")[index % 3]
        yield ("line", x, y, x + 36 * scale, y + 36 * scale, "#28475c")
        yield ("rect", x - 12 * scale, y - 12 * scale, 24 * scale, 24 * scale, "#4a6378")
        yield ("circle", x, y, 8 * scale, color)
        yield ("circle", x - 2 * scale, y - 2 * scale, 2 * scale, "#ffffff")


def canvas_command(state, command, payload=None):
    """A bounded reducer shared by app gestures and the saveable story activity."""
    validate_canvas(state)
    state = copy.deepcopy(state)
    payload = {} if payload is None else payload
    if not isinstance(payload, dict):
        raise ValueError("Canvas command payload must be a dictionary")
    camera = state["camera"]
    if command == "camera":
        camera = copy.deepcopy(payload)
        state["camera"] = camera
    elif command == "pan":
        camera["x"] += payload["dx"]
        camera["y"] += payload["dy"]
    elif command == "zoom":
        factor = payload["factor"]
        if type(factor) not in (int, float) or not math.isfinite(factor) or factor <= 0:
            raise ValueError("Zoom factor must be a finite positive number")
        new_scale = min(4.0, max(0.1, camera["scale"] * factor))
        effective = new_scale / camera["scale"]
        fx, fy = payload["x"], payload["y"]
        camera["x"] = fx - (fx - camera["x"]) * effective
        camera["y"] = fy - (fy - camera["y"]) * effective
        camera["scale"] = new_scale
    elif command == "select":
        state["selected"] = payload["node"]
    elif command == "probe":
        state["input_receipts"] += 1
    elif command == "reset":
        state["camera"] = canvas_state(state["tier"])["camera"]
    else:
        raise ValueError("Unknown Canvas command: " + str(command))
    state["revision"] += 1
    return validate_canvas(state)


def pick_node(state, x, y):
    """Pick the closest node within a twelve-logical-pixel touch target."""
    camera = state["camera"]
    world_x, world_y = (x - camera["x"]) / camera["scale"], (y - camera["y"]) / camera["scale"]
    columns = math.ceil(math.sqrt(state["nodes"]))
    column, row = math.floor(world_x / 36), math.floor(world_y / 36)
    index = row * columns + column
    if column < 0 or column >= columns or row < 0 or index >= state["nodes"]:
        return None
    nx, ny = node_position(index, state["nodes"])
    return index if math.hypot(nx - world_x, ny - world_y) * camera["scale"] <= 12 else None


def table_state(tier="nominal"):
    rows, list_controls, page_rows = _tier(TABLE_SIZES, tier)
    return {"tier": tier, "rows": rows, "list_controls": list_controls,
            "page_rows": page_rows, "edits": {}, "selected": 0,
            "draft": "", "filter": "", "descending": False, "page": 0,
            "input_receipts": 0, "revision": 0, "matching": None}


def table_row(index, state):
    if type(index) is not int or not 0 <= index < state["rows"]:
        raise ValueError("Table row does not exist")
    return {"id": index, "title": state["edits"].get(str(index), f"Record {index:06d}"),
            "score": (index * 7919 + SEED) % 100000,
            "status": "held" if index % 7 == 0 else "ready"}


def edit_table(state, index, title):
    if type(title) is not str or not title.strip() or len(title) > 256:
        raise ValueError("A row title needs 1–256 characters")
    table_row(index, state)
    state["edits"][str(index)] = title.strip()
    state["revision"] += 1


def query_table(state):
    """Scan/sort the whole dataset; callers run this bounded job off the UI loop."""
    query = state["filter"].casefold().strip()
    rows = [index for index in range(state["rows"])
            if not query or query in table_row(index, state)["title"].casefold()]
    rows.sort(key=lambda index: ((index * 7919 + SEED) % 100000, index),
              reverse=state["descending"])
    return rows


class TableWorkQueue:
    """One worker at a time; newer requests supersede results from older snapshots.

    This is renderer lifetime state, not application or saved game data.
    Disposing prevents callbacks even when a thread has already begun a job.
    """

    def __init__(self, on_result, *, query=query_table, on_error=None):
        self.on_result = on_result
        self.query = query
        self.on_error = on_error
        self.generation = 0
        self.pending = None
        self.task = None
        self.closed = False

    def submit(self, state):
        if self.closed:
            return False
        self.generation += 1
        self.pending = (self.generation, copy.deepcopy(state))
        if self.task is None:
            self.task = asyncio.create_task(self._run())
        return True

    async def _run(self):
        try:
            while self.pending is not None and not self.closed:
                generation, snapshot = self.pending
                self.pending = None
                try:
                    rows = await asyncio.to_thread(self.query, snapshot)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    if generation == self.generation and not self.closed and self.on_error:
                        value = self.on_error(error)
                        if inspect.isawaitable(value):
                            await value
                    continue
                if generation == self.generation and not self.closed:
                    value = self.on_result(rows, snapshot)
                    if inspect.isawaitable(value):
                        await value
        finally:
            self.task = None

    async def close(self):
        self.closed = True
        self.generation += 1
        self.pending = None
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
