"""Opt-in stress screens using the pinned Flet Canvas/ListView/DataTable APIs."""

import asyncio
import copy
import json
import math
import time

if __package__:
    from .scale_workloads import (
        PROBE_COLORS, TableWorkQueue, canvas_command, canvas_primitives, canvas_state,
        edit_table, pick_node, table_row, table_state,
    )
else:
    from scale_workloads import (
        PROBE_COLORS, TableWorkQueue, canvas_command, canvas_primitives, canvas_state,
        edit_table, pick_node, table_row, table_state,
    )


def marker(kind, **values):
    print("SDK_2D_" + kind + " " + json.dumps(
        {"monotonic_ns": time.monotonic_ns(), **values}, sort_keys=True), flush=True)


class CanvasPanel:
    """Rebuilt controls around a plain camera/selection model owned by the caller."""

    def __init__(self, page, state, command, *, is_current=lambda: True, allow_run=True):
        import flet as ft
        import flet.canvas as cv

        self.page, self.state, self.command = page, state, command
        self.is_current = is_current
        self.closed = False
        self.task = None
        self.previous_gesture_scale = 1.0
        self.paints = {}
        self.drawn_selection = None
        self.status = ft.Text("")
        columns = math.ceil(math.sqrt(state["nodes"]))
        rows = math.ceil(state["nodes"] / columns)
        # Flet's painter clips at the Canvas's original dimensions before its
        # layout transform. Give it the entire world, then clip the transformed
        # result in the fixed viewport; otherwise pan exposes clipped shapes.
        self.canvas = cv.Canvas(shapes=[], width=(columns + 1) * 36,
                                height=(rows + 1) * 36, left=0, top=0)
        self.viewport = ft.Stack(controls=[self.canvas], width=320, height=240,
                                 clip_behavior=ft.ClipBehavior.HARD_EDGE)

        def scale_start(event):
            self.previous_gesture_scale = 1.0

        def scale_update(event):
            if not self.active():
                return
            # ScaleUpdate.scale is cumulative from gesture start. Applying it
            # directly to the current camera would compound every update.
            factor = event.scale / self.previous_gesture_scale if self.previous_gesture_scale else 1.0
            self.previous_gesture_scale = event.scale
            camera = copy.deepcopy(self.state["camera"])
            effective = min(4.0, max(0.1, camera["scale"] * factor)) / camera["scale"]
            fx, fy = event.local_focal_point.x, event.local_focal_point.y
            camera["x"] = fx - (fx - camera["x"]) * effective + event.focal_point_delta.x
            camera["y"] = fy - (fy - camera["y"]) * effective + event.focal_point_delta.y
            camera["scale"] *= effective
            self.apply("camera", camera)

        def tap(event):
            if event.local_position is not None:
                node = pick_node(self.state, event.local_position.x, event.local_position.y)
                self.apply("select", {"node": node})

        self.gestures = ft.GestureDetector(
            content=self.viewport, on_scale_start=scale_start, on_scale_update=scale_update,
            on_tap_up=tap, drag_interval=16)
        self.probe_text = ft.Text("Probe input " + str(state["input_receipts"]), color="#000000")
        self.probe = ft.Container(content=self.probe_text, bgcolor=PROBE_COLORS[state["input_receipts"] % 2],
                                  height=48, width=180, padding=12,
                                  on_click=lambda event: self.apply("probe"))
        self.run = ft.Button("Run 35s", on_click=self.start_run)
        actions = [ft.TextButton("Reset camera", on_click=lambda event: self.apply("reset"))]
        if allow_run:
            actions.extend([self.run, ft.TextButton("Stop motion", on_click=self.stop_run)])
        self.controls = [ft.Semantics(identifier="cap-scale-camera", content=self.status),
                         ft.Container(content=ft.Semantics(identifier="cap-scale-canvas", container=True,
                                                           content=self.gestures), bgcolor="#101b2b",
                                                  clip_behavior=ft.ClipBehavior.HARD_EDGE),
                         ft.Row(actions, wrap=True), self.probe]
        self.redraw()

    def active(self):
        return not self.closed and self.is_current()

    def apply(self, name, payload=None):
        if not self.active():
            return False
        next_state = canvas_command(self.state, name, payload)
        if not self.command(name, payload):
            return False
        # App state identity is owned by the navigation session. The activity
        # renderer receives a private copy and native code owns its real model.
        self.state.clear()
        self.state.update(next_state)
        self.redraw()
        marker("INPUT", workload="canvas", command=name, revision=self.state["revision"],
               receipt=self.state["input_receipts"], camera=self.state["camera"], selected=self.state["selected"])
        self.page.update()
        return True

    def redraw(self):
        import flet as ft
        import flet.canvas as cv

        def paint(color, stroke=False):
            key = (color, stroke)
            if key not in self.paints:
                self.paints[key] = ft.Paint(color=color, stroke_width=1,
                                            style=ft.PaintingStyle.STROKE if stroke else ft.PaintingStyle.FILL)
            return self.paints[key]

        if not self.canvas.shapes:
            # The pinned Flet API already exposes a replayable Matrix4. Keep
            # the drawing geometry stable; pan/zoom changes a single transform
            # rather than deleting and resending thousands of shape controls.
            world = {**self.state, "camera": {"x": 0, "y": 0, "scale": 1}}
            for descriptor in canvas_primitives(world):
                kind, *values, color = descriptor
                cls = {"line": cv.Line, "rect": cv.Rect, "circle": cv.Circle}[kind]
                self.canvas.shapes.append(cls(*values, paint=paint(color, kind == "rect")))
        elif self.drawn_selection != self.state["selected"]:
            for index in (self.drawn_selection, self.state["selected"]):
                if index is not None:
                    color = "#ffe08a" if index == self.state["selected"] else ("#00d4c8", "#8ebcf0", "#f09f96")[index % 3]
                    self.canvas.shapes[index * 4 + 2].paint = paint(color)
        self.drawn_selection = self.state["selected"]
        camera = self.state["camera"]
        self.canvas.transform = ft.Transform(
            ft.Matrix4.identity().translate(camera["x"], camera["y"]).scale(camera["scale"]),
            alignment=ft.Alignment.TOP_LEFT, transform_hit_tests=False)
        self.status.value = (f"Canvas {self.state['tier']}: {len(self.canvas.shapes)} primitives; "
                             f"selected {self.state['selected']}; zoom {self.state['camera']['scale']:.2f}")
        self.probe_text.value = "Probe input " + str(self.state["input_receipts"])
        self.probe.bgcolor = PROBE_COLORS[self.state["input_receipts"] % 2]

    async def start_run(self, event=None):
        if not self.active() or self.task is not None:
            return
        self.task = asyncio.create_task(self._animate())

    async def _animate(self):
        self.run.disabled = True
        started = time.monotonic()
        initial = copy.deepcopy(self.state["camera"])
        frames = 0
        marker("WINDOW", workload="canvas", phase="start", tier=self.state["tier"])
        try:
            while self.active() and time.monotonic() - started < 35:
                elapsed = time.monotonic() - started
                camera = {**initial, "x": initial["x"] + math.sin(elapsed * 2) * 40,
                          "y": initial["y"] + math.cos(elapsed * 2) * 25}
                if self.apply("camera", camera):
                    frames += 1
                await asyncio.sleep(max(0, started + (math.floor(elapsed * 60) + 1) / 60 - time.monotonic()))
        finally:
            self.task = None
            self.run.disabled = False
            marker("WINDOW", workload="canvas", phase="stop", attempted_updates=frames,
                   elapsed_ms=(time.monotonic() - started) * 1000)
            if self.active():
                self.page.update()

    async def stop_run(self, event=None):
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def dispose(self):
        self.closed = True
        await self.stop_run()


def _screen_view(view, dispose=None):
    if __package__:
        from .app_navigation import ScreenView
    else:
        from app_navigation import ScreenView
    return ScreenView(view, dispose=dispose)


def canvas_screen(ctx):
    import flet as ft

    # CanvasPanel applies the reducer once after command acceptance. Application
    # changes belong to ctx.state; no native API is called by this screen.
    panel = CanvasPanel(ctx.page, ctx.state, lambda name, payload: ctx.is_current(),
                        is_current=ctx.is_current)
    marker("READY", workload="canvas", tier=ctx.state["tier"], primitives=ctx.state["primitives"],
           selectable_nodes=ctx.state["nodes"])
    return _screen_view(ft.View(route=ctx.route, padding=16, controls=[ft.Column([
        ft.Row([ft.Text("2D Canvas", size=26), ft.TextButton("Back", on_click=ctx.back)]),
        *panel.controls,
        ft.TextButton("Start story", on_click=lambda event: ctx.start_story()),
    ], expand=True, scroll=ft.ScrollMode.AUTO)]), panel.dispose)


class TablePanel:
    """Large model, lazy list, bounded table, and one coalescing file-style worker."""

    def __init__(self, page, state, *, is_current=lambda: True):
        import flet as ft

        self.page, self.state, self.is_current = page, state, is_current
        self.closed = False
        self.ids = list(range(state["rows"])) if state.get("matching") is None else list(state["matching"])
        self.status = ft.Text("")
        self.filter = ft.TextField(label="Filter all rows", value=state["filter"], on_change=self.filter_changed)
        self.draft = ft.TextField(label="Unsaved row title", value=state["draft"],
                                  max_length=256, on_change=self.draft_changed)
        self.selected = ft.Text("Selected row " + str(state["selected"]))
        self.list = ft.ListView(controls=[], item_extent=48, spacing=0, height=240,
                                build_controls_on_demand=True, cache_extent=144)
        self.table = ft.DataTable(columns=[ft.DataColumn(ft.Text(name))
                                          for name in ("ID", "Title", "Score", "Status")], rows=[])
        self.probe_text = ft.Text("Probe input " + str(state["input_receipts"]), color="#000000")
        self.probe = ft.Container(content=self.probe_text, bgcolor=PROBE_COLORS[state["input_receipts"] % 2],
                                  height=48, width=180, padding=12, on_click=self.probe_input)
        self.worker = TableWorkQueue(self.worker_result, on_error=self.worker_error)
        self.controls = [self.status, self.filter,
                         ft.Row([ft.Button("Filter / sort", on_click=self.run_worker),
                                 ft.TextButton("Reverse sort", on_click=self.reverse_sort)], wrap=True),
                         self.selected, self.draft,
                         ft.Button("Save row edit", on_click=self.save_edit), self.probe,
                         ft.Text("Lazy ListView"),
                         ft.Semantics(identifier="cap-scale-list", container=True, content=self.list),
                         ft.Row([ft.TextButton("Previous page", on_click=self.previous),
                                 ft.TextButton("Next page", on_click=self.next)], wrap=True),
                         ft.Column([ft.Row([ft.Semantics(identifier="cap-scale-table", container=True,
                                                       content=self.table)], scroll=ft.ScrollMode.AUTO)],
                                   scroll=ft.ScrollMode.AUTO, height=260)]
        self.redraw()

    def active(self):
        return not self.closed and self.is_current()

    def select(self, index):
        def selected(event):
            if not self.active():
                return
            self.state["selected"] = index
            self.state["draft"] = table_row(index, self.state)["title"]
            self.draft.value = self.state["draft"]
            self.selected.value = "Selected row " + str(index)
            self.page.update()
        return selected

    def draft_changed(self, event):
        if self.active():
            self.state["draft"] = self.draft.value or ""

    def filter_changed(self, event):
        if self.active():
            self.state["filter"] = self.filter.value or ""
            self.state["revision"] += 1

    def save_edit(self, event):
        if not self.active():
            return
        try:
            edit_table(self.state, self.state["selected"], self.draft.value or "")
        except ValueError as error:
            self.draft.error = str(error)
        else:
            self.draft.error = None
            self.state["draft"] = self.draft.value or ""
            self.redraw()
        self.page.update()

    def run_worker(self, event=None):
        if self.active():
            self.worker.submit(self.state)
            self.status.value = "Working across all " + str(self.state["rows"]) + " rows…"
            self.page.update()

    def reverse_sort(self, event):
        if self.active():
            self.state["descending"] = not self.state["descending"]
            self.state["revision"] += 1
            self.run_worker()

    def worker_result(self, rows, snapshot):
        if not self.active() or snapshot["revision"] != self.state["revision"]:
            return
        self.ids = rows
        self.state["matching"] = list(rows)
        self.state["page"] = 0
        self.redraw()
        marker("WORKER", workload="table", phase="completed", matches=len(rows),
               revision=snapshot["revision"])
        self.page.update()

    def worker_error(self, error):
        if self.active():
            self.status.value = "Worker failed: " + str(error)
            self.page.update()

    def redraw(self):
        import flet as ft

        self.list.controls = []
        for index in self.ids[:self.state["list_controls"]]:
            row = table_row(index, self.state)
            self.list.controls.append(ft.Container(
                content=ft.Text(f"{index}: {row['title']} · {row['score']}"),
                height=48, padding=8, on_click=self.select(index)))
        page_rows = self.state["page_rows"]
        last_page = max(0, (len(self.ids) - 1) // page_rows)
        self.state["page"] = min(last_page, self.state["page"])
        start = self.state["page"] * page_rows
        self.table.rows = []
        for index in self.ids[start:start + page_rows]:
            row = table_row(index, self.state)
            self.table.rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(str(row["id"]))),
                ft.DataCell(ft.Text(row["title"]), show_edit_icon=True, on_tap=self.select(index)),
                ft.DataCell(ft.Text(str(row["score"]))),
                ft.DataCell(ft.Text(row["status"])),
            ]))
        self.status.value = (f"Table {self.state['tier']}: {self.state['rows']} data rows; "
                             f"{len(self.list.controls)} list controls; page {self.state['page'] + 1}, "
                             f"{len(self.table.rows)} × 4 cells; {len(self.ids)} matches")

    def previous(self, event):
        if self.active():
            self.state["page"] = max(0, self.state["page"] - 1)
            self.redraw()
            self.page.update()

    def next(self, event):
        if self.active():
            self.state["page"] += 1
            self.redraw()
            self.page.update()

    def probe_input(self, event):
        if self.active():
            self.state["input_receipts"] += 1
            self.probe_text.value = "Probe input " + str(self.state["input_receipts"])
            self.probe.bgcolor = PROBE_COLORS[self.state["input_receipts"] % 2]
            marker("INPUT", workload="table", command="probe", receipt=self.state["input_receipts"])
            self.page.update()

    async def dispose(self):
        self.closed = True
        await self.worker.close()


def table_screen(ctx):
    import flet as ft

    panel = TablePanel(ctx.page, ctx.state, is_current=ctx.is_current)
    marker("READY", workload="table", tier=ctx.state["tier"], rows=ctx.state["rows"],
           list_controls=ctx.state["list_controls"], page_rows=ctx.state["page_rows"], columns=4)
    return _screen_view(ft.View(route=ctx.route, padding=16, controls=[ft.Column([
        ft.Row([ft.Text("2D Tables", size=26), ft.TextButton("Back", on_click=ctx.back)]),
        *panel.controls,
        ft.TextButton("Start story", on_click=lambda event: ctx.start_story()),
    ], expand=True, scroll=ft.ScrollMode.AUTO)]), panel.dispose)


def lab_screen(ctx):
    import flet as ft

    note = ft.TextField(label="Journey draft", value=ctx.state["draft"])
    status = ft.Text("Drafts, selections and camera values remain in this app session.")

    def changed(event):
        if ctx.is_current():
            ctx.state["draft"] = note.value or ""
            marker("APP_STATE", route=ctx.route, phase="changed", state=ctx.state)
    note.on_change = changed

    async def open_canvas(event):
        await ctx.navigate("/app/2d/canvas")

    async def open_table(event):
        await ctx.navigate("/app/2d/table")

    def start(event):
        accepted = ctx.start_story()
        if ctx.is_current():
            status.value = "Starting the 2D story journey…" if accepted else "Wait for story status, then try again."
            ctx.page.update()

    marker("READY", workload="journey", route=ctx.route)
    marker("APP_STATE", route=ctx.route, phase="mounted", state=ctx.state)
    return ft.View(route=ctx.route, padding=16, controls=[ft.Column([
        ft.Text("2D Lab", size=30), note,
        ft.Row([ft.Button("Canvas", on_click=open_canvas), ft.Button("Tables", on_click=open_table)], wrap=True),
        ft.Button("Start story", on_click=start), status,
        ft.TextButton("Back", on_click=ctx.back),
    ], spacing=16, expand=True, scroll=ft.ScrollMode.AUTO)])


def register_scale_screens(api):
    """Project setup calls this, without modifying any SDK route registry."""
    api.register_screen("/app/2d", lab_screen, state_factory=lambda: {"draft": ""})
    api.register_screen("/app/2d/canvas", canvas_screen, state_factory=canvas_state, parent="/app/2d")
    api.register_screen("/app/2d/table", table_screen, state_factory=table_state, parent="/app/2d")
    api.register_screen("/app/2d/canvas/stress", canvas_screen,
                        state_factory=lambda: canvas_state("stress"), parent="/app/2d")
    api.register_screen("/app/2d/table/stress", table_screen,
                        state_factory=lambda: table_state("stress"), parent="/app/2d")
