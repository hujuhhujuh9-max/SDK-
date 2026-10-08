"""Native-thread adapter for A's confirmed story mailbox.

Keep the instance in this Python module, outside Ren'Py's saveable store. The
native host passes plain status; this module never imports Ren'Py or reads saves.
"""

import threading

runtime = None


class NativeStoryMailbox:
    def __init__(self, bridge, story_id):
        self.bridge = bridge
        self.story_id = story_id
        self.owner = threading.get_ident()
        self.pending = None
        self.session_id = None
        self.run_id = None
        self.return_route = "/app"
        self.last_gate = None
        self.finished_session = None

    def _native_thread(self):
        if threading.get_ident() != self.owner:
            raise RuntimeError("Story mailbox must run on the native story thread")

    def restore(self, status):
        """Recovery replaces process IDs, without routing or replaying results."""
        self._native_thread()
        self.pending = None
        self.return_route = self.bridge.story_status()["return_route"]
        state = {"running": "active", "returned": "suspended", "completed": "completed"}.get(status["status"])
        self.session_id = self.bridge.restore_story_status(
            self.story_id if state else None, state=state or "suspended",
            return_route=self.return_route)
        self.run_id = status["run_id"] if state else None
        self.finished_session = self.session_id if state == "completed" else None

    def _reject(self, command, message):
        self.bridge.confirm_story_command(command["request_id"], success=False, message=message)

    def take(self, status, *, scene_shown):
        """Return a native interaction result only when actual flow must change."""
        self._native_thread()
        if self.pending is not None:
            return None
        command = self.bridge.take_story_command()
        if command is None:
            return None
        action = command["action"]
        if command["story_id"] != self.story_id:
            self._reject(command, "This host runs The Last Lantern.")
            return None
        if action == "start":
            valid = status["status"] in ("unavailable", "completed") and not scene_shown
        else:
            valid = (command["session_id"] == self.session_id and status["run_id"] == self.run_id
                     and (status["status"] == "returned" if action == "resume" and not scene_shown
                          else status["status"] == "running" and scene_shown))
        if not valid:
            self._reject(command, "That live story is no longer available. Reload story status.")
            return None
        if action == "resume" and status["status"] == "running":
            # The original native interaction is still alive behind an app page.
            # Confirm visibility, without reentering its label or reading a save.
            if self.bridge.confirm_story_command(command["request_id"], success=True):
                self.return_route = command["return_route"]
            return None
        self.pending = command
        return action

    def entered(self, status):
        """Confirm Start/Resume after the matching native scene exists."""
        self._native_thread()
        command = self.pending
        if command is None or command["action"] not in ("start", "resume") or status["status"] != "running":
            return False
        if command["action"] == "resume" and status["run_id"] != self.run_id:
            self._reject(command, "The live story changed before Resume.")
            self.pending = None
            return False
        self.pending = None
        if not self.bridge.confirm_story_command(command["request_id"], success=True):
            return False
        self.session_id, self.run_id = command["session_id"], status["run_id"]
        self.finished_session = None
        self.return_route = command["return_route"]
        return True

    def prepare_return(self):
        """Stage a native Return button through the same confirmed mailbox."""
        self._native_thread()
        request = self.bridge.request_story("return", self.story_id, return_route=self.return_route)
        if request is None:
            return False
        self.pending = self.bridge.take_story_command()
        return self.pending is not None and self.pending["request_id"] == request

    def handoff(self, status):
        """Confirm Return after its caller resumes; complete a session once."""
        self._native_thread()
        command, self.pending = self.pending, None
        if status["status"] == "completed" and status["run_id"] == self.run_id:
            if self.finished_session == self.session_id:
                return False
            accepted = self.bridge.finish_story(self.session_id, result=dict(status))
            if accepted:
                self.finished_session = self.session_id
            return accepted
        if command is None:
            return False
        success = (command["action"] == "return" and status["status"] == "returned"
                   and status["run_id"] == self.run_id)
        return self.bridge.confirm_story_command(command["request_id"], success=success,
            message="Story returned. Resume continues this live progress." if success
                    else "Could not change the native story. Reload story status.")
