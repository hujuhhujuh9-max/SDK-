#!/usr/bin/env python3
"""Measure host Python/Flet construction and protocol work, never phone FPS."""

import argparse
import asyncio
import contextlib
import datetime
import hashlib
import io
import json
import math
import platform
import os
import re
import resource
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def percentile(values, fraction):
    return sorted(values)[math.ceil(len(values) * fraction) - 1] if values else None


async def measure(repetitions):
    import flet as ft
    import msgpack
    from flet.controls.base_control import BaseControl
    from flet.controls.context import _context_page
    from flet.messaging.connection import Connection
    from flet.messaging.protocol import configure_encode_object_for_msgpack
    from flet.messaging.session import Session
    from flet.pubsub.pubsub_hub import PubSubHub
    from runtime.scale_ui import CanvasPanel, TablePanel
    from runtime.scale_workloads import canvas_state, table_state

    class Protocol(Connection):
        def __init__(self):
            super().__init__()
            self.loop = asyncio.get_running_loop()
            self.page_url = "flet://2d-host"
            self.pubsubhub = PubSubHub(loop=self.loop)
            self.bytes = 0
            self.packets = 0

        def encode(self, value):
            data = msgpack.packb(value, default=configure_encode_object_for_msgpack(BaseControl))
            self.bytes += len(data)
            self.packets += 1
            return data

        def send_message(self, message):
            self.encode([message.action, message.body])

    cases = []
    for workload in ("canvas", "table"):
        for tier in ("nominal", "stress"):
            samples = []
            for repetition in range(repetitions):
                connection = Protocol()
                session = Session(connection)
                page = session.page
                token = _context_page.set(page)
                connection.encode(session.get_page_patch())
                state = canvas_state(tier) if workload == "canvas" else table_state(tier)
                started = time.perf_counter_ns()
                panel = (CanvasPanel(page, state, lambda name, payload: True) if workload == "canvas"
                         else TablePanel(page, state))
                construct_ms = (time.perf_counter_ns() - started) / 1000000
                try:
                    page.views.append(ft.View(route="/2d", controls=[ft.Column(panel.controls)]))
                    connection.bytes = 0
                    started = time.perf_counter_ns()
                    page.update()
                    mount_ms = (time.perf_counter_ns() - started) / 1000000
                    mount_bytes = connection.bytes
                    event_ms, event_bytes = [], []
                    for index in range(20):
                        before = connection.bytes
                        started = time.perf_counter_ns()
                        if workload == "canvas":
                            panel.apply("pan", {"dx": 1, "dy": -1})
                        else:
                            await session.dispatch_event(panel.probe._i, "click", None)
                        event_ms.append((time.perf_counter_ns() - started) / 1000000)
                        event_bytes.append(connection.bytes - before)
                    worker_ms = None
                    if workload == "table":
                        state["filter"] = "Record 00"
                        started = time.perf_counter_ns()
                        panel.run_worker()
                        await panel.worker.task
                        worker_ms = (time.perf_counter_ns() - started) / 1000000
                    samples.append({"repetition": repetition + 1, "construct_ms": construct_ms,
                                    "mount_protocol_ms": mount_ms, "mount_bytes": mount_bytes,
                                    "input_protocol_ms": event_ms, "input_protocol_bytes": event_bytes,
                                    "filter_sort_and_patch_ms": worker_ms})
                finally:
                    await panel.dispose()
                    _context_page.reset(token)
                    session.close()
                    await asyncio.sleep(0)
            events = [value for sample in samples for value in sample["input_protocol_ms"]]
            cases.append({"workload": workload, "tier": tier, "samples": samples,
                          "construct_p50_ms": percentile([value["construct_ms"] for value in samples], .5),
                          "mount_p50_ms": percentile([value["mount_protocol_ms"] for value in samples], .5),
                          "input_protocol_p50_ms": percentile(events, .5),
                          "input_protocol_p95_ms": percentile(events, .95)})
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flet-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / ".android-build/2d-host")
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("repetitions must be positive")
    source = args.flet_root.resolve() / "sdk/python/packages/flet/src"
    if not (source / "flet/__init__.py").is_file():
        parser.error("Prepared pinned Flet source is missing")
    sys.path[:0] = [str(source), str(ROOT)]
    import flet.version
    if flet.version.flet_version != "1.0.3":
        parser.error("Benchmark requires pinned Flet 1.0.3")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        cases = asyncio.run(measure(args.repetitions))
    (output / "markers.txt").write_text(log.getvalue())
    files = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
             for name in ("runtime/scale_workloads.py", "runtime/scale_ui.py", "scripts/bench_2d_host.py")}
    result = {"schema_version": 1, "scope": "host_protocol",
              "excluded": ["Dart layout/paint", "GPU presentation", "Android input", "SDL frame timing"],
              "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "source_files": files, "python": platform.python_version(),
              "platform": platform.platform(), "flet": flet.version.flet_version,
              "collected_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "host_cpu": {"model": re.search(r"^model name\s*:\s*(.+)$", Path("/proc/cpuinfo").read_text(), re.M)[1],
                           "affinity_cpus": len(os.sched_getaffinity(0)),
                           "cgroup_cpu_max": Path("/sys/fs/cgroup/cpu.max").read_text().strip()},
              "peak_process_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              "cases": cases, "physical_phone_performance": "unverified"}
    (output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    for case in cases:
        print(f"{case['workload']} {case['tier']}: construction p50 {case['construct_p50_ms']:.2f} ms; "
              f"mount protocol p50 {case['mount_p50_ms']:.2f} ms; "
              f"input protocol p50/p95 {case['input_protocol_p50_ms']:.2f}/{case['input_protocol_p95_ms']:.2f} ms")
    print("Host receipt: " + str(output / "results.json"))


if __name__ == "__main__":
    main()
