"""Failure gates use temporary synthetic inputs, never phone performance receipts."""

import csv
import io
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from scripts.collect_2d_device import actions
from scripts.check_2d_evidence import summarize
from scripts.scale_functionality import evaluate_functionality
from scripts.scale_evidence import (
    Bundle, FRAME_SQL, SPEC, control_bounds, decode_frame, evaluate_bundle,
    frame_metrics, parse_display, sha256,
)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-2d-evidence-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.spec = json.loads(SPEC.read_text())
        # Tiny unit fixtures do not satisfy the published physical profile.
        self.spec["target"]["display_pixels"] = [4, 4]
        self.spec["measurement"].update(window_seconds=.1, min_frames_per_window=5,
                                        input_samples=2, cold_starts=2,
                                        navigation_cycles=2, memory_samples_per_phase=2)
        self.manifest = {"schema_version": 1, "spec_sha256": sha256(SPEC),
                         "source_sha": "a" * 40, "apk_sha256": "b" * 64,
                         "package": "com.example.synthetic", "pid": 321,
                         "workload": "canvas", "tier": "nominal", "kind": "frames",
                         "engine": "flutter", "repetition": 1, "layer_regex": "FlutterSurface"}
        self.write("properties.txt", "\n".join([
            "[ro.product.model]: [SYNTHETIC UNIT FIXTURE]", "[ro.build.version.sdk]: [35]",
            "[ro.product.cpu.abi]: [arm64-v8a]", "[ro.kernel.qemu]: [0]",
            "[ro.build.fingerprint]: [synthetic/unit/fixture]",
        ]))
        self.write("wm-size.txt", "Physical size: 4x4\n")
        self.write("display.txt", "DisplayDeviceInfo{test, modeId 1, supportedModes ["
                   "{id=1, width=4, height=4, fps=60.0}], type INTERNAL}\n")
        self.write("serial.txt", "SYNTHETIC-ONLY\n")
        self.write("process.txt", "321\n")
        self.write("package.txt", "pkgFlags=[ HAS_CODE ]\n")
        self.write("installed-apk-sha256.txt", "b" * 64 + "\n")
        self.json("apk-capabilities.json", {"source_sha": "a" * 40, "build_type": "release",
                    "project": {"application_id": "com.example.synthetic", "input_sha256": "c" * 64}})
        for index in range(3):
            self.write(f"thermal-{index}.txt", "Thermal Status: 0\n")
        self.write("logcat.txt", "SDK_2D_READY " + json.dumps({
            "workload": "canvas", "tier": "nominal", "primitives": 2000, "selectable_nodes": 500}) + "\n")
        self.write("baseline-logcat.txt", "")

    def write(self, name, value):
        path = self.root / name
        path.write_bytes(value) if isinstance(value, bytes) else path.write_text(value)

    def json(self, name, value):
        self.write(name, json.dumps(value))

    def seal(self):
        self.manifest["files"] = {path.name: sha256(path) for path in self.root.iterdir()
                                  if path.is_file() and path.name != "manifest.json"}
        self.json("manifest.json", self.manifest)
        return Bundle(self.root)

    def frame(self, name, color, *, patterned=False):
        pixels = bytes((*color, 255)) * 16
        if patterned:
            pixels = pixels[:20] + bytes((255, 255, 255, 255)) + pixels[24:]
        self.write(name, zlib.compress(struct.pack("<III", 4, 4, 1) + pixels))

    def frames(self, *, interval=16666667, count=10, jank="None"):
        fields = ["frame_id", "present_ns", "duration_ns", "layer_name", "surface_frame_token",
                  "display_frame_token", "jank_type", "pid", "process_name"]
        rows = [{"frame_id": index, "present_ns": 1000000000 + interval * index,
                 "duration_ns": 1000000, "layer_name": "FlutterSurface", "surface_frame_token": index,
                 "display_frame_token": index, "jank_type": jank, "pid": 321,
                 "process_name": "com.example.synthetic"} for index in range(count)]
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        self.write("frames.csv", output.getvalue())
        self.write("frames.sql", FRAME_SQL.format(pid=321))
        self.write("trace.perfetto-trace", b"SYNTHETIC UNIT TRACE ONLY")
        self.write("layers.csv", "pid,layer_name,frames\n321,FlutterSurface,10\n")
        return output.getvalue()

    def inputs(self, elapsed=80000000):
        self.manifest["kind"] = "input"
        self.frame("blue.zlib", (8, 204, 240))
        self.frame("orange.zlib", (240, 70, 32))
        samples = [{"dispatch_host_ns": (index + 1) * 1000000000,
                    "captured_host_ns": (index + 1) * 1000000000 + elapsed,
                    "before": "blue.zlib" if index == 0 else "orange.zlib",
                    "after": "orange.zlib" if index == 0 else "blue.zlib", "pixel": [1, 1]}
                   for index in range(2)]
        self.json("input-samples.json", samples)
        with (self.root / "logcat.txt").open("a") as stream:
            for receipt in (1, 2):
                stream.write("SDK_2D_INPUT " + json.dumps({"workload": "canvas", "command": "probe", "receipt": receipt}) + "\n")
        return samples

    def memory(self, final=100 * 1024, *, duplicate_cycles=False):
        self.manifest.update(kind="memory", workload="journey")
        phases = {"baseline": [], "during": [], "final": []}
        for phase in phases:
            for index in range(2):
                name = f"{phase}-{index}.txt"
                self.write(name, f"** MEMINFO in pid 321 [com.example.synthetic] **\n"
                           f"TOTAL PSS: {final if phase == 'final' else 100 * 1024}\n")
                phases[phase].append(name)
        self.json("memory-phases.json", phases)
        marker = "SDK_RUNNER_APP_STORY action=completed phase=completed revision=%d pid=321\n"
        self.write("baseline-logcat.txt", marker % 1)
        self.write("logcat.txt", (marker % 1 + marker % 2) * 3 if duplicate_cycles else
                   "".join(marker % revision for revision in (1, 2, 3)))
        return phases

    def test_hashed_bundle_rejects_changed_artifact_and_path_escape(self):
        self.seal()
        self.write("thermal-0.txt", "Thermal Status: 3\n")
        with self.assertRaisesRegex(ValueError, "Changed"):
            Bundle(self.root)
        self.seal()
        self.manifest["files"]["../outside"] = "a" * 64
        self.json("manifest.json", self.manifest)
        with self.assertRaisesRegex(ValueError, "invalid path"):
            Bundle(self.root)

    def test_no_samples_and_multiple_or_repeated_surfaces_cannot_pass(self):
        self.assertIsNone(frame_metrics([]))
        rows = [{"layer_name": "SDL", "surface_frame_token": "1", "present_ns": 1,
                 "duration_ns": 1, "jank_type": "None"}]
        with self.assertRaisesRegex(ValueError, "Repeated"):
            frame_metrics(rows * 2)
        with self.assertRaisesRegex(ValueError, "More than one"):
            frame_metrics(rows + [{**rows[0], "layer_name": "Flutter", "present_ns": 2}])
        with self.assertRaisesRegex(ValueError, "classification"):
            frame_metrics([{**rows[0], "jank_type": ""}])

    def test_good_csv_requires_binary_trace_verification_and_limits_are_recomputed(self):
        raw = self.frames()
        self.seal()
        result = evaluate_bundle(self.root, self.spec)
        self.assertEqual(result["status"], "unverified")
        with patch("scripts.scale_evidence.subprocess.check_output", return_value=raw):
            result = evaluate_bundle(self.root, self.spec, trace_processor="mock-unit-only")
        self.assertEqual(result["status"], "pass")
        self.assertAlmostEqual(result["metrics"]["interval_p95_ms"], 16.666667)
        raw = self.frames(interval=25000000)
        self.seal()
        with patch("scripts.scale_evidence.subprocess.check_output", return_value=raw):
            result = evaluate_bundle(self.root, self.spec, trace_processor="mock-unit-only")
        self.assertEqual(result["status"], "fail")
        self.assertIn("frame interval p95", result["reasons"])

    def test_rehashed_csv_that_differs_from_trace_and_custom_sql_are_rejected(self):
        raw = self.frames()
        self.write("frames.csv", raw.replace("1000000,FlutterSurface", "2000000,FlutterSurface"))
        self.seal()
        with patch("scripts.scale_evidence.subprocess.check_output", return_value=raw):
            with self.assertRaisesRegex(ValueError, "do not match"):
                evaluate_bundle(self.root, self.spec, trace_processor="mock-unit-only")
        self.write("frames.sql", "SELECT 1 AS pass;")
        self.seal()
        with self.assertRaisesRegex(ValueError, "fixed measurement"):
            evaluate_bundle(self.root, self.spec, trace_processor="mock-unit-only")

    def test_emulator_debug_thermal_and_workload_size_are_independent_unverified_gates(self):
        self.inputs()
        self.write("properties.txt", (self.root / "properties.txt").read_text().replace("[0]", "[1]"))
        self.write("package.txt", "pkgFlags=[ DEBUGGABLE ]")
        self.write("thermal-1.txt", "Thermal Status: 3")
        self.write("logcat.txt", "SDK_2D_READY {}\n")
        self.seal()
        result = evaluate_bundle(self.root, self.spec)
        self.assertEqual(result["status"], "unverified")
        self.assertGreaterEqual(len(result["reasons"]), 4)

    def test_input_pixel_and_clock_gate_rejects_handler_only_or_repeated_receipt(self):
        samples = self.inputs()
        self.seal()
        self.assertEqual(evaluate_bundle(self.root, self.spec)["status"], "pass")
        samples[0]["after"] = samples[0]["before"]
        self.json("input-samples.json", samples)
        self.seal()
        self.assertEqual(evaluate_bundle(self.root, self.spec)["status"], "unverified")
        samples = self.inputs()
        samples[1].update(dispatch_host_ns=samples[0]["dispatch_host_ns"],
                          captured_host_ns=samples[0]["captured_host_ns"])
        self.json("input-samples.json", samples)
        self.seal()
        with self.assertRaisesRegex(ValueError, "clock interval"):
            evaluate_bundle(self.root, self.spec)
        self.inputs(elapsed=240000000)
        self.seal()
        self.assertEqual(evaluate_bundle(self.root, self.spec)["status"], "fail")

    def test_memory_counts_unique_new_native_completions_and_whole_process_pss(self):
        self.memory()
        self.seal()
        result = evaluate_bundle(self.root, self.spec)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["metrics"]["completion_cycles"], 2)
        self.memory(duplicate_cycles=True)
        self.seal()
        self.assertEqual(evaluate_bundle(self.root, self.spec)["status"], "unverified")
        self.memory(final=130 * 1024)
        self.seal()
        self.assertEqual(evaluate_bundle(self.root, self.spec)["status"], "fail")

    def test_memory_cannot_reuse_snapshots_or_measure_a_different_process(self):
        phases = self.memory()
        phases["final"] = list(phases["baseline"])
        self.json("memory-phases.json", phases)
        self.seal()
        with self.assertRaisesRegex(ValueError, "independent"):
            evaluate_bundle(self.root, self.spec)
        self.memory()
        self.write("final-0.txt", "** MEMINFO in pid 322 [com.example.synthetic] **\nTOTAL PSS: 1")
        self.seal()
        with self.assertRaisesRegex(ValueError, "different"):
            evaluate_bundle(self.root, self.spec)

    def test_cold_start_needs_enabled_visible_control_and_stopped_process(self):
        self.manifest.update(kind="startup", workload="journey")
        xml = '<hierarchy><node enabled="true" clickable="true" bounds="[0,0][4,4]">' \
              '<node text="2D Lab"/></node></hierarchy>'
        self.assertEqual(control_bounds(xml, "2D Lab"), [0, 0, 4, 4])
        self.write("ready.xml", xml)
        self.write("stopped.txt", "PID NAME\n1 init\n")
        self.write("launch.txt", "Status: ok\nActivity: com.example.synthetic/org.sdk.runner.RunnerActivity\n")
        self.frame("ready.zlib", (8, 204, 240), patterned=True)
        samples = [{"dispatch_host_ns": (index + 1) * 10000000000,
                    "captured_host_ns": (index + 1) * 10000000000 + 2000000000,
                    "pid": 322 + index, "control": "2D Lab", "xml": "ready.xml", "frame": "ready.zlib",
                    "stopped_processes": "stopped.txt", "launch_log": "launch.txt"} for index in range(2)]
        self.json("startup-samples.json", samples)
        self.seal()
        self.assertEqual(evaluate_bundle(self.root, self.spec)["status"], "pass")
        self.write("stopped.txt", "PID NAME\n321 com.example.synthetic\n")
        self.seal()
        self.assertEqual(evaluate_bundle(self.root, self.spec)["status"], "unverified")
        self.write("stopped.txt", "PID NAME\n1 init\n")
        self.write("ready.xml", xml.replace('enabled="true"', 'enabled="false"'))
        self.seal()
        self.assertEqual(evaluate_bundle(self.root, self.spec)["status"], "unverified")

    def test_refresh_rate_uses_active_internal_mode_not_advertised_maximum(self):
        display = (self.root / "display.txt").read_text().replace("modeId 1", "modeId 2").replace(
            "]", ", {id=2, width=4, height=4, fps=120.0}]")
        self.assertEqual(parse_display("Physical size: 4x4", display), ([4, 4], 120.0))

    def test_incomplete_frame_and_unbounded_cycle_actions_are_rejected(self):
        with self.assertRaises(ValueError):
            decode_frame(zlib.compress(b"not a frame"))
        class Collector:
            def adb(self, *args):
                raise AssertionError("invalid plans must never reach adb")
        for step in ({"kind": "tap", "args": []}, {"kind": "wait", "args": [60]},
                     {"kind": "shell", "args": ["rm"]}):
            with self.assertRaises(ValueError):
                actions(Collector(), [step])

    def test_full_gate_requires_every_window_and_separate_matching_functionality(self):
        identity = {"apk_sha256": "a" * 64, "source_sha": "b" * 40,
                    "project_input_sha256": "c" * 64, "device_sha256": "d" * 64}
        results = [{**identity, "status": "pass", "kind": "frames", "workload": workload,
                    "tier": "nominal", "engine": engine, "repetition": repetition}
                   for workload in ("renpy", "canvas", "table", "rive")
                   for engine in self.spec["workloads"][workload]["engines"] for repetition in (1, 2, 3)]
        results += [{**identity, "status": "pass", "kind": "input", "workload": workload,
                     "tier": "nominal"} for workload in ("canvas", "table")]
        results += [{**identity, "status": "pass", "kind": kind} for kind in ("memory", "startup")]
        self.assertEqual(summarize(self.spec, results)["status"], "unverified")
        functionality = {"status": "pass", "source_sha": identity["source_sha"],
                         "project_input_sha256": identity["project_input_sha256"]}
        self.assertEqual(summarize(self.spec, results, functionality)["status"], "pass")
        self.assertEqual(summarize(self.spec, results[1:], functionality)["status"], "unverified")
        results[0]["status"] = "fail"
        self.assertEqual(summarize(self.spec, results, functionality)["status"], "fail")
        results[0]["status"] = "pass"
        results[0]["device_sha256"] = "e" * 64
        self.assertEqual(summarize(self.spec, results, functionality)["status"], "unverified")

    def test_combined_success_flag_without_unchanged_raw_artifacts_is_insufficient(self):
        receipt = {"schema": 1, "success": True, "skips": 0, "artifacts": {}}
        self.json("capabilities-device.json", receipt)
        with self.assertRaisesRegex(ValueError, "hashed raw"):
            evaluate_functionality(self.root / "capabilities-device.json")
        self.write("observation.txt", "original")
        receipt["artifacts"] = {"observation.txt": {"sha256": sha256(self.root / "observation.txt"), "size": 8}}
        self.json("capabilities-device.json", receipt)
        self.write("observation.txt", "changed!")
        with self.assertRaisesRegex(ValueError, "Changed"):
            evaluate_functionality(self.root / "capabilities-device.json")


if __name__ == "__main__":
    unittest.main()
