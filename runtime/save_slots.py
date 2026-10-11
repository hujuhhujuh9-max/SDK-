"""Named bookmarks backed by the owning Ren'Py thread's native save API."""

import hashlib
import json
import logging
import math
import os
import re
import threading
import uuid

if __package__:
    from .renfletpy import story
else:
    from renfletpy import story

SLOT_PATTERN = r"renfletpy-manual-[0-9a-f]{32}"
native = None


def save_name(value):
    if not isinstance(value, str):
        raise ValueError("Give the save a name.")
    value = value.strip()
    if not value or len(value) > 80 or not value.isprintable():
        raise ValueError("Use a name of 1–80 printable characters.")
    return value


def named_slot(value):
    return isinstance(value, str) and re.fullmatch(SLOT_PATTERN, value) is not None


class NativeSaveSlots:
    def __init__(self, renpy):
        self.renpy = renpy
        self.thread_id = threading.get_ident()

    def _native_thread(self):
        if threading.get_ident() != self.thread_id:
            raise RuntimeError("Save operations belong to Ren'Py's thread")

    def catalog(self):
        self._native_thread()
        entries = []
        for slot in self.renpy.list_slots("^" + SLOT_PATTERN + "$"):
            if not named_slot(slot):
                continue
            metadata = self.renpy.slot_json(slot)
            mtime = self.renpy.slot_mtime(slot)
            if mtime is None:
                continue
            fingerprint = hashlib.sha256(json.dumps(
                [mtime, metadata], sort_keys=True, ensure_ascii=True).encode()).hexdigest()
            details = metadata.get("renfletpy_slot", {}) if isinstance(metadata, dict) else {}
            supported = (isinstance(details, dict) and type(details.get("version")) is int
                         and details["version"] == 1)
            try:
                title = save_name(metadata.get("_save_name"))
            except (ValueError, AttributeError):
                title = "Unreadable save"
                supported = False
            scene = details.get("scene", "") if isinstance(details, dict) else ""
            entries.append({"slot": slot, "name": title,
                            "scene": scene if isinstance(scene, str) else "",
                            "mtime": float(mtime) if math.isfinite(float(mtime)) else 0,
                            "fingerprint": fingerprint, "loadable": supported})
        return tuple(sorted(entries, key=lambda row: (-row["mtime"], row["slot"])))

    def run(self, bridge, command, scene_title, quick_slot):
        self._native_thread()
        action = command if isinstance(command, str) else command["action"]
        quick = isinstance(command, str) and action in ("save", "load")
        message = "Saved games loaded."
        try:
            if action != "list":
                if quick:
                    slot, name = quick_slot, scene_title
                    if action == "load" and not self.renpy.can_load(slot):
                        bridge.update_save_status(False, "No saved game yet.")
                        return
                elif action == "create":
                    slot = "renfletpy-manual-" + uuid.uuid4().hex
                    if self.renpy.can_load(slot):
                        raise RuntimeError("The new save slot already exists.")
                    name = save_name(command["name"])
                else:
                    slot = command["slot"]
                    row = next((row for row in self.catalog() if row["slot"] == slot), None)
                    if row is None or row["fingerprint"] != command["expected"]:
                        raise ValueError("That save changed. Review the refreshed list and try again.")
                    name = row["name"]
                if action in ("save", "create", "overwrite"):
                    self.renpy.take_screenshot()
                    options = {} if quick else {"extra_json": {"renfletpy_slot": {"version": 1, "scene": scene_title}}}
                    self.renpy.save(slot, extra_info=name, **options)
                    if not self.renpy.can_load(slot):
                        raise RuntimeError("The save was not written.")
                    message = "Saved. You can return here after closing the app." if quick else "Saved: " + name
                    if quick:
                        current = story.current()
                        print("SDK_RUNNER_SAVE action=saved progress=%s pid=%s" %
                              (len(current.progress) if current is not None else 0, os.getpid()), flush=True)
                elif action == "delete":
                    self.renpy.unlink_save(slot)
                    if self.renpy.can_load(slot):
                        raise RuntimeError("The save was not deleted.")
                    message = "Deleted: " + name
                elif action == "load":
                    if not quick and not row["loadable"]:
                        raise ValueError("This save's metadata is unsupported. Your other saves are kept.")
                    token = bridge.begin_save_load()
                    if token is None:
                        raise ValueError("Could not show the saved game. Please try again.")
                    try:
                        self.renpy.load(slot)
                    finally:
                        bridge.end_save_load(token)
                    # Native loads do not return on success. Signature refusal does.
                    message = "Load cancelled."
                else:
                    raise ValueError("Unknown named save action")
                if not quick:
                    print("SDK_RUNNER_SLOT action=%s slot=%s pid=%s" %
                          (action, slot, os.getpid()), flush=True)
        except ValueError as error:
            message = str(error)
        except Exception:
            logging.exception("Named save %s failed", action)
            message = "Could not %s. Please try again." % action
        if not quick:
            try:
                bridge.publish_save_slots(self.catalog())
            except Exception:
                logging.exception("Named save listing failed")
                message = "Could not refresh saved games. Please try again."
        bridge.update_save_status(self.renpy.can_load(quick_slot), message)


def bind(renpy):
    global native
    native = NativeSaveSlots(renpy)
    return native
