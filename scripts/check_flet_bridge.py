"""Exercise the real Flet socket protocol and host-controlled shutdown."""

import argparse
import importlib
import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.flet_protocol import connect, receive, send


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("flet_root", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.flet_root.resolve() / "sdk/python/packages/flet/src"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
    names = json.loads((Path(__file__).resolve().parents[1] / "runtime/flet_extensions.json").read_text())
    for name in names:
        sys.path.insert(0, str(args.flet_root / "sdk/python/packages" / name / "src"))
    os.environ["FLET_PLATFORM"] = "android"
    os.environ["MSGPACK_PUREPYTHON"] = "1"
    import msgpack
    import sdk_bridge
    for name in names:
        importlib.import_module(name.replace("-", "_"))
    print("Passed: all", len(names), "Flet Python extension imports")
    suite = unittest.defaultTestLoader.discover(
        str(Path(__file__).resolve().parents[1] / "tests"),
        pattern="test_flet_lifetime.py",
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped:
        raise RuntimeError("Prepared Flet lifetime checks must pass without skips")

    with tempfile.TemporaryDirectory(prefix="flet-check-") as folder:
        os.environ["ANDROID_PRIVATE"] = folder
        os.environ["ANDROID_CACHE"] = str(Path(folder) / "cache")
        for attempt in range(2):
            sdk_bridge.start()
            try:
                path = Path(folder) / "flet.sock"
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(5)
                    connect(client, path)
                    send(client, msgpack, 1, {
                        "session_id": "", "page_name": "", "page": {
                            "platform": "android", "width": 360.0, "height": 280.0,
                        },
                    })
                    actions = []
                    for _ in range(2):
                        message = receive(client, msgpack, max_size=1024 * 1024 - 1)
                        actions.append(message[0])
                    assert actions == [1, 2], actions
                    sdk_bridge.stop()
            finally:
                sdk_bridge.stop()
            assert not sdk_bridge._thread.is_alive()
            print("Passed: real Flet handshake, UI patch and clean shutdown cycle", attempt + 1)
        sdk_bridge.start()
        sdk_bridge.stop()
        assert not sdk_bridge._thread.is_alive()
        print("Passed: shutdown during startup")


if __name__ == "__main__":
    main()
