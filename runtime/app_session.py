"""Plain, thread-safe handoff for the optional single-story app starter.

This module owns neither a Ren'Py context nor a Flet page. Native code retains
the actual interaction/save; this mailbox carries commands and published status.
"""

import copy
import json
import logging
import threading

STORY_ID = "app-recipe"


def app_mode():
    try:
        if __package__:
            from .project_config import STARTUP_TEMPLATE
        else:
            from project_config import STARTUP_TEMPLATE
    except ModuleNotFoundError as error:
        expected = (__package__ + "." if __package__ else "") + "project_config"
        if error.name != expected:
            raise
        return False
    return STARTUP_TEMPLATE == "app"


class AppSession:
    def __init__(self, *, enabled=lambda: True):
        # The bridge uses this same lock for save/reading commands, making their
        # busy checks and this mailbox's acceptance one atomic operation.
        self.operation_lock = threading.RLock()
        self._enabled = enabled
        self._gate = lambda: False
        self._revision = 0
        self._serial = 0
        self._command = None
        self._taken = False
        self._phase = "ready"
        self._resume_kind = "unavailable"
        self._showing_story = False
        self._message = "Ready to start a story."
        self._result = None
        self._event = "initialized"
        self._action = None
        self._command_id = None
        self._listeners = set()

    def bind_gate(self, blocked):
        """Bind the bridge's save/reading/quit gate under operation_lock."""
        with self.operation_lock:
            self._gate = blocked

    def _status(self):
        return {"app_mode": bool(self._enabled()), "story_id": STORY_ID,
                "revision": self._revision, "phase": self._phase,
                "busy": self._command is not None or bool(self._gate()),
                "resume_available": self._resume_kind != "unavailable",
                "resume_kind": self._resume_kind, "showing_story": self._showing_story,
                "message": self._message, "result": copy.deepcopy(self._result),
                "event": self._event, "action": self._action,
                "command_id": self._command_id}

    def status(self):
        with self.operation_lock:
            return self._status()

    def subscribe(self, callback):
        with self.operation_lock:
            self._listeners.add(callback)

        def detach():
            with self.operation_lock:
                self._listeners.discard(callback)
        return detach

    def _notification(self):
        return self._status(), tuple(self._listeners)

    @staticmethod
    def _notify(notification):
        status, listeners = notification
        for callback in listeners:
            try:
                callback(copy.deepcopy(status))
            except Exception:
                logging.exception("App session status listener failed")

    def request(self, action, revision, *, replace=False):
        if action not in ("start", "resume", "return"):
            raise ValueError("Unknown app story action")
        with self.operation_lock:
            if (not self._enabled() or type(revision) is not int
                    or revision != self._revision or self._command is not None or self._gate()):
                return False
            if action == "start":
                if self._resume_kind != "unavailable" and replace is not True:
                    return False
            elif action == "resume":
                if self._resume_kind == "unavailable":
                    return False
            elif self._phase != "active" or not self._showing_story:
                return False
            self._serial += 1
            self._command = {"story_id": STORY_ID, "revision": revision,
                             "action": action, "command_id": self._serial,
                             "replace": replace is True}
            self._taken = False
            self._event, self._action, self._command_id = "requested", action, self._serial
            self._message = {"start": "Starting story…", "resume": "Resuming story…",
                             "return": "Returning to app…"}[action]
            notification = self._notification()
        self._notify(notification)
        return True

    def take_request(self):
        notification = None
        with self.operation_lock:
            if self._command is None or self._taken or self._gate():
                return None
            # Initial native slot discovery may finish after an early Start
            # click. Preserve its command until consumption, but never silently
            # replace the newly discovered checkpoint without confirmation.
            if (self._command["action"] == "start" and self._resume_kind != "unavailable"
                    and not self._command["replace"]):
                self._command = None
                self._event = "failed"
                self._message = "A saved story is available. Confirm Start again to replace it."
                notification = self._notification()
                command = None
            else:
                self._taken = True
                command = dict(self._command)
        if notification is not None:
            self._notify(notification)
        return command

    def finish(self, command_id, *, success=True, message=None):
        with self.operation_lock:
            command = self._command
            if (type(command_id) is not int or command is None or not self._taken or command["command_id"] != command_id
                    or command["revision"] != self._revision):
                return False
            action = command["action"]
            self._command = None
            self._taken = False
            self._event = "finished" if success else "failed"
            if success:
                if action == "start":
                    self._revision += 1
                    self._result = None
                self._phase = "active"
                self._resume_kind = "live"
                self._showing_story = action != "return"
            self._message = message or ({"start": "Story started.", "resume": "Story resumed.",
                "return": "Your live story is kept. Quick save keeps a place on disk."}[action]
                if success else "Could not " + action + " the story. Please try again.")
            notification = self._notification()
        self._notify(notification)
        return True

    def initialize_saved(self, available):
        """Discover a native checkpoint without cancelling an early command."""
        with self.operation_lock:
            if self._phase != "ready":
                return False
            kind = "saved" if available else "unavailable"
            if self._resume_kind == kind:
                return False
            self._resume_kind = kind
            if self._command is None:
                self._event, self._action, self._command_id = "initialized", None, None
                self._message = "Saved story available." if available else "Ready to start a story."
            notification = self._notification()
        self._notify(notification)
        return True

    def complete(self, revision, value, *, saved_available=False):
        if type(saved_available) is not bool:
            raise ValueError("Saved checkpoint availability must be a plain bool")
        # Validate/copy at the boundary; never accept live native/service objects.
        value = json.loads(json.dumps(value, allow_nan=False))
        with self.operation_lock:
            if (type(revision) is not int or revision != self._revision or self._phase != "active"
                    or self._command is not None or self._gate() or not self._enabled()):
                return False
            self._phase, self._resume_kind, self._showing_story = (
                "completed", "saved" if saved_available else "unavailable", False)
            self._result = {"story_id": STORY_ID, "outcome": "completed", "value": value}
            self._event, self._action, self._command_id = "completed", None, None
            self._message = "Story completed."
            notification = self._notification()
        self._notify(notification)
        return True

    def restore(self, *, phase="active", resume_kind="live", showing_story=True,
                result=None, message=None, command_id=None):
        if phase not in ("ready", "active", "completed") or resume_kind not in ("live", "saved", "unavailable"):
            raise ValueError("Unknown app story restoration state")
        if ((phase == "active" and resume_kind != "live")
                or (phase != "active" and resume_kind == "live")):
            raise ValueError("Inconsistent app story restoration state")
        result = json.loads(json.dumps(result, allow_nan=False))
        with self.operation_lock:
            if command_id is not None:
                command = self._command
                if (type(command_id) is not int or command is None or not self._taken or command["action"] != "resume"
                        or command["command_id"] != command_id or command["revision"] != self._revision):
                    return None
            self._revision += 1
            self._command = None
            self._taken = False
            self._phase, self._resume_kind = phase, resume_kind
            self._showing_story = bool(showing_story) and phase == "active"
            self._result = result
            self._message = message or "Native story recovered."
            self._event = "finished" if command_id is not None else "restored"
            self._action = "resume" if command_id is not None else None
            self._command_id = command_id
            notification = self._notification()
            revision = self._revision
        self._notify(notification)
        return revision


session = AppSession(enabled=app_mode)
