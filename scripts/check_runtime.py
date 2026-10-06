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

from check_flet_bridge import connect

ROOT = Path(__file__).resolve().parents[1]


def exact(client, count):
    data = bytearray()
    while len(data) < count:
        chunk = client.recv(count - len(data))
        if not chunk:
            raise RuntimeError("Flet closed its protocol connection")
        data.extend(chunk)
    return bytes(data)


def receive(client, codec):
    size = int.from_bytes(exact(client, 4), "little")
    assert 0 < size <= 16 * 1024 * 1024, size
    packet = exact(client, size)
    assert packet[0] == 0
    message = codec.unpackb(packet[1:], strict_map_key=False)
    assert message[0] != 6, ("Flet session crashed", message)
    return message


def send(client, codec, action, body):
    packet = b"\x00" + codec.packb([action, body])
    client.sendall(len(packet).to_bytes(4, "little") + packet)


def walk(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from walk(child)


def until(client, codec, predicate):
    for _ in range(100):
        message = receive(client, codec)
        if predicate(message):
            return message
    raise AssertionError("Expected UI patch was not received")


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
    revision = story.show("Mira", "Which way?", (("sky", "Look at the sky"), ("dome", "Enter the observatory")))
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
                ui = until(client, msgpack, lambda message: "Look at the sky" in walk(message))
                button = next(item for item in walk(ui) if isinstance(item, dict)
                              and item.get("_c") == "Button" and item.get("content") == "Look at the sky")
                send(client, msgpack, 3, {"target": button["_i"], "name": "click", "data": None})
                until(client, msgpack, lambda message: any(isinstance(item, dict)
                      and item.get("disabled") is True for item in walk(message)))
                assert story.consume(revision) == "sky"
                assert story.consume(revision) is None

                # Publish from a different thread, as the Ren'Py story engine does.
                import threading
                owner = threading.Thread(target=lambda: story.show("Mira", "The sky is changing."))
                owner.start()
                owner.join(timeout=5)
                assert not owner.is_alive()
                until(client, msgpack, lambda message: "The sky is changing." in walk(message))
                pending = story.current()
                assert not story.choose(revision, "dome"), "Old buttons advanced a new line"

                def route(path):
                    send(client, msgpack, 4, {"id": page_id, "props": {"route": path}})
                    send(client, msgpack, 3, {"target": page_id, "name": "route_change", "data": {"route": path}})

                route("/menu")
                until(client, msgpack, lambda message: "Paused" in walk(message))
                assert sdk_bridge.presentation() == "page"
                route("/history")
                until(client, msgpack, lambda message: "→ Look at the sky" in walk(message))
                route("/")
                until(client, msgpack, lambda message: "The sky is changing." in walk(message))
                assert story.current() == pending and story.consume(pending.revision) is None
                assert sdk_bridge.presentation() == "story"
        finally:
            sdk_bridge.stop()
            story.reset()
        assert not story._listeners, "Closed Flet page retained a story listener"
    print("Passed: real RenFletPy choices, cross-thread dialogue, transcript and menu/resume")


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
