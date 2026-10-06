"""Dialogue shared by Ren'Py's story thread and Flet's UI event loop.

Publish on the Ren'Py thread, select on the Flet thread, and consume the result
on the Ren'Py thread. This module never calls either renderer's APIs.
"""

import logging
import threading
from collections import deque
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Dialogue:
    revision: int
    speaker: str
    text: str
    choices: tuple[tuple[str, str], ...]
    selected: str | None = None


class Story:
    def __init__(self):
        self._lock = threading.Lock()
        self._revision = 0
        self._dialogue = None
        self._selection = None
        self._history = deque(maxlen=200)
        self._listeners = set()
        self._restart = False

    def _notify(self):
        with self._lock:
            listeners = tuple(self._listeners)
        for listener in listeners:
            try:
                listener()
            except Exception:
                logging.exception("RenFletPy dialogue listener failed")

    def subscribe(self, listener):
        with self._lock:
            self._listeners.add(listener)

        def detach():
            with self._lock:
                self._listeners.discard(listener)

        return detach

    def current(self):
        with self._lock:
            return self._dialogue

    def history(self):
        with self._lock:
            return tuple(self._history)

    def show(self, speaker, text, choices=(("continue", "Continue"),)):
        choices = tuple(tuple(choice) for choice in choices)
        if not isinstance(speaker, str) or not isinstance(text, str) or not text:
            raise ValueError("Dialogue requires a speaker string and nonempty text")
        if (not choices or any(len(choice) != 2 or not all(
                isinstance(value, str) and value for value in choice) for choice in choices)
                or len({choice[0] for choice in choices}) != len(choices)):
            raise ValueError("Choices require unique nonempty IDs and labels")
        with self._lock:
            self._revision += 1
            self._dialogue = Dialogue(self._revision, speaker, text, choices)
            self._history.append(self._dialogue)
            self._selection = None
            revision = self._revision
        self._notify()
        return revision

    def choose(self, revision, choice_id):
        with self._lock:
            dialogue = self._dialogue
            if (self._restart or dialogue is None or dialogue.revision != revision
                    or dialogue.selected is not None
                    or choice_id not in dict(dialogue.choices)):
                return False
            self._dialogue = replace(dialogue, selected=choice_id)
            self._history[-1] = self._dialogue
            self._selection = (revision, choice_id)
        self._notify()
        return True

    def consume(self, revision):
        with self._lock:
            if self._selection is None or self._selection[0] != revision:
                return None
            _, choice_id = self._selection
            self._selection = None
            return choice_id

    def request_restart(self):
        with self._lock:
            self._restart = True

    def restarting(self):
        with self._lock:
            return self._restart

    def reset(self):
        with self._lock:
            # Never recycle a revision: delayed events from before a replay
            # must not select a choice in the new story.
            self._revision += 1
            self._dialogue = None
            self._selection = None
            self._history.clear()
            self._restart = False
        self._notify()


story = Story()
