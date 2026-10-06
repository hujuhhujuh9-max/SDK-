"""Native tactics displayable adapted from 2d-test at 7dc24c50.

Authoritative state lives in renfletpy.story, so native and background saves
capture moves. This displayable only holds the last painted copy for picking.
"""

import json
import os
from typing import Optional

from renpy.exports import Displayable, Render, redraw, restart_interaction
import renpy.pygame as pygame

import sdk_bridge
from renfletpy import story
from tactics import (
    BG, EDGE, ENEMY, ENEMY_BODY, FACE_LEFT, FACE_RIGHT, GOAL, HEAD, MOVE,
    PLAYER_BODY, PLAYER_BODY_2, SELECTED, SHADOW, SHELF_LEFT,
    SHELF_RIGHT, SHELF_UNDERSIDE, TOP_GROUND, TOP_HIGH, TOP_SHELF,
    Cell, Unit, build_draw_items, diamond, point_in_diamond, poly, project,
)


class _ScaledCanvas:
    """Fit the imported board coordinates inside the native scene viewport."""

    def __init__(self, canvas, scale, offset):
        self.canvas, self.scale, self.offset = canvas, scale, offset

    def point(self, point):
        x, y = point
        return (round(self.offset[0] + x * self.scale), round(self.offset[1] + y * self.scale))

    def bounds(self, rect):
        x, y, width, height = rect
        return (*self.point((x, y)), max(1, round(width * self.scale)), max(1, round(height * self.scale)))

    def polygon(self, color, points):
        self.canvas.polygon(color, [self.point(p) for p in points])

    def lines(self, color, closed, points, width=1):
        self.canvas.lines(color, closed, [self.point(p) for p in points], width=max(1, round(width * self.scale)))

    def rect(self, color, rect):
        self.canvas.rect(color, self.bounds(rect))

    def ellipse(self, color, rect, width=0):
        self.canvas.ellipse(color, self.bounds(rect), width=max(1, round(width * self.scale)) if width else 0)

    def circle(self, color, center, radius):
        self.canvas.circle(color, self.point(center), max(1, round(radius * self.scale)))


class TacticsDisplayable(Displayable):
    """Pure-2D isometric renderer with face-level painter sorting."""

    def __init__(self, **properties) -> None:
        super().__init__(**properties)
        self.state = None
        self.revision = None
        self.scale = 1.0
        self.offset = (0.0, 0.0)
        self._painted = None

    def reset(self) -> None:
        if self.interactive() and story.reset_tactics(self.revision):
            redraw(self, 0)
            restart_interaction()

    def skip(self):
        if self.interactive():
            story.choose(self.revision, "skipped")

    def render(self, width: int, height: int, st: float, at: float):
        render = Render(width, height)
        canvas = render.canvas()
        canvas.rect(BG, (0, 0, width, height))
        current = story.current()
        self.state = story.tactics_state()
        if current is None or self.state is None:
            return render
        self.revision = current.revision
        painted = (current.revision, current.positions, current.selected_unit)
        if painted != self._painted:
            self._painted = painted
            print("SDK_RUNNER_TACTICS " + json.dumps({
                "revision": current.revision, "positions": current.positions,
                "selected_unit": current.selected_unit, "pid": os.getpid()}), flush=True)
        self.scale = min(width / 836.0, height / 560.0)
        self.offset = (width / 2.0 - 640 * self.scale, height / 2.0 - 350 * self.scale)
        canvas = _ScaledCanvas(canvas, self.scale, self.offset)

        for item in build_draw_items(self.state):
            if item.kind == "underside":
                pts = poly(item.payload)
                canvas.polygon(SHELF_UNDERSIDE, pts)
                canvas.lines(EDGE, True, pts, width=2)

            elif item.kind == "top":
                surface, reachable, selected = item.payload
                color = (
                    MOVE if reachable
                    else SELECTED if selected
                    else TOP_GROUND if surface.kind == "ground"
                    else TOP_SHELF if surface.kind == "shelf"
                    else TOP_HIGH
                )
                pts = poly(diamond(surface.cell))
                canvas.polygon(color, pts)
                canvas.lines(EDGE, True, pts, width=2)
                if surface.cell == GOAL:
                    canvas.lines(SELECTED, True, pts, width=4)

            elif item.kind == "face_left":
                points, shelf = item.payload
                pts = poly(points)
                canvas.polygon(
                    SHELF_LEFT if shelf else FACE_LEFT, pts
                )
                canvas.lines(EDGE, True, pts, width=2)

            elif item.kind == "face_right":
                points, shelf = item.payload
                pts = poly(points)
                canvas.polygon(
                    SHELF_RIGHT if shelf else FACE_RIGHT, pts
                )
                canvas.lines(EDGE, True, pts, width=2)

            elif item.kind == "unit":
                self.draw_unit(canvas, item.payload)

        return render

    def draw_unit(self, canvas, unit: Unit) -> None:
        cx, cy = project(unit.cell)
        cx, cy = int(cx), int(cy)

        canvas.ellipse(SHADOW, (cx - 25, cy - 6, 50, 15))

        body = (
            ENEMY_BODY if unit.team == ENEMY
            else PLAYER_BODY_2 if unit.variant
            else PLAYER_BODY
        )
        canvas.rect(body, (cx - 18, cy - 47, 36, 48))
        canvas.circle(HEAD, (cx, cy - 62), 18)

        if self.state.selected_uid == unit.uid:
            canvas.ellipse(
                SELECTED,
                (cx - 29, cy - 11, 58, 22),
                width=3,
            )

    def pick_unit(self, x: float, y: float) -> Optional[Unit]:
        candidates = []
        for unit in self.state.units:
            cx, cy = project(unit.cell)
            if cx - 27 <= x <= cx + 27 and cy - 84 <= y <= cy + 10:
                candidates.append(unit)

        if not candidates:
            return None

        candidates.sort(
            key=lambda u: (
                u.cell.x + u.cell.y,
                u.cell.x,
                u.cell.z,
            ),
            reverse=True,
        )
        return candidates[0]

    def pick_surface(self, x: float, y: float) -> Optional[Cell]:
        candidates = [
            s.cell for s in self.state.board.iter_surfaces()
            if point_in_diamond(x, y, s.cell)
        ]

        if not candidates:
            return None

        candidates.sort(
            key=lambda c: (c.x + c.y, c.x, c.z),
            reverse=True,
        )
        return candidates[0]

    def event(self, ev, x: float, y: float, st: float):
        if not self.interactive() or self.state is None:
            return None
        if ev.type == pygame.MOUSEBUTTONUP and getattr(ev, "button", 1) == 1:
            x, y = self.board_position(x, y)
            unit = self.pick_unit(x, y)
            if unit is not None:
                changed = story.select_tactics_unit(self.revision, unit.uid)
            else:
                target = self.pick_surface(x, y)
                changed = target is not None and story.move_tactics_unit(self.revision, target)
            if changed:
                redraw(self, 0)
                restart_interaction()
        return None

    def interactive(self):
        return (sdk_bridge.presentation() == "scene" and not sdk_bridge.save_status()["busy"]
                and not sdk_bridge.reading_status()["busy"])

    def screen_position(self, x, y):
        return (self.offset[0] + x * self.scale, self.offset[1] + y * self.scale)

    def board_position(self, x, y):
        return ((x - self.offset[0]) / self.scale, (y - self.offset[1]) / self.scale)
