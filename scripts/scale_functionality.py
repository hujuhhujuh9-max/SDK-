"""Revalidate the combined driver's raw receipt without operating a device."""

import json
import re
import zlib
from pathlib import Path
from xml.etree import ElementTree

from runtime.scale_workloads import validate_canvas
from scripts.scale_evidence import SPEC, framebuffer_pixel, sha256


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

    def pixels(value):
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
        proof = checks.pixel_comparison(*frames, value["bounds"], moving=value["moving"])
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
    pixels(native["pixels"])

    rive, save = outcomes["rive"], outcomes["story_save"]["rive"]
    for group, model in ((rive["quick_load_ready"], save["quick_load"]["after"]),
                         (rive["restored_ready"], save["after"])):
        for role in ("forest", "signal"):
            observed("SDK_CAP_RIVE_READY", group[role])
            checks.rive_ready(group[role], model["state"], role)
    for name, active, reasons in (("background", False, ("inactive", "hidden", "paused")),
                                  ("foreground", True, ("resumed",))):
        observed("SDK_CAP_RIVE_LIFECYCLE", rive[name])
        if rive[name]["data"].get("active") is not active or rive[name]["data"].get("reason") not in reasons:
            raise ValueError("Actual Rive lifecycle did not suspend and resume")
    observed("SDK_CAP_RIVE_EVENT", rive["event"])
    event = checks.meaningful_rive_event(rive["event"])
    if event["properties"]["SomeBoolean"] is not True:
        raise ValueError("Actual Rive event did not preserve its boolean type")
    pixels(rive["pixels"]["initial"])
    pixels(rive["pixels"]["restored"])
    cleanup = checks.rive_cleanup(logs[pids["rive_restored"]], pids["rive_restored"])
    if cleanup is None or cleanup != rive["cleanup"]:
        raise ValueError("Combined actual Rive controller cleanup differs from its raw log")

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
