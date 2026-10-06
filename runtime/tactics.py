"""Isometric terrain and movement adapted from the owner’s 2d-test repository.

Source: 7dc24c50ef8900ede31dd4bcdc01422b55d5addb/game/tactics.py.
The model and draw queue use no renderer APIs; Ren’Py owns drawing and input.
"""

from collections import deque
from dataclasses import dataclass
from math import isfinite
from typing import Dict, Iterable, Iterator, List, Optional, Set, Tuple


BOARD_W = 6
BOARD_H = 6
BOARD_Z = 3

TILE_W = 132
TILE_H = 66
LEVEL_H = 96

ORIGIN_X = 640
ORIGIN_Y = 215

PLAYER = "player"
ENEMY = "enemy"

BG = (17, 19, 24, 255)
FLOOR = (73, 102, 132, 255)
WALL = (124, 83, 67, 255)
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

    opacity: float = 0.6
    rotation: int = 0
    zoom: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0

    def __post_init__(self):
        if type(self.rotation) is not int or not 0 <= self.rotation < 4:
            raise ValueError("Invalid camera rotation")
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
    cost: Dict[Cell, int]
    came_from: Dict[Cell, Optional[Cell]]

    def path_to(self, target: Cell) -> List[Cell]:
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
        self.surfaces: Dict[Cell, Surface] = {}
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

    def surfaces_at(self, x: int, y: int) -> List[Surface]:
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
        self.units: List[Unit] = []
        self.selected_uid: Optional[str] = None
        self.reset()

    def reset(self) -> None:
        self.units = [
            Unit("knight", "Knight", PLAYER, Cell(0, 1, 0), 5, 1, 0),
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
    def selected(self) -> Optional[Unit]:
        for unit in self.units:
            if unit.uid == self.selected_uid:
                return unit
        return None

    def unit_at(self, c: Cell) -> Optional[Unit]:
        for unit in self.units:
            if unit.cell == c:
                return unit
        return None

    def occupied(self, except_uid: Optional[str] = None) -> Set[Cell]:
        return {u.cell for u in self.units if u.uid != except_uid}

    def movement_field(self, unit: Unit) -> MovementField:
        return compute_movement_field(
            self.board,
            unit.cell,
            unit.move,
            unit.jump,
            self.occupied(unit.uid),
        )

    def select(self, unit: Optional[Unit]) -> None:
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
    blocked: Set[Cell],
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


def project(c: Cell, rotation: int = 0) -> Tuple[float, float]:
    c = camera_cell(c, rotation)
    return (
        ORIGIN_X + (c.x - c.y) * (TILE_W / 2.0),
        ORIGIN_Y + (c.x + c.y) * (TILE_H / 2.0) - c.z * LEVEL_H,
    )


def diamond(c: Cell, rotation: int = 0) -> Tuple[Tuple[float, float], ...]:
    cx, cy = project(c, rotation)
    hw, hh = TILE_W / 2.0, TILE_H / 2.0
    return (
        (cx, cy - hh),
        (cx + hw, cy),
        (cx, cy + hh),
        (cx - hw, cy),
    )


def point_in_diamond(px: float, py: float, c: Cell, rotation: int = 0) -> bool:
    cx, cy = project(c, rotation)
    return (
        abs(px - cx) / (TILE_W / 2.0)
        + abs(py - cy) / (TILE_H / 2.0)
        <= 1.0
    )


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
    key: Tuple[int, int, int, int]
    kind: str
    payload: object


def poly(points: Iterable[Tuple[float, float]]) -> List[Tuple[int, int]]:
    return [(int(round(x)), int(round(y))) for x, y in points]


def build_draw_items(state: TacticsState, rotation: int = 0) -> List[DrawItem]:
    """
    Build a single painter queue.

    Floors are flat diamonds, with no thickness or underside. Vertical walls
    are separate panels split at the same LEVEL_H floor boundaries. Geometry
    and depth keys use camera coordinates; identities remain world cells.
    """
    items: List[DrawItem] = []

    selected = state.selected
    reachable: Set[Cell] = set()
    if selected is not None:
        reachable = set(state.movement_field(selected).cost)
        reachable.discard(selected.cell)

    for surface in state.board.iter_surfaces():
        c = surface.cell
        view_cell = camera_cell(c, rotation)
        diag, vx = view_cell.x + view_cell.y, view_cell.x

        pts = diamond(c, rotation)

        items.append(DrawItem(
            (diag, vx, c.z, 1),
            "floor",
            (surface, c in reachable,
             selected is not None and c == selected.cell),
        ))

        left, right, bottom = pts[3], pts[1], pts[2]

        for a, b, dx, dy in ((left, bottom, 0, 1), (bottom, right, 1, 0)):
            if surface.kind != "solid" or c.z == 0:
                continue
            neighbor = camera_cell(Cell(view_cell.x + dx, view_cell.y + dy, c.z), -rotation)
            lower = column_top_z(state.board, neighbor.x, neighbor.y, c.z)
            for floor in range(lower, c.z):
                top_drop = (c.z - floor - 1) * LEVEL_H
                bottom_drop = (c.z - floor) * LEVEL_H
                face = ((a[0], a[1] + top_drop), (b[0], b[1] + top_drop),
                        (b[0], b[1] + bottom_drop), (a[0], a[1] + bottom_drop))
                items.append(DrawItem((diag, vx, c.z, 0), "wall", face))

    for unit in state.units:
        c = unit.cell
        view_cell = camera_cell(c, rotation)
        items.append(DrawItem(
            (view_cell.x + view_cell.y, view_cell.x, c.z, 3),
            "unit",
            unit,
        ))

    items.sort(key=lambda item: item.key)
    return items
