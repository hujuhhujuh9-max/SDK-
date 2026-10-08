"""Native-thread helpers for the opt-in, single-story application recipe.

The controller lives in this module, outside Ren'Py's saved store. Its only
saved input is ``_app_recipe_state``: a small versioned dictionary. Ren'Py
still saves the actual script position and the existing interlude adapter.
"""

import logging
import os
import threading

STORY_ID = "app-recipe"
SAVE_SLOT = "app-recipe-quick"
SAVE_NAMESPACE = "app-starter"
STATE_VERSION = 1
native = None


def configure_save_location(renpy):
    """Set config.savedir in python early, before any save/persistent scan.

    Android's platform resolver ignores config.save_directory. Use its chosen
    writable base, then a recipe subdirectory; never guess Android paths.
    """
    base = renpy.config.savedir
    if base is None:
        base = renpy.__main__.path_to_saves(renpy.config.gamedir, "sdk-runner-integration")
    if os.path.basename(os.path.normpath(base)) != SAVE_NAMESPACE:
        base = os.path.join(base, SAVE_NAMESPACE)
    renpy.config.savedir = base
    print("SDK_RUNNER_APP_SAVE_DIR path=%s pid=%s" % (base, os.getpid()), flush=True)
    return base


def saved_state(phase="ready", value=None):
    if phase not in ("ready", "active", "completed"):
        raise ValueError("Unknown app story phase")
    if ((phase == "completed" and (not isinstance(value, str) or not value))
            or (phase != "completed" and value is not None)):
        raise ValueError("Only a completed app story has a nonempty result")
    return {"version": STATE_VERSION, "story_id": STORY_ID, "phase": phase, "value": value}


def validate_state(state):
    if (not isinstance(state, dict) or type(state.get("version")) is not int
            or state.get("version") != STATE_VERSION
            or state.get("story_id") != STORY_ID or set(state) != {"version", "story_id", "phase", "value"}):
        raise ValueError("Invalid or unsupported app story save")
    return saved_state(state["phase"], state["value"])


class NativeStory:
    """Execute an accepted mailbox command on the owning native thread."""

    def __init__(self, renpy, session, bridge, story, poll_choice=None):
        self.renpy = renpy
        self.session = session
        self.bridge = bridge
        self.story = story
        self.original_poll_choice = poll_choice
        self.thread_id = threading.get_ident()
        self.revision = None
        self.resume_command_id = None
        self.completion_released = False

    def _native_thread(self):
        if threading.get_ident() != self.thread_id:
            raise RuntimeError("App story operations belong to Ren'Py's thread")

    def _marker(self, action):
        status = self.session.status()
        print("SDK_RUNNER_APP_STORY action=%s phase=%s revision=%s pid=%s" %
              (action, status["phase"], status["revision"], os.getpid()), flush=True)

    def checkpoint_available(self):
        self._native_thread()
        if not self.renpy.can_load(SAVE_SLOT):
            return False
        metadata = self.renpy.slot_json(SAVE_SLOT) or {}
        try:
            return validate_state(metadata.get("app_story"))["phase"] == "active"
        except ValueError:
            return False

    def enter_home(self):
        self._native_thread()
        try:
            self.session.initialize_saved(self.checkpoint_available())
        except Exception:
            # Every Start/Resume rechecks native availability, so a discovery
            # failure cannot silently replace an unreadable checkpoint.
            logging.exception("App story checkpoint discovery failed")
        self._marker("ready")
        print("SDK_RUNNER_RENPY_READY pid=%s" % os.getpid(), flush=True)

    def save_metadata(self, metadata):
        # This callback can run on Ren'Py's autosave worker. Publish only the
        # replace-only plain native state; do not touch session/native APIs.
        metadata["app_story"] = validate_state(self.renpy.store._app_recipe_state)

    def poll_choice(self):
        self._native_thread()
        status = self.session.status()
        # Hold a selected result as soon as Return is accepted, including the
        # interval before Flet/Android finishes changing the visible surface.
        if status["busy"] or (status["phase"] == "active" and not status["showing_story"]):
            return
        self.original_poll_choice()

    def poll(self):
        self._native_thread()
        command = self.session.take_request()
        if command is None:
            return
        command_id = command["command_id"]
        action = command["action"]
        if action == "start":
            # Discovery can race an early Start; never replace a checkpoint
            # the submitting UI did not yet know existed.
            try:
                available = self.checkpoint_available()
            except Exception:
                logging.exception("App story checkpoint could not be checked")
                self.session.finish(command_id, success=False,
                                    message="Could not check the saved story. Please try again.")
                return
            if available and not command.get("replace"):
                self.session.finish(command_id, success=False,
                                    message="A saved story exists. Confirm before starting again.")
                return
            try:
                self.renpy.unlink_save("_reload-1")
            except Exception:
                logging.exception("Old app story recovery could not be cleared")
                self.session.finish(command_id, success=False,
                                    message="Could not clear old recovery. Your current story is kept.")
                return
            if not self.session.finish(command_id, message="Story started."):
                return
            self.revision = self.session.status()["revision"]
            self.renpy.store._app_recipe_state = saved_state("active")
            self.renpy.store._interlude_revision = None
            self.renpy.store._tactics_view = None
            self.story.reset()
            self._marker("started")
            # A confirmed replacement can arrive during a nested interlude.
            # Discard its call stack, then start the one recipe without an
            # application restart or a second interpreter/context.
            self.renpy.set_return_stack([])
            self.renpy.jump("app_recipe_start")
        elif action == "resume" and self.session.status()["resume_kind"] == "saved":
            try:
                if not self.checkpoint_available():
                    raise ValueError("The saved native checkpoint is unavailable")
                self.resume_command_id = command_id
                self.renpy.load(SAVE_SLOT)
                # Successful native load never returns. A declined signature
                # prompt does, and must release the command without routing.
                self.resume_command_id = None
                self.session.finish(command_id, success=False, message="Resume cancelled.")
            except Exception:
                self.resume_command_id = None
                logging.exception("App story checkpoint could not be loaded")
                self.session.finish(command_id, success=False,
                                    message="Could not resume the saved story. Please try again.")
        else:
            # Return and live Resume acknowledge navigation only. They do not
            # end the native interaction, consume a choice, or claim a save.
            message = ("Your place is kept in this session. Quick save keeps a checkpoint."
                       if action == "return" else "Continuing your current story.")
            if self.session.finish(command_id, message=message):
                self._marker(action)

    def restore(self):
        """Run after the existing interlude restoration on Ren'Py's thread."""
        self._native_thread()
        command_id, self.resume_command_id = self.resume_command_id, None
        try:
            state = validate_state(self.renpy.store._app_recipe_state)
        except ValueError:
            logging.exception("Invalid app story checkpoint; returning to the native home wait")
            if command_id is not None:
                self.session.finish(command_id, success=False,
                                    message="This saved story is unsupported. Your app data is kept.")
            self.renpy.store._app_recipe_state = saved_state()
            self.renpy.store._interlude_revision = None
            self.renpy.store._tactics_view = None
            self.story.reset()
            self.revision = self.session.restore(
                phase="ready", resume_kind="unavailable", showing_story=False,
                message="This saved story is unsupported. You can start a new story.")
            self.renpy.set_return_stack([])
            self.renpy.jump("app_recipe_home")
        previous = self.session.status()
        phase = state["phase"]
        result = ({"story_id": STORY_ID, "outcome": "completed", "value": state["value"]}
                  if phase == "completed" else None)
        resume_kind = "live" if phase == "active" else "unavailable"
        if phase != "active":
            try:
                if self.checkpoint_available():
                    resume_kind = "saved"
            except Exception:
                logging.exception("Recovered app story checkpoint could not be checked")
        self.revision = self.session.restore(
            phase=phase, resume_kind=resume_kind,
            showing_story=phase == "active" and (command_id is not None or previous["showing_story"]),
            result=result, message="Loaded the native story checkpoint.", command_id=command_id)
        self.completion_released = False
        self._marker("restored")

    def prepare_completion(self, value):
        self._native_thread()
        self.renpy.store._app_recipe_state = saved_state("completed", value)
        self.completion_released = False

    def finish_completion(self):
        self._native_thread()
        if self.completion_released:
            return
        state = validate_state(self.renpy.store._app_recipe_state)
        if state["phase"] != "completed":
            return
        try:
            saved_available = self.checkpoint_available()
        except Exception:
            logging.exception("Completed app story checkpoint could not be checked")
            saved_available = False
        published = self.session.complete(self.revision, state["value"], saved_available=saved_available)
        status = self.session.status()
        already_restored = (status["revision"] == self.revision and status["phase"] == "completed"
                            and status.get("result") == {"story_id": STORY_ID, "outcome": "completed",
                                                          "value": state["value"]})
        if published or already_restored:
            # A manual bookmark remains a deliberate way back to its saved
            # interaction, just as it does in the story-first sample.
            try:
                available = self.renpy.can_load(SAVE_SLOT)
                message = ("Story complete. Your manual bookmark is kept." if available
                           else "Story complete. Start again when you're ready.")
            except Exception:
                logging.exception("Completed app story bookmark could not be checked")
                available = self.bridge.save_status()["available"]
                message = "Story complete. Could not check the manual bookmark."
            self.bridge.update_save_status(available, message)
            self._marker("completed" if published else "completion_wait_released")
            self.completion_released = True
            self.renpy.end_interaction(True)


def bind(renpy, session, bridge, story, poll_choice=None):
    global native
    native = NativeStory(renpy, session, bridge, story, poll_choice)
    return native
