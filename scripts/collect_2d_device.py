#!/usr/bin/env python3
"""Collect raw Android 2D evidence; recording does not mark a capability proven."""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.scale_evidence import FRAME_SQL, SPEC, control_bounds, control_has_pixels, framebuffer_pixel, sha256

PERFETTO_CONFIG = '''
buffers { size_kb: 65536 fill_policy: RING_BUFFER }
duration_ms: 35000
data_sources { config { name: "android.surfaceflinger.frametimeline" } }
data_sources { config { name: "linux.process_stats" process_stats_config { proc_stats_poll_ms: 1000 } } }
data_sources { config { name: "linux.ftrace" ftrace_config {
  atrace_categories: "gfx"
  atrace_categories: "view"
  atrace_categories: "input"
  atrace_apps: "*"
  ftrace_events: "sched/sched_switch"
  ftrace_events: "power/cpu_frequency"
} } }
'''
LAYER_SQL = '''
SELECT p.pid, p.name AS process_name, f.layer_name, COUNT(*) AS frames
FROM actual_frame_timeline_slice AS f
JOIN process_track AS t ON f.track_id = t.id
JOIN process AS p ON t.upid = p.upid
WHERE f.layer_name IS NOT NULL
GROUP BY p.pid, p.name, f.layer_name;
'''


class Collector:
    def __init__(self, args):
        self.args = args
        self.output = args.output.resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        self.command_log = []
        self.prefix = ["adb"] + (["-s", args.serial] if args.serial else [])
        self.pid = None

    def adb(self, *arguments, raw=False, timeout=30):
        command = self.prefix + [str(value) for value in arguments]
        self.command_log.append(command)
        result = subprocess.run(command, capture_output=True, timeout=timeout, check=True)
        return result.stdout if raw else result.stdout.decode(errors="replace")

    def write(self, name, value):
        path = self.output / name
        if isinstance(value, bytes):
            path.write_bytes(value)
        else:
            path.write_text(value)
        return name

    def logs(self):
        return self.adb("logcat", "-d", "-v", "monotonic", "--pid", self.pid)

    def thermal(self, index):
        self.write("thermal-" + str(index) + ".txt", self.adb("shell", "dumpsys", "thermalservice"))

    def inspect(self):
        self.write("properties.txt", self.adb("shell", "getprop"))
        self.write("wm-size.txt", self.adb("shell", "wm", "size"))
        self.write("display.txt", self.adb("shell", "dumpsys", "display"))
        self.write("package.txt", self.adb("shell", "dumpsys", "package", self.args.package))
        self.write("serial.txt", self.adb("get-serialno"))
        self.pid = self.adb("shell", "pidof", self.args.package).strip()
        if not self.pid.isdigit():
            raise RuntimeError("Start the application and select the workload before collecting")
        self.write("process.txt", self.pid + "\n")
        with zipfile.ZipFile(self.args.apk) as archive:
            self.write("apk-capabilities.json", archive.read("assets/runner-capabilities.json"))
        paths = self.adb("shell", "pm", "path", self.args.package)
        self.write("installed-apk-paths.txt", paths)
        apks = [line.removeprefix("package:") for line in paths.splitlines() if line.startswith("package:")]
        if len(apks) != 1:
            raise RuntimeError("This benchmark requires the installed monolithic runner APK")
        with tempfile.TemporaryDirectory(prefix="2d-installed-apk-") as folder:
            installed = Path(folder) / "base.apk"
            self.adb("pull", apks[0], installed, timeout=60)
            fingerprint = sha256(installed)
        if fingerprint != sha256(self.args.apk):
            raise RuntimeError("Installed APK does not match --apk; install the intended artifact first")
        self.write("installed-apk-sha256.txt", fingerprint + "\n")
        self.write("baseline-logcat.txt", self.logs())
        self.thermal(0)

    def finish(self, **fields):
        self.thermal(2)
        if self.adb("shell", "pidof", self.args.package).strip() != self.pid:
            raise RuntimeError("The measured application process restarted during collection")
        self.write("process.txt", self.pid + "\n")
        self.write("logcat.txt", self.logs())
        self.write("commands.json", json.dumps(self.command_log, indent=2) + "\n")
        inventory = json.loads((self.output / "apk-capabilities.json").read_text())
        manifest = {"schema_version": 1, "spec_sha256": sha256(SPEC),
                    "source_sha": inventory["source_sha"], "apk_sha256": sha256(self.args.apk),
                    "package": self.args.package, "kind": self.args.kind,
                    "workload": getattr(self.args, "workload", "journey"),
                    "tier": getattr(self.args, "tier", "nominal"), "pid": int(self.pid),
                    **fields, "files": {path.name: sha256(path) for path in self.output.iterdir()
                                       if path.is_file() and path.name != "manifest.json"}}
        self.write("manifest.json", json.dumps(manifest, indent=2) + "\n")
        print("Raw 2D evidence: " + str(self.output))
        print("Run scripts/check_2d_evidence.py to recompute metrics; device eligibility is checked there.")

    def capture(self, name):
        data = self.adb("exec-out", "screencap", raw=True)
        captured = time.monotonic_ns()
        framebuffer_pixel(data, 0, 0)
        self.write(name, zlib.compress(data, 1))
        return data, captured


def frames(collector):
    import csv
    import io

    args = collector.args
    if not shutil.which(str(args.trace_processor)) and not Path(args.trace_processor).is_file():
        raise RuntimeError("Install Perfetto trace_processor_shell and pass --trace-processor")
    collector.write("perfetto-config.pbtxt", PERFETTO_CONFIG)
    remote = "/data/misc/perfetto-traces/sdk-2d-" + str(time.time_ns()) + ".perfetto-trace"
    command = collector.prefix + ["shell", "perfetto", "--txt", "-c", "-", "-o", remote]
    collector.command_log.append(command)
    with (collector.output / "perfetto.log").open("wb") as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=log, stderr=log)
        try:
            process.stdin.write(PERFETTO_CONFIG.encode())
            process.stdin.close()
            if args.trigger:
                collector.adb("shell", "input", "tap", *args.trigger)
            started = time.monotonic()
            middle = False
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if elapsed > 17 and not middle:
                    collector.thermal(1)
                    middle = True
                if args.swipe and elapsed > 5:
                    points = args.swipe if int(elapsed) % 2 == 0 else args.swipe[2:] + args.swipe[:2]
                    collector.adb("shell", "input", "swipe", *points, "850")
                else:
                    time.sleep(.1)
                if elapsed > 50:
                    raise RuntimeError("Perfetto recording timed out")
            if process.returncode:
                raise RuntimeError("Perfetto failed; inspect perfetto.log")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
    trace = collector.output / "trace.perfetto-trace"
    collector.adb("pull", remote, trace, timeout=60)
    collector.adb("shell", "rm", remote)
    sql = FRAME_SQL.format(pid=collector.pid)
    collector.write("frames.sql", sql)
    collector.write("layers.sql", LAYER_SQL)
    # Trace processor emits raw CSV. A specific, unique layer must be selected;
    # aggregate statistics from the debug profile channel are never substituted.
    all_frames = subprocess.check_output([str(args.trace_processor), str(trace), "--query-file",
                                          str(collector.output / "frames.sql")], timeout=60, text=True)
    collector.write("all-frames.csv", all_frames)
    collector.write("layers.csv", subprocess.check_output([
        str(args.trace_processor), str(trace), "--query-file", str(collector.output / "layers.sql")],
        timeout=60, text=True))
    reader = csv.DictReader(io.StringIO(all_frames))
    rows = [row for row in reader if re.fullmatch(args.layer_regex, row.get("layer_name", ""))]
    value = io.StringIO()
    writer = csv.DictWriter(value, fieldnames=reader.fieldnames or [])
    writer.writeheader()
    writer.writerows(rows)
    collector.write("frames.csv", value.getvalue())
    collector.finish(engine=args.engine, repetition=args.repetition, layer_regex=args.layer_regex)


def inputs(collector):
    args = collector.args
    samples = []
    before_name = "input-before.rgba.zlib"
    before, _ = collector.capture(before_name)
    for index in range(args.samples):
        previous = framebuffer_pixel(before, *args.pixel)
        if previous not in ((8, 204, 240), (240, 70, 32)):
            raise RuntimeError("--pixel must be inside the solid background of the visible Probe input control")
        dispatched = time.monotonic_ns()
        collector.adb("shell", "input", "tap", *args.tap)
        deadline = time.monotonic() + 5
        after_name = f"input-{index + 1:02d}.rgba.zlib"
        while True:
            after, captured = collector.capture(after_name)
            if framebuffer_pixel(after, *args.pixel) != previous:
                break
            if time.monotonic() > deadline:
                raise RuntimeError("No visible input receipt; input sample remains unverified")
        samples.append({"dispatch_host_ns": dispatched, "captured_host_ns": captured,
                        "before": before_name, "after": after_name, "pixel": args.pixel})
        before, before_name = after, after_name
        if index == args.samples // 2:
            collector.thermal(1)
    collector.write("input-samples.json", json.dumps(samples, indent=2) + "\n")
    collector.finish()


def actions(collector, plan):
    for step in plan:
        kind, values = step["kind"], step.get("args", [])
        counts = {"tap": (2,), "swipe": (4, 5), "keyevent": (1,)}
        if (kind in counts and len(values) in counts[kind]
                and all(type(value) is int and value >= 0 for value in values)):
            collector.adb("shell", "input", kind, *values)
        elif kind == "wait" and len(values) == 1 and type(values[0]) in (int, float) and 0 <= values[0] <= 5:
            time.sleep(values[0])
        else:
            raise ValueError("Cycle plans support only bounded tap/swipe/keyevent/wait actions")


def memory(collector):
    plan = json.loads(collector.args.cycles_plan.read_text())
    collector.write("cycles-plan.json", json.dumps(plan, indent=2) + "\n")
    phases = {"baseline": [], "during": [], "final": []}

    def sample(phase, index):
        name = f"memory-{phase}-{index}.txt"
        collector.write(name, collector.adb("shell", "dumpsys", "meminfo", collector.args.package))
        phases[phase].append(name)

    for index in range(3):
        sample("baseline", index)
    for index in range(10):
        actions(collector, plan)
        sample("during", index)
        if index == 5:
            collector.thermal(1)
    for index in range(3):
        sample("final", index)
    collector.write("memory-phases.json", json.dumps(phases, indent=2) + "\n")
    collector.finish()


def startup(collector):
    samples = []
    args = collector.args
    component = args.package + "/org.sdk.runner.RunnerActivity"
    for index in range(5):
        prefix = f"startup-{index + 1}"
        collector.adb("shell", "am", "force-stop", args.package)
        stopped = collector.write(prefix + "-stopped.txt", collector.adb("shell", "ps", "-A", "-o", "PID,NAME"))
        dispatched = time.monotonic_ns()
        launch = collector.write(prefix + "-launch.txt", collector.adb(
            "shell", "am", "start", "-W", "-n", component, timeout=30))
        collector.pid = collector.adb("shell", "pidof", args.package).strip()
        if not collector.pid.isdigit():
            raise RuntimeError("Cold launch did not create the application process")
        remote = "/sdcard/sdk-2d-startup-" + str(time.time_ns()) + ".xml"
        deadline = time.monotonic() + 30
        try:
            while True:
                collector.adb("shell", "uiautomator", "dump", remote, timeout=15)
                xml = collector.adb("shell", "cat", remote)
                bounds = control_bounds(xml, args.control)
                if bounds is not None:
                    frame_name = prefix + ".rgba.zlib"
                    frame, captured = collector.capture(frame_name)
                    if control_has_pixels(frame, bounds):
                        break
                if time.monotonic() > deadline:
                    raise RuntimeError("Cold launch never exposed its visible enabled control")
        finally:
            collector.adb("shell", "rm", "-f", remote)
        xml_name = collector.write(prefix + ".xml", xml)
        collector.write(prefix + "-logcat.txt", collector.logs())
        samples.append({"dispatch_host_ns": dispatched, "captured_host_ns": captured,
                        "pid": int(collector.pid), "control": args.control, "xml": xml_name,
                        "frame": frame_name, "stopped_processes": stopped, "launch_log": launch})
        if index == 2:
            collector.thermal(1)
    collector.write("startup-samples.json", json.dumps(samples, indent=2) + "\n")
    collector.finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--serial", help="Select one device; the coordinator owns all stateful runs")
    parser.add_argument("--output", type=Path, required=True, help="New raw-evidence directory")
    sub = parser.add_subparsers(dest="kind", required=True)
    frame = sub.add_parser("frames")
    frame.add_argument("--workload", choices=("renpy", "canvas", "table", "rive"), required=True)
    frame.add_argument("--tier", choices=("nominal", "stress"), default="nominal")
    frame.add_argument("--engine", choices=("sdl", "flutter"), required=True)
    frame.add_argument("--layer-regex", required=True, help="Full regex for exactly one inspected renderer surface")
    frame.add_argument("--trace-processor", type=Path, required=True)
    frame.add_argument("--repetition", type=int, choices=(1, 2, 3), required=True)
    frame.add_argument("--trigger", nargs=2, type=int, help="Tap Run 35s after starting recording")
    frame.add_argument("--swipe", nargs=4, type=int, help="Continuously alternate list swipes during the window")
    response = sub.add_parser("input")
    response.add_argument("--workload", choices=("canvas", "table"), required=True)
    response.add_argument("--tier", choices=("nominal", "stress"), default="nominal")
    response.add_argument("--tap", nargs=2, type=int, required=True)
    response.add_argument("--pixel", nargs=2, type=int, required=True)
    response.add_argument("--samples", type=int, default=20)
    mem = sub.add_parser("memory")
    mem.add_argument("--cycles-plan", type=Path, required=True)
    cold = sub.add_parser("startup")
    cold.add_argument("--control", default="2D Lab", help="Exact enabled home button label; use Capabilities in the combined project")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+", args.package):
        parser.error("Invalid Android application ID")
    if getattr(args, "samples", 20) < 1:
        parser.error("Input sample count must be positive")
    collector = Collector(args)
    collector.inspect()
    {"frames": frames, "input": inputs, "memory": memory, "startup": startup}[args.kind](collector)


if __name__ == "__main__":
    main()
