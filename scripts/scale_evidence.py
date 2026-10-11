"""Validate raw device evidence and recompute 2D metrics; summaries are not inputs."""

import csv
import hashlib
import json
import math
import re
import statistics
import struct
import subprocess
import zlib
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "examples/2d/workloads.json"

FRAME_SQL = '''
SELECT f.id AS frame_id, f.ts + f.dur AS present_ns, f.dur AS duration_ns,
       f.layer_name, f.surface_frame_token, f.display_frame_token, f.jank_type,
       p.pid, p.name AS process_name
FROM actual_frame_timeline_slice AS f
JOIN process_track AS t ON f.track_id = t.id
JOIN process AS p ON t.upid = p.upid
WHERE p.pid = {pid} AND f.layer_name IS NOT NULL
  AND f.ts + f.dur >= (SELECT end_ts - 30000000000 FROM trace_bounds)
  AND f.ts + f.dur <= (SELECT end_ts FROM trace_bounds)
ORDER BY f.ts + f.dur;
'''


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def percentile(values, fraction):
    return sorted(values)[math.ceil(len(values) * fraction) - 1] if values else None


def framebuffer_pixel(data, x, y):
    if len(data) < 12:
        raise ValueError("Incomplete Android framebuffer")
    width, height, pixel_format = struct.unpack_from("<III", data)
    header = len(data) - width * height * 4
    if not width or not height or pixel_format != 1 or header not in (12, 16):
        raise ValueError("Expected a complete Android RGBA_8888 framebuffer")
    if not 0 <= x < width or not 0 <= y < height:
        raise ValueError("Input probe pixel is outside the framebuffer")
    offset = header + (y * width + x) * 4
    return tuple(data[offset:offset + 3])


def decode_frame(data):
    decoder = zlib.decompressobj()
    value = decoder.decompress(data, 64 * 1024 * 1024)
    if not decoder.eof or decoder.unused_data:
        raise ValueError("Incomplete or oversized compressed framebuffer")
    framebuffer_pixel(value, 0, 0)
    return value


def control_bounds(xml, label):
    """Find an enabled clickable node that contains the requested exact label."""
    root = ElementTree.fromstring(xml)
    for node in root.iter("node"):
        if node.get("enabled") != "true" or node.get("clickable") != "true":
            continue
        if not any(label in (child.get("text"), child.get("content-desc")) for child in node.iter("node")):
            continue
        match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
        if match:
            bounds = list(map(int, match.groups()))
            if bounds[2] > bounds[0] and bounds[3] > bounds[1]:
                return bounds
    return None


def control_has_pixels(frame, bounds):
    left, top, right, bottom = bounds
    samples = {framebuffer_pixel(frame, min(right - 1, left + (right - left) * x // 8),
                                 min(bottom - 1, top + (bottom - top) * y // 8))
               for x in range(1, 8) for y in range(1, 8)}
    return len(samples) > 1


def parse_display(wm, display):
    sizes = re.findall(r"(?:Physical|Override) size: (\d+)x(\d+)", wm)
    size = list(map(int, sizes[-1])) if sizes else None
    # Read the active internal display mode, not a maximum advertised rate.
    refresh = None
    for block in re.findall(r"DisplayDeviceInfo\{[^\n]+", display):
        if "INTERNAL" not in block:
            continue
        mode = re.search(r"\bmodeId\s*(?:=\s*)?(\d+)", block)
        if mode:
            active = re.search(r"\{id\s*=\s*" + mode[1] +
                               r",\s*width\s*=\s*\d+,\s*height\s*=\s*\d+,\s*(?:fps|refreshRate)\s*=\s*([\d.]+)", block)
            if active:
                refresh = float(active[1])
    return size, refresh


def frame_metrics(rows):
    if not rows:
        return None
    seen = set()
    for row in rows:
        token = (row["layer_name"], row["surface_frame_token"])
        if token in seen:
            raise ValueError("Repeated SurfaceFrame token in raw samples")
        seen.add(token)
        if row["present_ns"] <= 0 or row["duration_ns"] <= 0:
            raise ValueError("Incomplete or invalid SurfaceFrame timing")
        if not row["jank_type"].strip():
            raise ValueError("FrameTimeline jank classification is missing")
    if len({row["layer_name"] for row in rows}) != 1:
        raise ValueError("More than one surface selected; timings cannot be combined")
    ordered = sorted(rows, key=lambda row: row["present_ns"])
    intervals = [(after["present_ns"] - before["present_ns"]) / 1000000
                 for before, after in zip(ordered, ordered[1:])]
    if any(value <= 0 for value in intervals):
        raise ValueError("Presented frames must have distinct increasing timestamps")
    durations = [row["duration_ns"] / 1000000 for row in rows]
    jank = sum(row["jank_type"].strip().casefold() not in ("none", "no jank") for row in rows)
    return {"frames": len(rows), "seconds": (ordered[-1]["present_ns"] - ordered[0]["present_ns"]) / 1e9,
            "interval_p50_ms": percentile(intervals, .5), "interval_p95_ms": percentile(intervals, .95),
            "interval_p99_ms": percentile(intervals, .99), "pipeline_p95_ms": percentile(durations, .95),
            "jank_fraction": jank / len(rows), "layer": ordered[0]["layer_name"]}


class Bundle:
    """A bounded collection directory with content hashes for every raw artifact."""

    def __init__(self, folder):
        self.root = Path(folder).resolve()
        self.manifest = json.loads((self.root / "manifest.json").read_text())
        if self.manifest.get("schema_version") != 1:
            raise ValueError("Unsupported 2D evidence schema")
        if self.manifest.get("spec_sha256") != sha256(SPEC):
            raise ValueError("Evidence was collected against a different workload specification")
        files = self.manifest.get("files")
        if not isinstance(files, dict) or not files:
            raise ValueError("Evidence has no hashed raw artifacts")
        for name, digest in files.items():
            path = self.path(name)
            if not re.fullmatch(r"[0-9a-f]{64}", digest) or sha256(path) != digest:
                raise ValueError("Changed or missing raw evidence: " + name)

    def path(self, name):
        if (not isinstance(name, str) or name not in self.manifest.get("files", {})
                or Path(name).is_absolute() or ".." in Path(name).parts):
            raise ValueError("Evidence references an unhashed or invalid path")
        path = self.root / name
        if path.is_symlink() or not path.resolve().is_relative_to(self.root) or not path.is_file():
            raise ValueError("Evidence path leaves the collection directory")
        return path

    def text(self, name):
        return self.path(name).read_text()

    def json(self, name):
        return json.loads(self.text(name))

    def frame(self, name):
        return decode_frame(self.path(name).read_bytes())

    def eligibility(self, spec):
        props = dict(re.findall(r"\[([^\]]+)\]: \[([^\]]*)\]", self.text("properties.txt")))
        inventory = self.json("apk-capabilities.json")
        reasons = []
        if props.get("ro.kernel.qemu") == "1" or not props.get("ro.product.model"):
            reasons.append("physical phone model not established")
        if "emulator" in props.get("ro.product.model", "").casefold() or "sdk_gphone" in props.get("ro.product.name", ""):
            reasons.append("emulator cannot establish phone performance")
        if props.get("ro.build.version.sdk") != str(spec["target"]["android_api"]):
            reasons.append("requires Android API 35")
        if props.get("ro.product.cpu.abi") != spec["target"]["abi"]:
            reasons.append("requires physical ARM64 ABI")
        size, refresh = parse_display(self.text("wm-size.txt"), self.text("display.txt"))
        if size != spec["target"]["display_pixels"]:
            reasons.append("display size differs from the selected profile")
        if refresh is None or abs(refresh - spec["target"]["refresh_hz"]) > .1:
            reasons.append("active 60 Hz internal display mode not established")
        if inventory.get("build_type") != "release" or "DEBUGGABLE" in self.text("package.txt"):
            reasons.append("requires the release APK")
        if not re.fullmatch(r"[0-9a-f]{40}", inventory.get("source_sha", "")):
            reasons.append("APK source revision is missing")
        if self.manifest.get("source_sha") != inventory.get("source_sha"):
            reasons.append("recorded source revision differs from the APK")
        project = inventory.get("project", {})
        if (project.get("application_id") != self.manifest.get("package")
                or not re.fullmatch(r"[0-9a-f]{64}", project.get("input_sha256", ""))):
            reasons.append("project identity and input fingerprint are missing from the APK")
        if not re.fullmatch(r"[0-9a-f]{64}", self.manifest.get("apk_sha256", "")):
            reasons.append("installed APK fingerprint is missing")
        if self.text("installed-apk-sha256.txt").strip() != self.manifest.get("apk_sha256"):
            reasons.append("installed APK differs from the measured artifact")
        if not self.text("serial.txt").strip() or self.text("serial.txt").strip() == "unknown":
            reasons.append("device serial is missing")
        if not props.get("ro.build.fingerprint"):
            reasons.append("Android OS build fingerprint is missing")
        if str(self.manifest.get("pid")) != self.text("process.txt").strip():
            reasons.append("process identity differs from the recorded application PID")
        thermal = [int(value) for name in self.manifest["files"] if name.startswith("thermal-")
                   for value in re.findall(r"Thermal Status:\s*(\d+)", self.text(name))]
        if len(thermal) < 3:
            reasons.append("requires at least three thermal observations")
        elif max(thermal) > spec["limits"]["thermal_status_max"]:
            reasons.append("phone exceeded the allowed thermal status")
        return reasons

    def identity(self):
        props = dict(re.findall(r"\[([^\]]+)\]: \[([^\]]*)\]", self.text("properties.txt")))
        inventory = self.json("apk-capabilities.json")
        device = {key: props.get(key) for key in ("ro.product.model", "ro.build.fingerprint", "ro.product.cpu.abi")}
        device["serial"] = self.text("serial.txt").strip()
        return {"source_sha": inventory.get("source_sha"),
                "project_input_sha256": inventory.get("project", {}).get("input_sha256"),
                "device_sha256": hashlib.sha256(json.dumps(device, sort_keys=True).encode()).hexdigest()}

    def size_evidence(self, spec):
        workload, tier = self.manifest.get("workload"), self.manifest.get("tier")
        sizes = spec["workloads"].get(workload, {}).get(tier)
        if not isinstance(sizes, dict):
            return False
        markers = []
        for payload in re.findall(r"SDK_2D_READY (\{[^\n]+\})", self.text("logcat.txt")):
            try:
                markers.append(json.loads(payload))
            except json.JSONDecodeError:
                pass
        # Distinguish all modeled rows from the bounded rendered table page.
        for event in markers[-1:]:
            if event.get("workload") != workload or event.get("tier") != tier:
                return False
            if workload == "table":
                event = {**event, "table_page_rows": event.get("page_rows")}
            return all(event.get(key) == value for key, value in sizes.items())
        return False


def extract_frames(bundle, trace_processor):
    """Re-extract the binary trace with fixed SQL; a submitted summary cannot pass."""
    pid = bundle.manifest.get("pid")
    if type(pid) is not int or pid <= 0:
        raise ValueError("Frame trace has no valid measured process ID")
    sql = FRAME_SQL.format(pid=pid)
    if bundle.text("frames.sql") != sql:
        raise ValueError("Frame extraction SQL differs from the fixed measurement query")
    query = bundle.path("frames.sql")
    raw = subprocess.check_output([str(trace_processor), str(bundle.path("trace.perfetto-trace")),
                                   "--query-file", str(query)], timeout=60, text=True)
    all_rows = list(csv.DictReader(raw.splitlines()))
    selected = [row for row in all_rows if re.fullmatch(bundle.manifest["layer_regex"], row["layer_name"])]
    submitted = list(csv.DictReader(bundle.text("frames.csv").splitlines()))
    if not selected or selected != submitted:
        raise ValueError("Selected frame samples do not match the binary Perfetto trace")


def evaluate_frames(bundle, spec, trace_processor=None):
    reasons = bundle.eligibility(spec)
    if not bundle.size_evidence(spec):
        reasons.append("actual workload size/mount evidence is missing")
    if bundle.manifest.get("engine") not in spec["workloads"].get(bundle.manifest.get("workload"), {}).get("engines", []):
        reasons.append("renderer is not part of the selected workload")
    for required in ("trace.perfetto-trace", "frames.sql", "frames.csv", "layers.csv"):
        bundle.path(required)
    if not bundle.path("trace.perfetto-trace").stat().st_size:
        reasons.append("binary Perfetto trace is empty")
    if trace_processor is None:
        reasons.append("requires trace_processor_shell to verify samples against the binary trace")
    else:
        extract_frames(bundle, trace_processor)
    rows = []
    for row in csv.DictReader(bundle.text("frames.csv").splitlines()):
        rows.append({**row, "present_ns": int(row["present_ns"]), "duration_ns": int(row["duration_ns"])})
    metrics = frame_metrics(rows)
    if metrics is None:
        reasons.append("no presented frames were collected")
    elif (metrics["frames"] < spec["measurement"]["min_frames_per_window"]
          or metrics["seconds"] < spec["measurement"]["window_seconds"] * .95):
        reasons.append("too few frames or too short a presented-frame window")
    if reasons:
        return {"status": "unverified", "reasons": reasons, "metrics": metrics}
    limits = spec["limits"]
    failed = [key for key, observed, limit in (
        ("frame interval p95", metrics["interval_p95_ms"], limits["frame_interval_p95_ms"]),
        ("frame interval p99", metrics["interval_p99_ms"], limits["frame_interval_p99_ms"]),
        ("jank fraction", metrics["jank_fraction"], limits["jank_fraction"])) if observed > limit]
    return {"status": "fail" if failed else "pass", "reasons": failed, "metrics": metrics}


def evaluate_input(bundle, spec):
    reasons = bundle.eligibility(spec)
    if not bundle.size_evidence(spec):
        reasons.append("actual workload size/mount evidence is missing")
    samples = bundle.json("input-samples.json")
    values = []
    previous_capture = 0
    for sample in samples:
        before = framebuffer_pixel(bundle.frame(sample["before"]), *sample["pixel"])
        after = framebuffer_pixel(bundle.frame(sample["after"]), *sample["pixel"])
        expected = {(8, 204, 240), (240, 70, 32)}
        if before not in expected or after not in expected or before == after:
            reasons.append("captured input receipt did not visibly change")
            continue
        elapsed = (sample["captured_host_ns"] - sample["dispatch_host_ns"]) / 1000000
        if (not math.isfinite(elapsed) or elapsed <= 0
                or sample["dispatch_host_ns"] < previous_capture):
            raise ValueError("Invalid input sample clock interval")
        previous_capture = sample["captured_host_ns"]
        values.append(elapsed)
    if len(values) < spec["measurement"]["input_samples"]:
        reasons.append("too few visible input samples")
    def receipts(name):
        entries = set()
        for payload in re.findall(r"SDK_2D_INPUT (\{[^\n]+\})", bundle.text(name)):
            value = json.loads(payload)
            if value.get("workload") == bundle.manifest.get("workload") and value.get("command") == "probe":
                entries.add(value.get("receipt"))
        return entries
    if len(receipts("logcat.txt") - receipts("baseline-logcat.txt")) < spec["measurement"]["input_samples"]:
        reasons.append("actual input callbacks for this workload are missing")
    p95 = percentile(values, .95)
    return {"status": "unverified" if reasons else (
        "fail" if p95 > spec["limits"]["input_visible_upper_bound_p95_ms"] else "pass"),
        "reasons": reasons, "metrics": {"samples": len(values), "visible_upper_bound_p95_ms": p95}}


def evaluate_startup(bundle, spec):
    reasons = bundle.eligibility(spec)
    values = []
    samples = bundle.json("startup-samples.json")
    previous_capture = 0
    for sample in samples:
        stopped = bundle.text(sample["stopped_processes"])
        if any(line.split()[-1:] == [bundle.manifest["package"]] for line in stopped.splitlines()):
            reasons.append("application process remained alive before cold launch")
            continue
        bounds = control_bounds(bundle.text(sample["xml"]), sample["control"])
        if bounds is None or not control_has_pixels(bundle.frame(sample["frame"]), bounds):
            reasons.append("cold launch has no captured visible enabled control")
            continue
        launch = bundle.text(sample["launch_log"])
        if "Status: ok" not in launch or not re.search(r"^Activity:", launch, re.M):
            reasons.append("Android cold launch did not complete successfully")
            continue
        elapsed = (sample["captured_host_ns"] - sample["dispatch_host_ns"]) / 1000000
        if (not math.isfinite(elapsed) or elapsed <= 0 or type(sample.get("pid")) is not int
                or sample["pid"] <= 0 or sample["dispatch_host_ns"] < previous_capture):
            raise ValueError("Invalid cold-launch timing or process ID")
        previous_capture = sample["captured_host_ns"]
        values.append(elapsed)
    if len(values) < spec["measurement"]["cold_starts"]:
        reasons.append("requires five force-stopped cold launches")
    p95 = percentile(values, .95)
    return {"status": "unverified" if reasons else (
        "fail" if p95 > spec["limits"]["cold_start_visible_upper_bound_p95_ms"] else "pass"),
        "reasons": reasons, "metrics": {"cold_starts": len(values), "visible_upper_bound_p95_ms": p95}}


def evaluate_memory(bundle, spec):
    reasons = bundle.eligibility(spec)
    phases = bundle.json("memory-phases.json")
    names = [name for phase in ("baseline", "during", "final") for name in phases.get(phase, [])]
    if len(set(names)) != len(names):
        raise ValueError("Memory phases require independent process snapshots")

    def samples(names):
        values = []
        if len(set(names)) != len(names):
            raise ValueError("Repeated memory snapshot cannot count as another sample")
        for name in names:
            text = bundle.text(name)
            header = re.search(r"MEMINFO in pid (\d+) \[([^\]]+)\]", text)
            if not header or header[1] != str(bundle.manifest["pid"]) or header[2] != bundle.manifest["package"]:
                raise ValueError("Memory snapshot belongs to a different or unknown process")
            match = re.search(r"TOTAL PSS:\s*(\d+)", text)
            if not match:
                match = re.search(r"^\s*TOTAL\s+(\d+)\s", bundle.text(name), re.M)
            if not match:
                raise ValueError("Process PSS is missing from meminfo: " + name)
            values.append(int(match[1]) / 1024)
        return values

    baseline, final = samples(phases["baseline"]), samples(phases["final"])
    peak = samples(phases.get("during", [])) + baseline + final
    expression = r"SDK_RUNNER_APP_STORY action=completed phase=completed revision=(\d+) pid=(\d+)"
    completed = len(set(re.findall(expression, bundle.text("logcat.txt")))
                    - set(re.findall(expression, bundle.text("baseline-logcat.txt"))))
    if completed < spec["measurement"]["navigation_cycles"]:
        reasons.append("ten actual story completion cycles are missing")
    if min(len(baseline), len(final)) < spec["measurement"]["memory_samples_per_phase"]:
        reasons.append("requires three process-memory samples before and after navigation")
    if len(phases.get("during", [])) < spec["measurement"]["navigation_cycles"]:
        reasons.append("requires a whole-process memory sample after each navigation cycle")
    growth = statistics.median(final) - statistics.median(baseline) if baseline and final else None
    metrics = {"peak_pss_mib": max(peak) if peak else None, "growth_mib": growth,
               "completion_cycles": completed, "baseline_pss_mib": baseline, "final_pss_mib": final}
    failed = []
    if peak and max(peak) > spec["limits"]["total_pss_mib"]:
        failed.append("process PSS exceeds the limit")
    if growth is not None and growth > spec["limits"]["pss_growth_mib"]:
        failed.append("retained PSS growth exceeds the limit")
    return {"status": "unverified" if reasons else ("fail" if failed else "pass"),
            "reasons": reasons + failed, "metrics": metrics}


def evaluate_bundle(folder, spec=None, trace_processor=None):
    spec = json.loads(SPEC.read_text()) if spec is None else spec
    bundle = Bundle(folder)
    kind = bundle.manifest.get("kind")
    if kind == "frames":
        result = evaluate_frames(bundle, spec, trace_processor=trace_processor)
    elif kind == "input":
        result = evaluate_input(bundle, spec)
    elif kind == "memory":
        result = evaluate_memory(bundle, spec)
    elif kind == "startup":
        result = evaluate_startup(bundle, spec)
    else:
        raise ValueError("Unsupported device measurement kind")
    return {"folder": str(bundle.root), "kind": kind, "workload": bundle.manifest.get("workload"),
            "tier": bundle.manifest.get("tier"), "engine": bundle.manifest.get("engine"),
            "repetition": bundle.manifest.get("repetition"), "apk_sha256": bundle.manifest.get("apk_sha256"),
            **bundle.identity(),
            **result}
