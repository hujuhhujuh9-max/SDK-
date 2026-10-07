"""Exercise real Flet event traffic and record local protocol latency."""

import argparse
import gc
import json
import math
import os
import platform
import select
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if not __package__:
    sys.path.insert(0, str(ROOT))

from scripts.flet_protocol import connect, receive, send, until, walk


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def benchmark(flet, output):
    sys.path.insert(0, str(ROOT / "runtime"))
    sys.path.insert(0, str(flet / "sdk/python/packages/flet/src"))
    for name in json.loads((ROOT / "runtime/flet_extensions.json").read_text()):
        sys.path.insert(0, str(flet / "sdk/python/packages" / name / "src"))
    os.environ["MSGPACK_PUREPYTHON"] = "1"
    import msgpack
    import sdk_bridge

    results = []
    with tempfile.TemporaryDirectory(prefix="flet-runtime-") as folder:
        os.environ["ANDROID_PRIVATE"] = folder
        os.environ["ANDROID_CACHE"] = str(Path(folder) / "cache")
        for cycle in range(5):
            initial = sdk_bridge.counter()
            started = time.perf_counter()
            sdk_bridge.start()
            try:
                path = Path(folder) / "flet.sock"
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(5)
                    connect(client, path)
                    send(client, msgpack, 1, {"session_id": "", "page_name": "",
                         "page": {"platform": "android", "width": 360.0,
                                  "height": 280.0, "route": "/diagnostics"}})
                    registered = receive(client, msgpack)
                    assert registered[0] == 1 and not registered[1].get("error"), registered
                    ui = until(client, msgpack, lambda message: any(
                        isinstance(item, dict) and item.get("_c") == "Button"
                        and item.get("content") == "Increment" for item in walk(message)))
                    buttons = [item for item in walk(ui) if isinstance(item, dict)
                               and item.get("_c") == "Button" and item.get("content") == "Increment"]
                    assert len(buttons) == 1, buttons
                    button_id = buttons[0]["_i"]
                    startup = (time.perf_counter() - started) * 1000
                    timings = []
                    for event in range(1, 101):
                        tick = time.perf_counter()
                        send(client, msgpack, 3, {"target": button_id, "name": "click", "data": None})
                        expected = "Count: " + str(initial + event)
                        until(client, msgpack, lambda message:
                              message[0] == 2 and expected in walk(message))
                        timings.append((time.perf_counter() - tick) * 1000)
                    assert sdk_bridge.counter() == initial + 100
                    assert not select.select([client], [], [], 0.25)[0], "Unexpected idle traffic"
                    tick = time.perf_counter()
                    sdk_bridge.stop()
                    shutdown = (time.perf_counter() - tick) * 1000
            finally:
                sdk_bridge.stop()
            assert not sdk_bridge._thread.is_alive()
            gc.collect()
            result = {"cycle": cycle + 1, "events": 100, "idle_messages": 0,
                      "startup_ms": round(startup, 3), "shutdown_ms": round(shutdown, 3),
                      "round_trip_p50_ms": round(percentile(timings, 0.5), 3),
                      "round_trip_p95_ms": round(percentile(timings, 0.95), 3),
                      "round_trip_max_ms": round(max(timings), 3)}
            results.append(result)
            print("Passed: protocol stress " + json.dumps(result), flush=True)
    report = {"scope": "Linux UDS event-to-UI-patch latency; excludes device input/rendering",
              "python": platform.python_version(), "platform": platform.platform(),
              "cpu_count": os.cpu_count(), "events_verified": 500, "cycles": results}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print("Protocol measurements: " + json.dumps(report), flush=True)


def check_story_protocol():
    """Verify the actual Flet protocol against Ren'Py-side publication/consumption."""
    import msgpack
    import sdk_bridge

    story = sdk_bridge.story
    story.reset()
    sdk_bridge.update_reading_status(False, "instant", "Reading choices kept.")
    revision = story.minigame("star_map")
    with tempfile.TemporaryDirectory(prefix="renfletpy-check-") as folder:
        os.environ["ANDROID_PRIVATE"] = folder
        os.environ["ANDROID_CACHE"] = str(Path(folder) / "cache")
        sdk_bridge.start()
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(5)
                connect(client, Path(folder) / "flet.sock")
                send(client, msgpack, 1, {"session_id": "", "page_name": "", "page": {
                    "platform": "android", "width": 411.0, "height": 292.0, "route": "/"}})
                registered = receive(client, msgpack)
                assert registered[0] == 1 and not registered[1].get("error"), registered
                page_id = registered[1]["page_patch"]["_i"]
                ui = until(client, msgpack, lambda message: "Deneb" in walk(message))
                assert sdk_bridge.presentation() == "interlude"
                for label, expected in (("Altair", "Start with Deneb. Try again."),
                                        ("Deneb", "Stars connected: 1 / 3"),
                                        ("Vega", "Stars connected: 2 / 3"),
                                        ("Altair", "Constellation aligned.")):
                    button = next(item for item in walk(ui) if isinstance(item, dict)
                                  and item.get("_c") == "Button" and item.get("content") == label)
                    send(client, msgpack, 3, {"target": button["_i"], "name": "click", "data": None})
                    ui = until(client, msgpack, lambda message: expected in walk(message))
                assert story.consume(revision) == "aligned"
                assert story.consume(revision) is None
                story.close(revision)
                until(client, msgpack, lambda message: message[0] == 2 and sdk_bridge.presentation() == "scene")
                assert story.current() is None

                # Publish from a different thread, as the Ren'Py story engine does.
                import threading
                owner = threading.Thread(target=lambda: story.show("Mira", "Optional inventory panel."))
                owner.start()
                owner.join(timeout=5)
                assert not owner.is_alive()
                until(client, msgpack, lambda message: "Optional inventory panel." in walk(message))
                pending = story.current()
                assert not story.tap_star(revision, "deneb"), "Old minigame taps advanced a new panel"

                def route(path):
                    send(client, msgpack, 4, {"id": page_id, "props": {"route": path}})
                    send(client, msgpack, 3, {"target": page_id, "name": "route_change", "data": {"route": path}})

                route("/menu")
                ui = until(client, msgpack, lambda message: "Paused" in walk(message))
                assert sdk_bridge.presentation() == "page"
                save = next(item for item in walk(ui) if isinstance(item, dict)
                            and item.get("_c") == "Button" and item.get("content") == "Quick save")
                send(client, msgpack, 3, {"target": save["_i"], "name": "click", "data": None})
                until(client, msgpack, lambda message: "Saving…" in walk(message))
                assert sdk_bridge.take_save_request() == "save"
                assert sdk_bridge.take_save_request() is None
                assert not sdk_bridge.request_save("save"), "Busy save accepted duplicate work"
                snapshot = story.snapshot()
                sdk_bridge.update_save_status(True, "Saved protocol checkpoint.")
                ui = until(client, msgpack, lambda message: "Saved protocol checkpoint." in walk(message))
                load = next(item for item in walk(ui) if isinstance(item, dict)
                            and item.get("_c") == "Button" and item.get("content") == "Quick load")
                send(client, msgpack, 3, {"target": load["_i"], "name": "click", "data": None})
                until(client, msgpack, lambda message: "Loading…" in walk(message))
                assert sdk_bridge.take_save_request() == "load"
                # Stand in for the native load callback. Revision and live UI
                # restoration are real; native serialization is checked on Android.
                restored = story.restore(snapshot)
                assert restored != pending.revision
                assert not story.choose(pending.revision, "continue")
                sdk_bridge.update_save_status(True, "Loaded protocol checkpoint.")
                until(client, msgpack, lambda message: "Loaded protocol checkpoint." in walk(message))
                transcript = (("Mira", "Before sunrise.", ""),
                              ("Star map", "Connect the triangle.", "Constellation aligned"),
                              ("Mira", "A morning to remember.", ""),
                              (pending.speaker, pending.text, ""))
                sdk_bridge.publish_transcript(transcript)
                route("/history")
                ui = until(client, msgpack, lambda message: "→ Constellation aligned" in walk(message))
                assert "Before sunrise." in walk(ui) and "A morning to remember." in walk(ui)
                # Native dialogue/history updates cross threads while history is
                # open; no native APIs or views are mutated on that publisher.
                updated = transcript + (("Mira", "One more native line.", ""),)
                owner = threading.Thread(target=lambda: sdk_bridge.publish_transcript(updated))
                owner.start()
                owner.join(timeout=5)
                assert not owner.is_alive()
                until(client, msgpack, lambda message: "One more native line." in walk(message))

                route("/settings")
                ui = until(client, msgpack, lambda message: "Text size: Standard" in walk(message))
                larger = next(item for item in walk(ui) if isinstance(item, dict)
                              and item.get("_c") == "Button" and item.get("content") == "Larger")
                send(client, msgpack, 3, {"target": larger["_i"], "name": "click", "data": None})
                until(client, msgpack, lambda message: "Keeping your reading choice…" in walk(message))
                assert sdk_bridge.take_reading_request() == ("large_text", True)
                assert sdk_bridge.take_reading_request() is None
                assert not sdk_bridge.request_quit() and not sdk_bridge.request_save("save")
                owner = threading.Thread(target=lambda: sdk_bridge.update_reading_status(
                    True, "instant", "Reading choice kept for your next visit."))
                owner.start()
                owner.join(timeout=5)
                assert not owner.is_alive()
                ui = until(client, msgpack, lambda message: "Text size: Larger" in walk(message))
                assert any(isinstance(item, dict) and item.get("_c") == "Text"
                           and item.get("value", "").startswith("A clear sky") and item.get("size") == 25
                           for item in walk(ui)), ui
                animated = next(item for item in walk(ui) if isinstance(item, dict)
                                and item.get("_c") == "Button" and item.get("content") == "Animated")
                send(client, msgpack, 3, {"target": animated["_i"], "name": "click", "data": None})
                until(client, msgpack, lambda message: "Keeping your reading choice…" in walk(message))
                assert sdk_bridge.take_reading_request() == ("text_speed", "animated")
                sdk_bridge.update_reading_status(True, "animated", "Reading choice kept for your next visit.")
                until(client, msgpack, lambda message: "Dialogue: Animated" in walk(message))
                route("/")
                until(client, msgpack, lambda message: "Optional inventory panel." in walk(message))
                assert story.current().revision == restored and story.consume(restored) is None
                assert story.current().text == pending.text
                assert sdk_bridge.presentation() == "interlude"
        finally:
            sdk_bridge.stop()
            story.reset()
        assert not story._listeners, "Closed Flet page retained a story listener"
    print("Passed: real RenFletPy result, scene return, cross-thread panel, save/load, shared reading controls and restored progress")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".android-build/runtime-check/protocol.json")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    from prepare import BuildInputs
    from build_android import stage_flet

    inputs = BuildInputs(ROOT / ".android-build")
    inputs.setup("flet")
    work = inputs.cache / "runtime-inspection"
    work.mkdir(parents=True, exist_ok=True)
    flet = stage_flet(inputs, work)
    subprocess.run([sys.executable, str(ROOT / "scripts/check_flet_bridge.py"), str(flet)], check=True)
    benchmark(flet, args.output)
    check_story_protocol()


if __name__ == "__main__":
    main()
