"""Native tactics displayable adapted from 2d-test at 7dc24c50.

Authoritative state lives in renfletpy.story, so native and background saves
capture moves. This displayable only holds the last painted copy for picking.
"""

import json
import os
from dataclasses import asdict
from math import atan2, cos, degrees, hypot, radians, sin
from typing import Optional

from renpy.exports import Displayable, Render, redraw, restart_interaction, render as render_displayable
import renpy.pygame as pygame
from renpy.text.text import Text

import sdk_bridge
from renfletpy import story
from tactics import (
    BG, EDGE, ENEMY, ENEMY_BODY, FLOOR, GOAL, HEAD, MOVE,
    PLAYER_BODY, PLAYER_BODY_2, SELECTED, SHADOW, WALL,
    LEVEL_H, Cell, TacticsView, Unit, build_draw_items, camera_cell, diamond,
    point_in_diamond, poly, project,
)


class _BlendedCanvas:
    """Composite each translucent face onto the faces already painted below it."""

    def __init__(self, width, height):
        self.surface = pygame.Surface((width, height), pygame.SRCALPHA, 32)
        self.surface.fill(BG)
        self.layer = pygame.Surface((width, height), pygame.SRCALPHA, 32)

    def draw(self, function, color, bounds, *args, **kwargs):
        if len(color) < 4 or color[3] == 255:
            function(self.surface, color, *args, **kwargs)
        elif color[3]:
            bounds = pygame.Rect(bounds).clip(self.surface.get_rect())
            if not bounds.width or not bounds.height:
                return
            self.layer.set_clip(bounds)
            self.layer.fill((0, 0, 0, 0), bounds)
            function(self.layer, color, *args, **kwargs)
            self.surface.blit(self.layer, bounds.topleft, bounds)

    @staticmethod
    def bounds(points, margin=0):
        xs, ys = zip(*points)
        left, top = min(xs) - margin, min(ys) - margin
        return (left, top, max(xs) - left + margin + 1, max(ys) - top + margin + 1)

    def polygon(self, color, points):
        self.draw(pygame.draw.polygon, color, self.bounds(points), points)

    def lines(self, color, closed, points, width=1):
        self.draw(pygame.draw.lines, color, self.bounds(points, width), closed, points, width)

    def rect(self, color, rect):
        self.draw(pygame.draw.rect, color, rect, rect)

    def ellipse(self, color, rect, width=0):
        # Ren'Py's pygame ellipse takes (center_x, center_y, radius_x,
        # radius_y), unlike the bounding boxes used by the imported renderer.
        x, y, w, h = rect
        rx, ry = max(1, w // 2), max(1, h // 2)
        cx, cy = round(x + w / 2), round(y + h / 2)
        bounds = (cx - rx - width, cy - ry - width,
                  2 * (rx + width) + 2, 2 * (ry + width) + 2)
        self.draw(pygame.draw.ellipse, color, bounds, (cx, cy, rx, ry), width)

    def circle(self, color, center, radius):
        x, y = center
        self.draw(pygame.draw.circle, color, (x - radius, y - radius, 2 * radius + 1, 2 * radius + 1),
                  center, radius)


def interactive():
    current = story.current()
    return (current is not None and current.kind == "tactics" and current.selected is None
            and not story.restarting() and sdk_bridge.presentation() == "scene"
            and not sdk_bridge.save_status()["busy"] and not sdk_bridge.reading_status()["busy"])


class OpacityDial(Displayable):
    """A touch dial backed by the same saved value as the opacity slider."""

    def __init__(self, board):
        super().__init__()
        self.board = board
        self.revision = None
        self.dragging = False

    def render(self, width, height, st, at):
        current = story.current()
        if current is not None and current.revision != self.revision:
            self.revision, self.dragging = current.revision, False
        value = story.tactics_view() or TacticsView()
        rv = Render(80, 80)
        canvas = rv.canvas()
        canvas.circle((27, 40, 56, 255), (40, 40), 36)
        points = [(40 + 32 * cos(radians(135 + n * 5)), 40 + 32 * sin(radians(135 + n * 5)))
                  for n in range(55)]
        canvas.lines((62, 79, 95, 255), False, poly(points), width=5)
        active = points[:max(2, round(value.opacity * 54) + 1)]
        canvas.lines((185, 215, 222, 255), False, poly(active), width=5)
        angle = radians(135 + value.opacity * 270)
        canvas.lines((244, 240, 232, 255), False,
                     [(40, 40), (round(40 + 24 * cos(angle)), round(40 + 24 * sin(angle)))], width=4)
        canvas.circle((244, 240, 232, 255), (40, 40), 4)
        return rv

    def event(self, ev, x, y, st):
        current = story.current()
        if not interactive() or current.revision != self.revision:
            self.dragging = False
            return None
        down = ev.type == pygame.MOUSEBUTTONDOWN and getattr(ev, "button", 1) == 1
        up = ev.type == pygame.MOUSEBUTTONUP and getattr(ev, "button", 1) == 1
        if down and 0 <= x <= 80 and 0 <= y <= 80:
            self.dragging = True
        if self.dragging and (down or up or ev.type == pygame.MOUSEMOTION):
            angle = (degrees(atan2(y - 40, x - 40)) - 135) % 360
            value = angle / 270 if angle <= 270 else (1.0 if angle < 315 else 0.0)
            self.board.change_view(opacity=round(value, 2))
        if up:
            self.dragging = False
        return None


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
    """Flat floor and wall planes in a single isometric painter queue."""

    def __init__(self, **properties) -> None:
        super().__init__(**properties)
        self.state = None
        self.revision = None
        self.scale = 1.0
        self.offset = (0.0, 0.0)
        self.viewport = (0, 0)
        self._painted = None
        self.camera = TacticsView()
        self.opacity_dial = OpacityDial(self)
        self._drag = None
        self._dragging = False

    @property
    def opacity(self):
        return (story.tactics_view() or TacticsView()).opacity

    @opacity.setter
    def opacity(self, value):
        self.change_view(opacity=max(0.0, min(1.0, float(value))))

    def change_view(self, **changes):
        if self.interactive() and story.set_tactics_view(self.revision, **changes):
            redraw(self, 0)
            redraw(self.opacity_dial, 0)
            restart_interaction()

    def rotate(self, direction):
        current = story.tactics_view()
        if current is not None:
            self.change_view(rotation=(current.rotation + direction) % 4)

    def zoom_by(self, amount):
        current = story.tactics_view()
        if current is not None:
            self.change_view(zoom=round(max(0.65, min(1.8, current.zoom + amount)), 2))

    def center(self):
        self.change_view(zoom=1.0, pan_x=0.0, pan_y=0.0)

    def view_label(self):
        current = story.tactics_view() or TacticsView()
        return "%s view · %s%% zoom" % (("North", "East", "South", "West")[current.rotation],
                                        round(current.zoom * 100))

    def reset(self) -> None:
        if self.interactive() and story.reset_tactics(self.revision):
            redraw(self, 0)
            restart_interaction()

    def skip(self):
        if self.interactive():
            story.choose(self.revision, "skipped")

    def render(self, width: int, height: int, st: float, at: float):
        self.viewport = (width, height)
        render = Render(width, height)
        raster = _BlendedCanvas(width, height)
        current = story.current()
        self.state = story.tactics_state()
        if current is None or self.state is None:
            render.blit(raster.surface, (0, 0))
            return render
        if current.revision != self.revision:
            self._drag, self._dragging = None, False
        self.revision = current.revision
        self.camera = current.view
        self.scale = min(width / 836.0, height / 560.0) * self.camera.zoom
        self.offset = (width / 2.0 - 640 * self.scale + self.camera.pan_x * self.scale,
                       height / 2.0 - 350 * self.scale + self.camera.pan_y * self.scale)
        floor_ticks = [self.screen_position(*project(Cell(2.5, 2.5, floor)))[1] for floor in range(3)]
        painted = (current.revision, current.positions, current.selected_unit, self.camera, width, height)
        if painted != self._painted:
            self._painted = painted
            print("SDK_RUNNER_TACTICS " + json.dumps({
                "revision": current.revision, "positions": current.positions,
                "selected_unit": current.selected_unit, "view": asdict(self.camera),
                "floor_height": LEVEL_H, "floor_ticks": floor_ticks, "viewport": [width, height],
                "plane_colors": {"floor": FLOOR[:3], "wall": WALL[:3]},
                "scale": self.scale, "offset": self.offset, "pid": os.getpid()}), flush=True)
        canvas = _ScaledCanvas(raster, self.scale, self.offset)
        edge = ((*EDGE[:3], 255) if self.camera.opacity >= 0.75
                else (106, 128, 144, 120))

        def terrain(color):
            return (*color[:3], round(255 * self.camera.opacity))

        for item in build_draw_items(self.state, self.camera.rotation):
            if item.kind == "floor":
                surface, reachable, selected = item.payload
                pts = poly(diamond(surface.cell, self.camera.rotation))
                canvas.polygon(terrain(FLOOR), pts)
                canvas.lines(edge, True, pts, width=2)
                if reachable:
                    canvas.lines((*MOVE[:3], 220), True, pts, width=2)
                if selected or surface.cell == GOAL:
                    canvas.lines(SELECTED, True, pts, width=4)

            elif item.kind == "wall":
                pts = poly(item.payload)
                canvas.polygon(terrain(WALL), pts)
                canvas.lines(edge, True, pts, width=2)

            elif item.kind == "unit":
                self.draw_unit(canvas, item.payload)

        # A fixed ruler makes the equal vertical floor steps visible in every
        # orientation. Its ticks follow zoom/pan, independently of tile opacity.
        ys = floor_ticks
        raster.lines((185, 215, 222, 180), False, [(20, round(ys[0])), (20, round(ys[-1]))], width=2)
        for floor, y in enumerate(ys):
            raster.lines((185, 215, 222, 230), False, [(14, round(y)), (26, round(y))], width=2)
        render.blit(raster.surface, (0, 0))
        for floor, y in enumerate(ys):
            if 12 <= y <= height - 12:
                label = render_displayable(Text(str(floor), size=20, color="#b9d7de"), 32, 32, st, at)
                render.blit(label, (30, round(y - 12)))
        return render

    def draw_unit(self, canvas, unit: Unit) -> None:
        cx, cy = project(unit.cell, self.camera.rotation)
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
            cx, cy = project(unit.cell, self.camera.rotation)
            if cx - 27 <= x <= cx + 27 and cy - 84 <= y <= cy + 10:
                candidates.append(unit)

        if not candidates:
            return None

        candidates.sort(
            key=lambda u: (
                camera_cell(u.cell, self.camera.rotation).x + camera_cell(u.cell, self.camera.rotation).y,
                camera_cell(u.cell, self.camera.rotation).x,
                u.cell.z,
            ),
            reverse=True,
        )
        return candidates[0]

    def pick_surface(self, x: float, y: float) -> Optional[Cell]:
        candidates = [
            s.cell for s in self.state.board.iter_surfaces()
            if point_in_diamond(x, y, s.cell, self.camera.rotation)
        ]

        if not candidates:
            return None

        candidates.sort(
            key=lambda c: (camera_cell(c, self.camera.rotation).x + camera_cell(c, self.camera.rotation).y,
                           camera_cell(c, self.camera.rotation).x, c.z),
            reverse=True,
        )
        return candidates[0]

    def event(self, ev, x: float, y: float, st: float):
        if not self.interactive() or self.state is None:
            self._drag, self._dragging = None, False
            return None
        if ev.type == pygame.MOUSEBUTTONDOWN:
            if not (0 <= x < self.viewport[0] and 0 <= y < self.viewport[1]):
                return None
            if getattr(ev, "button", 1) == 1:
                self._drag = (x, y, self.camera.pan_x, self.camera.pan_y, self.revision)
                self._dragging = False
            elif getattr(ev, "button", 1) in (4, 5):
                self.zoom_by(0.1 if ev.button == 4 else -0.1)
            return None
        if ev.type == pygame.MOUSEMOTION and self._drag is not None:
            sx, sy, pan_x, pan_y, revision = self._drag
            if revision != self.revision:
                self._drag = None
                return None
            if hypot(x - sx, y - sy) >= 10:
                self._dragging = True
            if self._dragging:
                self.change_view(pan_x=max(-360.0, min(360.0, pan_x + (x - sx) / self.scale)),
                                 pan_y=max(-280.0, min(280.0, pan_y + (y - sy) / self.scale)))
            return None
        if ev.type == pygame.MOUSEBUTTONUP and getattr(ev, "button", 1) == 1:
            dragged = self._dragging
            self._drag, self._dragging = None, False
            if dragged or not (0 <= x < self.viewport[0] and 0 <= y < self.viewport[1]):
                return None
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
        current = story.current()
        return interactive() and current.revision == self.revision

    def screen_position(self, x, y):
        return (self.offset[0] + x * self.scale, self.offset[1] + y * self.scale)

    def board_position(self, x, y):
        return ((x - self.offset[0]) / self.scale, (y - self.offset[1]) / self.scale)
