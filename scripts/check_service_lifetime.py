"""Inspect real prepared-Flet service references after capability-view navigation."""

import argparse
import asyncio
import gc
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path


async def inspect():
    from flet.controls.context import _context_page
    from flet.messaging.connection import Connection
    from flet.messaging.session import Session
    from flet.pubsub.pubsub_hub import PubSubHub
    from capability_demo import open_page

    class Sink(Connection):
        def __init__(self):
            super().__init__()
            self.loop = asyncio.get_running_loop()
            self.pubsubhub = PubSubHub(loop=self.loop)
            self.patches = 0

        def send_message(self, message):
            # Discard protocol messages so this inspection doesn't retain trees.
            self.patches += 1

    connection = Sink()
    session = Session(connection)
    page = session.page
    session.get_page_patch()
    token = _context_page.set(page)

    async def navigate(route):
        # Native route acknowledgement is outside this Python reference check.
        page.route = route
        page.update()

    page.push_route = navigate

    def counts():
        return dict(Counter(service.__class__.__name__ for service in page._services._services))

    baseline = counts()
    samples = []
    retained_ids = None
    retained_counts = None
    enabled = gc.isenabled()
    gc.disable()
    try:
        for cycle in range(20):
            await asyncio.wait_for(open_page(page), 5)
            mounted = counts()
            current_ids = sorted(service._i for service in page._services._services)
            if retained_ids is None:
                retained_ids, retained_counts = current_ids, mounted
                if len(retained_ids) != 9:
                    raise RuntimeError("Capability page must own exactly nine reusable services")
            if current_ids != retained_ids:
                raise RuntimeError("Navigation created replacement/duplicate native services")
            page.views.pop()
            page.update()
            page._services.unregister_services()
            samples.append({"cycle": cycle + 1, "mounted": mounted, "after_pop": counts()})
            if counts() != retained_counts:
                raise RuntimeError("Capability service set changed after view removal: " + str(counts()))
        gc.collect()
        page._services.unregister_services()
        final = counts()
        result = {"scope": "Python references in the prepared Flet service registry; no native-memory claim",
                  "baseline": baseline, "retained_service_ids": retained_ids,
                  "cycles": samples, "after_collection": final,
                  "protocol_patches": connection.patches}
        output = Path(".android-build/runtime-check/service-lifetime.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2))
        print("Service lifetime inspection: " + json.dumps(result, sort_keys=True), flush=True)
        if final != retained_counts:
            raise RuntimeError("Page-owned service set changed after collection")
    finally:
        if enabled:
            gc.enable()
        _context_page.reset(token)
        session.close()
        await asyncio.sleep(0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("flet_root", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    packages = args.flet_root.resolve() / "sdk/python/packages"
    sys.path.insert(0, str(root / "runtime"))
    sys.path.insert(0, str(packages / "flet/src"))
    for name in json.loads((root / "runtime/flet_extensions.json").read_text()):
        sys.path.insert(0, str(packages / name / "src"))
    os.environ["FLET_PLATFORM"] = "android"
    os.environ["MSGPACK_PUREPYTHON"] = "1"
    with tempfile.TemporaryDirectory(prefix="runner-service-check-") as folder:
        os.environ["FLET_ASSETS_DIR"] = folder
        asyncio.run(inspect())


if __name__ == "__main__":
    main()
