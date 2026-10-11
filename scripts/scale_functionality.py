"""Revalidate the combined driver's raw receipt without operating a device."""

import json
import math
import re
import zlib
from pathlib import Path
from xml.etree import ElementTree

from runtime.scale_workloads import validate_canvas
from scripts.scale_evidence import SPEC, framebuffer_pixel, sha256


def verify_rive_playback(rive, saved, *, observed, ready, pixels, cleanup, pid):
    """Require actual three-controller playback and saved pause reconstruction."""
    roles = {"forest", "signal", "loop"}
    groups = (("ready", None), ("quick_load_ready", saved["quick_load"]["after"]),
              ("restored_ready", saved["after"]))
    for name, model in groups:
        group = rive.get(name)
        if not isinstance(group, dict) or set(group) != roles:
            raise ValueError("Rive playback requires all three actual controller manifests")
        if model is None:
            # Initial native inputs precede the later bookmark. Bind the loop
            # to the actual forest boolean, not the newer bookmark's value.
            forest = group["forest"].get("data", {})
            state = {"progress": forest.get("numbers", {}).get("Progress"),
                     "downloading": forest.get("booleans", {}).get("Downloading")}
        else:
            state = model["state"]
        if type(state.get("downloading")) is not bool:
            raise ValueError("Rive playback requires the saved boolean type")
        for role in sorted(roles):
            record = group[role]
            observed("SDK_CAP_RIVE_READY", record)
            if model is not None and record.get("revision") != model["revision"]:
                raise ValueError("Rive readiness belongs to a different restored activity revision")
            ready(record, state, role)
        loop = group["loop"]["data"]
        speed = loop.get("speed_multiplier")
        if (loop.get("animations") != ["bouncing"] or loop.get("artboard") != "New Artboard"
                or loop.get("active") is not state["downloading"]
                or type(speed) not in (int, float) or not math.isfinite(speed)
                or speed != (1 if state["downloading"] else 0)):
            raise ValueError("Rover did not reconstruct actual bouncing playback from the saved boolean")
    for name, active, reasons in (("pause", False, ("properties",)),
                                  ("resume", True, ("properties",)),
                                  ("background", False, ("inactive", "hidden", "paused")),
                                  ("foreground", True, ("resumed",))):
        record = rive[name]
        observed("SDK_CAP_RIVE_LIFECYCLE", record)
        if (record.get("role") != "loop" or record["data"].get("active") is not active
                or record["data"].get("reason") not in reasons):
            raise ValueError("Actual looping rover lifecycle did not pause and resume")
        if name in ("pause", "resume"):
            model = rive[name + "_model"]
            observed("SDK_CAP_ACTIVITY_STATE", model)
            if (model.get("kind") != "rive_console" or model.get("phase") != "committed"
                    or model.get("revision") != record.get("revision")
                    or model["state"].get("downloading") is not active
                    or model["state"].get("progress") != 25):
                raise ValueError("Loop pause/resume did not commit its actual game values")
    if (saved["quick_load"]["after"]["state"]["downloading"] is not False
            or saved["after"]["state"]["downloading"] is not True):
        raise ValueError("Rive must reconstruct both a frozen bookmark and newer playing game state")
    for name, progress, downloading in (("applied_inputs", 50, False), ("completed_inputs", 99, True)):
        record = rive[name]
        observed("SDK_CAP_RIVE_INPUT", record)
        if (record.get("role") != "forest" or record["data"].get("numbers", {}).get("Progress") != progress
                or record["data"].get("booleans", {}).get("Downloading") is not downloading):
            raise ValueError("Rive did not apply its actual number/boolean inputs")
    for name, moving in (("initial", True), ("paused", False), ("resumed", True),
                         ("quick_loaded_paused", False), ("restored", True)):
        value = rive["pixels"][name]
        if value.get("moving") is not moving:
            raise ValueError("Rover pixel evidence claims the wrong playback state")
        pixels(value, moving=moving)
    if (cleanup is None or cleanup != rive["cleanup"] or cleanup.get("pid") != pid
            or len(set(cleanup.get("ready_ids", []))) < 3
            or not set(cleanup["ready_ids"]) <= set(cleanup.get("disposed_ids", []))):
        raise ValueError("Combined actual three-controller cleanup differs from its raw log")


def evaluate_functionality(receipt_path):
    path = Path(receipt_path).resolve()
    receipt = json.loads(path.read_text())
    if receipt.get("schema") != 1 or receipt.get("success") is not True or receipt.get("skips") != 0:
        raise ValueError("Combined functionality must finish successfully without skips")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError("Combined receipt requires hashed raw artifacts")

    def artifact(name):
        if not isinstance(name, str) or name not in artifacts or Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("Combined receipt references an invalid or unhashed path")
        file = path.parent / name
        if file.is_symlink() or not file.resolve().is_relative_to(path.parent) or not file.is_file():
            raise ValueError("Combined artifact leaves its evidence directory")
        return file

    for name, metadata in artifacts.items():
        file = artifact(name)
        if (not re.fullmatch(r"[0-9a-f]{64}", metadata.get("sha256", ""))
                or file.stat().st_size != metadata.get("size") or sha256(file) != metadata["sha256"]):
            raise ValueError("Changed combined raw artifact: " + name)

    # Use the functionality driver's pure native-owner, archive and pixel
    # validators. Importing these helpers never starts ADB or loads a save.
    from scripts import check_project_capabilities as checks

    inspection = checks.strict_json(artifact("apk-inspection.json").read_text())
    if (inspection["sha256"] != receipt["sha256"] or receipt["installed_sha256"] != receipt["sha256"]
            or inspection["source_sha"] != receipt["source_sha"]
            or inspection["project"]["input_sha256"] != receipt["project_input_sha256"]):
        raise ValueError("Combined APK/source/project identity differs from its inspection")
    if receipt.get("scope") != "emulator_functionality" or receipt.get("phone_performance_proven") is not False:
        raise ValueError("The API 35 functionality driver cannot establish phone performance")
    if receipt.get("device", {}).get("api") != 35 or receipt["device"].get("emulator") is not True:
        raise ValueError("Combined functionality receipt has an unexpected hardware scope")

    process_files = {"initial": "canvas-source-logcat.txt", "canvas_restored": "rive-source-logcat.txt",
                     "rive_restored": "capabilities-logcat.txt"}
    pids = {name: int(receipt["pids"][name]) for name in process_files}
    if min(pids.values()) <= 0 or len(set(pids.values())) != len(pids):
        raise ValueError("Combined reopen checks require distinct application processes")
    records, logs = {}, {}
    for name, filename in process_files.items():
        pid = pids[name]
        logs[pid] = artifact(filename).read_text()
        checks.check_log_errors(logs[pid], pids.values())
        records[pid] = checks.marker_records(logs[pid], pid)
        checks.owner_proof(records[pid], pid)

    def observed(marker, value):
        if not any(record["marker"] == marker and record["data"] == value
                   for group in records.values() for record in group):
            raise ValueError("Combined raw logs do not contain " + marker + " observation")

    def archive(value):
        proof = checks.save_archive(artifact(value["artifact"]).read_bytes())
        for key in ("sha256", "size", "metadata", "members", "game_data_sha256", "unpickled"):
            if proof[key] != value[key]:
                raise ValueError("Native saved game bytes differ from the claimed archive")

    def pixels(value, *, moving):
        if value.get("moving") is not moving:
            raise ValueError("Playback capture claims the wrong expected motion state")
        frames = []
        for name in value["captures"]:
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
            frame = decoder.decompress(artifact(name).read_bytes(), 64 * 1024 * 1024)
            if not decoder.eof or decoder.unused_data:
                raise ValueError("Combined capture is incomplete or oversized")
            framebuffer_pixel(frame, 0, 0)
            frames.append(frame)
        if len(frames) != 2:
            raise ValueError("A playback observation requires two actual captures")
        proof = checks.pixel_comparison(*frames, value["bounds"], moving=moving)
        if any(proof[key] != value[key] for key in proof):
            raise ValueError("Playback pixels differ from the recorded comparison")

    outcomes = receipt["checks"]
    for name, kind in (("canvas", "scale_canvas"), ("rive", "rive_console")):
        saved = outcomes["story_save"][name]
        for proof in (saved, saved["quick_load"]):
            for model in (proof["before"], proof["after"]):
                if model["kind"] != kind:
                    raise ValueError("Saved activity has an unexpected model kind")
                observed("SDK_CAP_ACTIVITY_STATE", model)
                if name == "canvas":
                    validate_canvas(model["state"])
            checks.restored_model(proof["before"], proof["after"], fresh_process=proof["fresh_process"])
        if saved["fresh_process"] is not True or saved["quick_load"]["fresh_process"] is not False:
            raise ValueError("Combined journey must prove both quick load and process-loss restore")
        for slot in (saved["quick_save"], saved["mobile_save"]):
            archive(slot)
        expected = ({"status": "completed", "value": {key: saved["after"]["state"][key]
                     for key in ("selected", "camera", "input_receipts")}} if name == "canvas" else
                    {"status": "completed", "value": {"progress": 100.0, "downloading": True,
                     "signal": {"SomeNumber": 11.0, "SomeBoolean": True, "SomeString": "Something"}}})
        returned = checks.single_result(records[saved["after"]["pid"]], saved["after"]["pid"], kind, expected)
        if returned != saved["result"]:
            raise ValueError("Combined native result differs from the actual story return")

    for example in (outcomes["canvas"]["app"], outcomes["canvas"]["story"]["interaction"]):
        for name in ("selection", "pan", "zoom", "probe"):
            observed("SDK_2D_INPUT", example[name])
        if (example["selection"].get("selected") is None
                or example["pan"]["camera"] == example["selection"]["camera"]
                or example["zoom"]["camera"]["scale"] <= example["pan"]["camera"]["scale"] * 1.2
                or example["probe"].get("receipt", 0) < 1):
            raise ValueError("Canvas gesture/selection/input observations are incomplete")
    observed("SDK_2D_WORKER", outcomes["table"]["worker"])
    if outcomes["table"]["worker"].get("matches") != 1:
        raise ValueError("Edited table row did not return through the asynchronous worker")
    native = outcomes["native"]
    observed("SDK_2D_READY", native["workload"])
    sizes = json.loads(SPEC.read_text())["workloads"]["renpy"]["nominal"]
    if any(native["workload"].get(key) != value for key, value in sizes.items()):
        raise ValueError("Combined native workload sizes differ from the acceptance specification")
    pixels(native["pixels"], moving=True)

    rive, save = outcomes["rive"], outcomes["story_save"]["rive"]
    cleanup = checks.rive_cleanup(logs[pids["rive_restored"]], pids["rive_restored"])
    verify_rive_playback(rive, save, observed=observed, ready=checks.rive_ready,
                         pixels=pixels, cleanup=cleanup, pid=pids["rive_restored"])
    observed("SDK_CAP_RIVE_EVENT", rive["event"])
    event = checks.meaningful_rive_event(rive["event"])
    if event["properties"]["SomeBoolean"] is not True:
        raise ValueError("Actual Rive event did not preserve its boolean type")

    navigation = outcomes["navigation"]
    for filename in ("navigation-detail.xml", "navigation-direct-link.xml", "navigation-returned-draft.xml"):
        tree = ElementTree.fromstring(artifact(filename).read_text())
        values = [value for node in tree.iter("node") for key in ("text", "content-desc")
                  if (value := node.get(key))]
        if not any(navigation["draft"] in value for value in values) or not any("rowan" in value for value in values):
            raise ValueError("Rebuilt app screen did not preserve its actual draft and selection")
    observed("SDK_CAP_APP_STATE", save["app_result"])
    if save["app_result"].get("phase") != "completed":
        raise ValueError("Combined story did not return to its application")
    return {"status": "pass", "scope": "emulator_functionality", "receipt": str(path),
            "source_sha": receipt["source_sha"], "project_input_sha256": receipt["project_input_sha256"],
            "apk_sha256": receipt["sha256"], "reasons": [], "phone_performance_proven": False}
