"""Isometric terrain and movement adapted from the owner’s 2d-test repository.

Source: 7dc24c50ef8900ede31dd4bcdc01422b55d5addb/game/tactics.py.
The model and draw queue use no renderer APIs; Ren’Py owns drawing and input.
"""

from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from math import isfinite


BOARD_W = 6
BOARD_H = 6
BOARD_Z = 3

TILE_W = 132
TILE_H = 48
LEVEL_H = 160

ORIGIN_X = 640
ORIGIN_Y = 215

PLAYER = "player"
ENEMY = "enemy"

BG = (17, 19, 24, 255)
TERRAIN = (91, 126, 68, 255)
WALL = (124, 83, 67, 255)
GRID = (94, 112, 135, 150)
CAMERA_MODES = ("isometric", "top_down", "side")
EDGE = (21, 24, 29, 255)
MOVE = (69, 151, 191, 255)
SELECTED = (214, 181, 69, 255)
PLAYER_BODY = (76, 136, 211, 255)
PLAYER_BODY_2 = (74, 170, 157, 255)
ENEMY_BODY = (184, 76, 71, 255)
HEAD = (226, 229, 235, 255)
SHADOW = (20, 21, 25, 210)


@dataclass(frozen=True, order=True)
class Cell:
    x: int
    y: int
    z: int


GOAL = Cell(3, 3, 2)


@dataclass(frozen=True)
class TacticsView:
    """Saved camera and material settings, separate from movement coordinates."""

    opacity: float = 1.0
    rotation: int = 0
    zoom: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0
    mode: str = "isometric"
    level: int | None = None

    def __post_init__(self):
        if type(self.rotation) is not int or not 0 <= self.rotation < 4:
            raise ValueError("Invalid camera rotation")
        if self.mode not in CAMERA_MODES:
            raise ValueError("Invalid camera mode")
        if self.level is not None and (type(self.level) is not int or not 0 <= self.level < BOARD_Z):
            raise ValueError("Invalid visible level")
        if self.mode == "top_down" and self.level is None:
            raise ValueError("Top-down view requires a level")
        for name, lower, upper in (("opacity", 0, 1), ("zoom", 0.65, 1.8),
                                   ("pan_x", -360, 360), ("pan_y", -280, 280)):
            value = getattr(self, name)
            if (type(value) not in (int, float) or not isfinite(value)
                    or not lower <= value <= upper):
                raise ValueError("Invalid tactics " + name)

    @classmethod
    def from_snapshot(cls, data):
        if data is None:
            return cls()  # Saves from before camera controls.
        if isinstance(data, cls):
            data = vars(data)
        if not isinstance(data, dict):
            raise ValueError("Invalid tactics view")
        try:
            return cls(**data)
        except TypeError as error:
            raise ValueError("Invalid tactics view") from error


def camera_cell(cell: Cell, rotation: int = 0) -> Cell:
    """Quarter-turn the board around its center without changing world state."""
    x, y = cell.x, cell.y
    for _ in range(rotation % 4):
        x, y = BOARD_W - 1 - y, x
    return Cell(x, y, cell.z)


@dataclass(frozen=True)
class Surface:
    cell: Cell
    kind: str  # ground, solid, shelf


@dataclass
class Unit:
    uid: str
    name: str
    team: str
    cell: Cell
    move: int = 4
    jump: int = 1
    variant: int = 0


@dataclass
class MovementField:
    cost: dict[Cell, int]
    came_from: dict[Cell, Cell | None]

    def path_to(self, target: Cell) -> list[Cell]:
        if target not in self.came_from:
            return []
        out = []
        current = target
        while current is not None:
            out.append(current)
            current = self.came_from[current]
        out.reverse()
        return out


class Board:
    """Walkable surfaces at exact x/y/z locations."""

    def __init__(self) -> None:
        self.surfaces: dict[Cell, Surface] = {}
        self._build_demo()

    def add(self, x: int, y: int, z: int, kind: str) -> None:
        c = Cell(x, y, z)
        self.surfaces[c] = Surface(c, kind)

    def _build_demo(self) -> None:
        # Ground.
        for y in range(BOARD_H):
            for x in range(BOARD_W):
                self.add(x, y, 0, "ground")

        # Solid raised terrain. A solid column replaces the ground surface
        # underneath it; unlike a shelf, there is no walkable tunnel inside.
        for y in range(1, 5):
            for x in range(2, 5):
                self.surfaces.pop(Cell(x, y, 0), None)
                self.add(x, y, 1, "solid")

        # Flat shelf/bridge above usable ground.
        self.add(1, 4, 1, "shelf")
        self.add(1, 3, 1, "shelf")

        # A true three-surface column: ground + shelf + upper shelf.
        self.add(1, 3, 2, "shelf")

        # Upper balcony above the raised platform. The z=1 floor remains usable.
        for y in range(2, 4):
            for x in range(3, 5):
                self.add(x, y, 2, "shelf")

    def exists(self, c: Cell) -> bool:
        return c in self.surfaces

    def iter_surfaces(self) -> Iterator[Surface]:
        yield from self.surfaces.values()

    def surfaces_at(self, x: int, y: int) -> list[Surface]:
        return sorted(
            (s for s in self.surfaces.values()
             if s.cell.x == x and s.cell.y == y),
            key=lambda s: s.cell.z,
        )

    def movement_neighbors(self, c: Cell, jump: int) -> Iterator[Cell]:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = c.x + dx, c.y + dy
            if not (0 <= nx < BOARD_W and 0 <= ny < BOARD_H):
                continue
            for s in self.surfaces_at(nx, ny):
                if abs(s.cell.z - c.z) <= jump:
                    yield s.cell


class TacticsState:
    def __init__(self) -> None:
        self.board = Board()
        self.units: list[Unit] = []
        self.selected_uid: str | None = None
        self.reset()

    def reset(self) -> None:
        self.units = [
            Unit("knight", "Knight", PLAYER, Cell(0, 5, 0), 5, 1, 0),
            Unit("scout", "Scout", PLAYER, Cell(1, 4, 0), 4, 1, 1),
            # Deliberately under the z=2 balcony.
            Unit("under", "Under", PLAYER, Cell(3, 2, 1), 3, 1, 1),
            Unit("guard", "Guard", ENEMY, Cell(4, 3, 2), 3, 1, 0),
        ]
        self.selected_uid = "knight"

    def positions(self):
        return tuple((u.uid, u.cell.x, u.cell.y, u.cell.z) for u in self.units)

    @classmethod
    def from_positions(cls, positions, selected_uid):
        """Reconstruct a private model from immutable, validated save data."""
        state = cls()
        if not isinstance(positions, (tuple, list)) or len(positions) != len(state.units):
            raise ValueError("Invalid tactics units")
        occupied = set()
        for unit, position in zip(state.units, positions):
            if (not isinstance(position, (tuple, list)) or len(position) != 4
                    or position[0] != unit.uid
                    or any(type(value) is not int for value in position[1:])):
                raise ValueError("Invalid tactics position")
            cell = Cell(*position[1:])
            if not state.board.exists(cell) or cell in occupied:
                raise ValueError("Invalid or occupied tactics surface")
            occupied.add(cell)
            unit.cell = cell
        if selected_uid not in {u.uid for u in state.units if u.team == PLAYER}:
            raise ValueError("Invalid selected tactics unit")
        state.selected_uid = selected_uid
        return state

    @property
    def goal_reached(self):
        return any(u.uid == "scout" and u.cell == GOAL for u in self.units)

    @property
    def selected(self) -> Unit | None:
        for unit in self.units:
            if unit.uid == self.selected_uid:
                return unit
        return None

    def unit_at(self, c: Cell) -> Unit | None:
        for unit in self.units:
            if unit.cell == c:
                return unit
        return None

    def occupied(self, except_uid: str | None = None) -> set[Cell]:
        return {u.cell for u in self.units if u.uid != except_uid}

    def movement_field(self, unit: Unit) -> MovementField:
        return compute_movement_field(
            self.board,
            unit.cell,
            unit.move,
            unit.jump,
            self.occupied(unit.uid),
        )

    def select(self, unit: Unit | None) -> None:
        self.selected_uid = unit.uid if unit and unit.team == PLAYER else None

    def move_selected(self, destination: Cell) -> bool:
        unit = self.selected
        if unit is None or self.unit_at(destination) is not None:
            return False
        field = self.movement_field(unit)
        if destination not in field.cost or destination == unit.cell:
            return False
        unit.cell = destination
        return True


def compute_movement_field(
    board: Board,
    start: Cell,
    move_budget: int,
    jump: int,
    blocked: set[Cell],
) -> MovementField:
    cost = {start: 0}
    came_from = {start: None}
    queue = deque([start])

    while queue:
        current = queue.popleft()
        next_cost = cost[current] + 1
        if next_cost > move_budget:
            continue

        for nxt in board.movement_neighbors(current, jump):
            if nxt in blocked:
                continue
            if nxt not in cost or next_cost < cost[nxt]:
                cost[nxt] = next_cost
                came_from[nxt] = current
                queue.append(nxt)

    return MovementField(cost, came_from)


def project(c: Cell, rotation: int = 0, mode: str = "isometric") -> tuple[float, float]:
    c = camera_cell(c, rotation)
    if mode == "top_down":
        return (ORIGIN_X + (c.x - (BOARD_W - 1) / 2) * TILE_W,
                ORIGIN_Y + (c.y - (BOARD_H - 1) / 2) * TILE_W)
    if mode == "side":
        return (ORIGIN_X + (c.x - (BOARD_W - 1) / 2) * TILE_W,
                ORIGIN_Y - c.z * LEVEL_H)
    return (
        ORIGIN_X + (c.x - c.y) * (TILE_W / 2.0),
        ORIGIN_Y + (c.x + c.y) * (TILE_H / 2.0) - c.z * LEVEL_H,
    )


def diamond(c: Cell, rotation: int = 0, mode: str = "isometric") -> tuple[tuple[float, float], ...]:
    cx, cy = project(c, rotation, mode)
    hw, hh = TILE_W / 2.0, TILE_H / 2.0
    if mode == "top_down":
        return ((cx - hw, cy - hw), (cx + hw, cy - hw),
                (cx + hw, cy + hw), (cx - hw, cy + hw))
    if mode == "side":
        return ((cx - hw, cy), (cx + hw, cy))
    return (
        (cx, cy - hh),
        (cx + hw, cy),
        (cx, cy + hh),
        (cx - hw, cy),
    )


def point_in_diamond(px: float, py: float, c: Cell, rotation: int = 0,
                     mode: str = "isometric") -> bool:
    cx, cy = project(c, rotation, mode)
    if mode == "top_down":
        return abs(px - cx) <= TILE_W / 2 and abs(py - cy) <= TILE_W / 2
    if mode == "side":
        return False  # A side projection cannot identify a row for movement.
    return (
        abs(px - cx) / (TILE_W / 2.0)
        + abs(py - cy) / (TILE_H / 2.0)
        <= 1.0
    )


def camera_bounds(mode: str = "isometric") -> tuple[float, float, float, float]:
    """Fit complete grids and upright units, independently of the level filter."""
    points = [project(Cell(x, y, z), mode=mode)
              for x in (-0.5, BOARD_W - 0.5) for y in (-0.5, BOARD_H - 0.5)
              for z in (0, BOARD_Z - 1)]
    xs, ys = zip(*points)
    return (min(xs) - 44, min(ys) - (44 if mode == "top_down" else 84),
            max(xs) + 44, max(ys) + 44)


def draw_key(c: Cell, rotation: int = 0, mode: str = "isometric") -> tuple[int, int, int]:
    c = camera_cell(c, rotation)
    return (c.x + c.y if mode == "isometric" else c.y, c.x, c.z)


def column_top_z(board: Board, x: int, y: int, max_z: int) -> int:
    if not (0 <= x < BOARD_W and 0 <= y < BOARD_H):
        return 0
    values = [
        s.cell.z for s in board.surfaces_at(x, y)
        if s.cell.z <= max_z and s.kind == "solid"
    ]
    return max(values) if values else 0


@dataclass
class DrawItem:
    key: tuple[int, int, int, int]
    kind: str
    payload: object


def poly(points: Iterable[tuple[float, float]]) -> list[tuple[int, int]]:
    return [(int(round(x)), int(round(y))) for x, y in points]


def build_draw_items(state: TacticsState, rotation: int = 0, mode: str = "isometric",
                     level: int | None = None) -> list[DrawItem]:
    """
    Build a single painter queue.

    Grid floors never produce filled faces. Only solid terrain has a top and
    walls. A top-down slice shows terrain footprints below a solid top; side
    views collapse hidden rows to their visible terrain silhouette.
    """
    items: list[DrawItem] = []
    if mode == "top_down" and level is None:
        raise ValueError("Top-down view requires a level")

    selected = state.selected
    reachable: set[Cell] = set()
    if selected is not None and mode != "side":
        reachable = set(state.movement_field(selected).cost)
        reachable.discard(selected.cell)

    solids = [s for s in state.board.iter_surfaces() if s.kind == "solid"]
    if mode == "side":
        columns = {}
        for surface in solids:
            c = camera_cell(surface.cell, rotation)
            current = columns.get(c.x)
            if current is None or (c.z, c.y) > (current[0].z, current[0].y):
                columns[c.x] = (c, surface)
        solids = [value[1] for value in columns.values()]

    for surface in solids:
        c = surface.cell
        view_cell = camera_cell(c, rotation)
        key = draw_key(c, rotation, mode)
        if mode == "top_down" and c.z < level:
            continue
        items.append(DrawItem((*key, 1), "terrain", surface))
        if mode == "top_down":
            continue
        pts = diamond(c, rotation, mode)
        if mode == "side":
            a, b = pts
            face = (a, b, (b[0], b[1] + c.z * LEVEL_H), (a[0], a[1] + c.z * LEVEL_H))
            items.append(DrawItem((*key, 0), "wall", face))
            continue

        left, right, bottom = pts[3], pts[1], pts[2]

        for a, b, dx, dy in ((left, bottom, 0, 1), (bottom, right, 1, 0)):
            neighbor = camera_cell(Cell(view_cell.x + dx, view_cell.y + dy, c.z), -rotation)
            lower = column_top_z(state.board, neighbor.x, neighbor.y, c.z)
            for floor in range(lower, c.z):
                top_drop = (c.z - floor - 1) * LEVEL_H
                bottom_drop = (c.z - floor) * LEVEL_H
                face = ((a[0], a[1] + top_drop), (b[0], b[1] + top_drop),
                        (b[0], b[1] + bottom_drop), (a[0], a[1] + bottom_drop))
                items.append(DrawItem((*key, 0), "wall", face))

    for surface in state.board.iter_surfaces():
        c = surface.cell
        if level is not None and c.z != level:
            continue
        is_selected = selected is not None and c == selected.cell
        if c in reachable or is_selected or c == GOAL:
            items.append(DrawItem((*draw_key(c, rotation, mode), 2), "marker",
                                  (surface, c in reachable, is_selected)))

    for unit in state.units:
        c = unit.cell
        if level is not None and c.z != level:
            continue
        items.append(DrawItem(
            (*draw_key(c, rotation, mode), 3),
            "unit",
            unit,
        ))

    items.sort(key=lambda item: item.key)
    return items
