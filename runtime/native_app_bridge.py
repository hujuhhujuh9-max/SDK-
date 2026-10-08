"""Native-thread adapter for the opt-in Lantern app project, never saved."""

import threading
import logging

if __package__:
    from . import sdk_bridge
else:
    import sdk_bridge

_driver = None
HOST_SCHEMA = 1


class NativeAppBridge:
    def __init__(self):
        import renpy.exports as native
        import renpy.store as store
        from renpy import config

        self.native, self.store = native, store
        self.thread = threading.get_ident()
        self.command = None
        self.session_id = self.run_id = None
        sdk_bridge.configure_app_story("lantern", "The Last Lantern", initializing=True, native_host=True)
        # B's standalone host has a different saved caller stack. Only saves
        # made by this host may restore here, even with the same story profile.
        self.slot_owner = store.sdk_native_story_owns_slot
        self.checkpoint_saver = store.sdk_native_story_save_checkpoint
        store.sdk_native_story_owns_slot = owns_slot
        store.sdk_native_story_save_checkpoint = save_checkpoint
        config.save_json_callbacks.append(self.save_metadata)
        config.after_load_callbacks.append(self.recover)
        sdk_bridge.initialize_reading(bool(getattr(store.persistent, "sdk_app_large_text", False)),
                                     getattr(store.persistent, "sdk_app_text_speed", None) or "instant")

    def check_thread(self):
        if threading.get_ident() != self.thread:
            raise RuntimeError("Native story operations require Ren'Py's thread")

    def save_metadata(self, metadata):
        metadata["sdk_app_host"] = HOST_SCHEMA

    def owns_slot(self, slot):
        if not self.slot_owner(slot):
            return False
        metadata = self.native.slot_json(slot)
        return (isinstance(metadata, dict) and type(metadata.get("sdk_app_host")) is int
                and metadata["sdk_app_host"] == HOST_SCHEMA)

    def save_checkpoint(self):
        self.check_thread()
        result = self.checkpoint_saver()
        sdk_bridge.update_save_status(self.owns_slot(self.store.SDK_NATIVE_STORY_SLOT),
                                      self.store.sdk_native_story_message)
        return result

    def recover(self):
        """Called after B's native validation; never replay saved command IDs."""
        self.check_thread()
        self.command = None
        value = dict(self.store.sdk_native_story_status())
        self.run_id = value["run_id"]
        state = {"running": "active", "returned": "suspended", "completed": "completed"}
        self.session_id = sdk_bridge.restore_story_status(
            "lantern" if value["status"] in state else None,
            state=state.get(value["status"], "suspended"),
            result=value if value["status"] == "completed" else None,
            message="Story restored." if self.run_id else "Choose a story to begin.",
            return_route=sdk_bridge.story_status()["return_route"])
        sdk_bridge.update_save_status(self.store.sdk_native_story_owns_slot(self.store.SDK_NATIVE_STORY_SLOT),
                                      "Story restored. Application records are kept.")

    def confirm(self, success, message, *, navigate=True):
        command, self.command = self.command, None
        return sdk_bridge.confirm_story_command(command["request_id"], success=success,
                                               message=message, navigate=navigate)

    def clear_continuation(self):
        self.store._sdk_native_story_clear_recovery()
        self.store.sdk_native_story_state = None
        self.run_id = None

    def tick(self):
        self.check_thread()
        if sdk_bridge.quitting():
            self.native.quit()
        value = dict(self.store.sdk_native_story_status())
        scene = self.native.get_screen("sdk_native_story_scene") is not None
        idle = self.native.get_screen("sdk_app_idle") is not None
        if self.command is not None:
            if self.command["action"] in ("start", "resume") and scene and value["status"] == "running":
                session_id = self.command["session_id"]
                if self.confirm(True, "Story ready."):
                    self.session_id, self.run_id = session_id, value["run_id"]
            return
        reading = sdk_bridge.take_reading_request()
        if reading is not None:
            name, selected = reading
            previous = sdk_bridge.reading_status()
            try:
                if name == "large_text":
                    self.store.persistent.sdk_app_large_text = selected
                else:
                    self.store.persistent.sdk_app_text_speed = selected
                self.native.save_persistent()
                message = "Reading choice kept."
            except Exception:
                logging.exception("Optional app reading preference save failed")
                self.store.persistent.sdk_app_large_text = previous["large_text"]
                self.store.persistent.sdk_app_text_speed = previous["text_speed"]
                message = "Could not keep the reading choice. Try again."
            sdk_bridge.update_reading_status(bool(getattr(self.store.persistent, "sdk_app_large_text", False)),
                getattr(self.store.persistent, "sdk_app_text_speed", None) or "instant", message)
        save = sdk_bridge.take_save_request()
        if save is not None:
            if save == "save":
                self.store.sdk_native_story_save_checkpoint()
            else:
                self.store.sdk_native_story_load_checkpoint()
            sdk_bridge.update_save_status(self.store.sdk_native_story_owns_slot(self.store.SDK_NATIVE_STORY_SLOT),
                                          self.store.sdk_native_story_message)
        if not (scene or idle):
            return
        command = sdk_bridge.take_story_command()
        if command is None:
            return
        self.command = command
        if command["story_id"] != "lantern":
            self.confirm(False, "This project does not contain that story.")
        elif scene and value["status"] == "running":
            if command["action"] == "resume":
                # A restored active interaction is already in the native label.
                self.confirm(True, "Story ready.")
            else:
                # Native Return raises EndInteraction; confirmation belongs to
                # returned(), after the ordinary caller receives native truth.
                self.store.sdk_native_story_return()
        elif command["action"] in ("start", "resume"):
            self.native.end_interaction(command["action"])
        elif command["action"] == "cancel" and value["status"] == "returned":
            self.clear_continuation()
            self.confirm(True, "Story cancelled.")
        else:
            self.confirm(False, "No active native story to return from.")

    def returned(self, result):
        """Handle the ordinary label's plain result. True starts a replacement."""
        self.check_thread()
        value = dict(self.store.sdk_native_story_status())
        # A user can Return/finish before the first command timer observes a
        # newly started scene. Its native result proves entry; bind that fresh
        # run to the still-pending Start before publishing its final phase.
        if (result == value and self.command is not None and self.command["action"] == "start"
                and value["run_id"] != self.run_id and value["status"] in ("returned", "completed")):
            session_id = self.command["session_id"]
            # Entry already ended. Publish its session without sending a Start
            # navigation that could arrive after the returned/terminal state.
            if self.confirm(True, "Story ready.", navigate=False):
                self.session_id, self.run_id = session_id, value["run_id"]
        if result != value or value["run_id"] != self.run_id:
            if self.command is not None:
                self.confirm(False, "The native story could not be opened. Try again.")
            return False
        # A native button can end the scene before the command timer runs.
        # Consume its concurrent mailbox request here on the same native thread.
        if self.command is None:
            self.command = sdk_bridge.take_story_command()
            if self.command is not None and self.command["story_id"] != "lantern":
                self.confirm(False, "This project does not contain that story.")
        if value["status"] == "returned":
            if self.command is None:
                sdk_bridge.return_from_story(self.session_id)
            elif self.command["action"] == "return":
                self.confirm(True, "Story paused.")
            elif self.command["action"] == "cancel":
                self.clear_continuation()
                self.confirm(True, "Story cancelled.")
            elif self.command["action"] == "start":
                return True
            elif self.command["action"] == "resume":
                self.confirm(False, "The native story paused before Resume. Try again.")
                sdk_bridge.return_from_story(self.session_id, message="Story paused. Resume to continue.")
        elif value["status"] == "completed":
            if self.command is not None and self.command["action"] == "start":
                return True
            sdk_bridge.finish_story(self.session_id, result=value, message="The lantern is home.")
            self.command = None
        elif self.command is not None:
            self.confirm(False, "No live native story to resume.")
        return False


def install():
    global _driver
    _driver = NativeAppBridge()


def tick():
    _driver.tick()


def recover():
    _driver.recover()


def returned(result):
    return _driver.returned(result)


def owns_slot(slot):
    return _driver.owns_slot(slot)


def save_checkpoint():
    return _driver.save_checkpoint()
