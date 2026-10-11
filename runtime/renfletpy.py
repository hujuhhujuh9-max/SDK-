"""Optional interludes shared by Ren'Py's story thread and Flet's UI event loop.

Publish on the Ren'Py thread, select on the Flet thread, and consume the result
on the Ren'Py thread. This module never calls either renderer's APIs.
"""

import logging
import re
import threading
from collections import deque
from dataclasses import asdict, dataclass, replace

if __package__:
    from .story_activities import ActivityResult, activities, plain_copy
    from .tactics import PLAYER, TacticsState, TacticsView
else:
    from story_activities import ActivityResult, activities, plain_copy
    from tactics import PLAYER, TacticsState, TacticsView


@dataclass(frozen=True)
class Interlude:
    revision: int
    speaker: str
    text: str
    choices: tuple[tuple[str, str], ...]
    selected: str | None = None
    kind: str = "panel"
    progress: tuple[str, ...] = ()
    feedback: str = ""
    positions: tuple[tuple[str, int, int, int], ...] = ()
    selected_unit: str | None = None
    view: TacticsView | None = None
    activity: dict | None = None


STAR_ORDER = (("deneb", "Deneb"), ("vega", "Vega"), ("altair", "Altair"))


class Story:
    def __init__(self, registry=activities):
        self._lock = threading.Lock()
        self._revision = 0
        self._dialogue = None
        self._selection = None
        self._history = deque(maxlen=200)
        self._listeners = set()
        self._restart = False
        self.activities = registry
        self._activity_commands = deque()
        self._activity_terminal_pending = False
        self._activity_owner = None

    @staticmethod
    def _copy(interlude):
        if interlude is not None and interlude.activity is not None:
            return replace(interlude, activity=plain_copy(interlude.activity))
        return interlude

    def _require_activity_owner(self, *, bind=False):
        thread = threading.current_thread()
        if self._activity_owner is None and bind:
            self._activity_owner = thread
        if self._activity_owner is not thread:
            raise RuntimeError("Activity commands and native results belong to the story owner thread")

    def _notify(self):
        with self._lock:
            listeners = tuple(self._listeners)
        for listener in listeners:
            try:
                listener()
            except Exception:
                logging.exception("RenFletPy interlude listener failed")

    def subscribe(self, listener):
        with self._lock:
            self._listeners.add(listener)

        def detach():
            with self._lock:
                self._listeners.discard(listener)

        return detach

    def current(self):
        with self._lock:
            return self._copy(self._dialogue)

    def history(self):
        with self._lock:
            return tuple(self._copy(entry) for entry in self._history)

    def snapshot(self):
        """Return plain save data, with no locks, listeners or live event IDs."""
        # Native manual/mobile serialization may immediately follow a UI input.
        # Autosave serializers on other threads capture committed data without
        # running reducers or native operations outside the story owner.
        if self._activity_owner is threading.current_thread():
            self.process_activity_commands()
        with self._lock:
            entries = []
            for interlude in self._history:
                entry = asdict(interlude)
                del entry["revision"]
                entries.append(entry)
            return {"version": 1, "active": self._dialogue is not None, "history": entries}

    def restore(self, snapshot):
        """Restore a save and issue fresh revisions so old controls cannot act."""
        if (not isinstance(snapshot, dict) or snapshot.get("version") != 1
                or type(snapshot.get("active")) is not bool
                or not isinstance(snapshot.get("history"), (list, tuple))
                or len(snapshot["history"]) > 200
                or (snapshot["active"] and not snapshot["history"])):
            raise ValueError("Invalid or unsupported RenFletPy save")
        # Validate everything before replacing the current story.
        entries = []
        for entry in snapshot["history"]:
            try:
                interlude = Interlude(**entry, revision=0)
                choices = tuple(tuple(choice) for choice in interlude.choices)
                progress = tuple(interlude.progress)
                positions = tuple(tuple(position) for position in interlude.positions)
                self._validate(interlude.speaker, interlude.text, choices, interlude.kind)
                if (not isinstance(interlude.feedback, str)
                        or (interlude.selected is not None and interlude.selected not in dict(choices))
                        or (interlude.kind != "star_map" and progress)
                        or (interlude.kind != "tactics" and (positions or interlude.selected_unit is not None
                                                            or interlude.view is not None))
                        or (interlude.kind == "star_map" and (
                            progress != tuple(star[0] for star in STAR_ORDER[:len(progress)])
                            or len(progress) > len(STAR_ORDER)
                            or (interlude.selected == "aligned") != (len(progress) == len(STAR_ORDER))))):
                    raise ValueError("Invalid interlude state")
                if interlude.kind == "tactics":
                    state = TacticsState.from_positions(positions, interlude.selected_unit)
                    view = TacticsView.from_snapshot(interlude.view)
                    if (interlude.selected == "reached") != state.goal_reached:
                        raise ValueError("Invalid tactics result")
                else:
                    view = None
                if self.activities.contains(interlude.kind):
                    activity = self.activities.get(interlude.kind).restore(interlude.activity)
                    result = activity["result"]
                    if (set(dict(choices)) != {"completed", "cancelled"}
                            or (result is None) != (interlude.selected is None)
                            or (result is not None and interlude.selected != result["status"])):
                        raise ValueError("Invalid activity result selection")
                elif interlude.activity is not None:
                    raise ValueError("Built-in interludes cannot contain project activity data")
                else:
                    activity = None
                entries.append(replace(interlude, choices=choices, progress=progress, positions=positions,
                                       view=view, activity=activity))
            except (TypeError, KeyError) as error:
                raise ValueError("Invalid interlude save") from error
        if any(entry.activity is not None for entry in entries):
            self._require_activity_owner(bind=True)
        with self._lock:
            self._revision += 1
            self._history.clear()
            for interlude in entries:
                self._revision += 1
                self._history.append(replace(interlude, revision=self._revision))
            self._dialogue = self._history[-1] if snapshot["active"] else None
            if self._dialogue is not None and self._dialogue.selected is not None:
                result = (ActivityResult.from_snapshot(self._dialogue.activity["result"])
                          if self._dialogue.activity is not None else self._dialogue.selected)
                self._selection = (self._dialogue.revision, result)
            else:
                self._selection = None
            self._restart = False
            self._activity_commands.clear()
            self._activity_terminal_pending = False
            revision = self._dialogue.revision if self._dialogue is not None else None
        self._notify()
        return revision

    def show(self, speaker, text, choices=(("continue", "Continue"),), *, kind="panel"):
        if self.activities.contains(kind):
            return self.start_activity(kind, speaker=speaker, text=text)
        choices = tuple(tuple(choice) for choice in choices)
        self._validate(speaker, text, choices, kind)
        with self._lock:
            self._revision += 1
            state = TacticsState() if kind == "tactics" else None
            self._dialogue = Interlude(self._revision, speaker, text, choices, kind=kind,
                                      positions=state.positions() if state else (),
                                      selected_unit="scout" if state else None,
                                      view=TacticsView() if state else None)
            self._history.append(self._dialogue)
            self._selection = None
            self._activity_commands.clear()
            self._activity_terminal_pending = False
            revision = self._revision
        self._notify()
        return revision

    def _validate(self, speaker, text, choices, kind):
        if kind not in ("panel", "star_map", "tactics") and not self.activities.contains(kind):
            raise ValueError("Unknown interlude kind")
        if not isinstance(speaker, str) or not isinstance(text, str) or not text:
            raise ValueError("Dialogue requires a speaker string and nonempty text")
        if (not choices or any(len(choice) != 2 or not all(
                isinstance(value, str) and value for value in choice) for choice in choices)
                or len({choice[0] for choice in choices}) != len(choices)):
            raise ValueError("Choices require unique nonempty IDs and labels")
        if kind == "tactics" and {choice[0] for choice in choices} != {"reached", "skipped"}:
            raise ValueError("Tactics requires reached/skipped results")

    def minigame(self, kind):
        if self.activities.contains(kind):
            return self.start_activity(kind)
        if kind == "tactics":
            return self.show("Balcony route", "Guide the teal Scout to the gold balcony tile.",
                             (("reached", "Scout reached the balcony"), ("skipped", "Route skipped")),
                             kind=kind)
        if kind != "star_map":
            raise ValueError("Unknown minigame")
        return self.show("Star map", "Connect the summer triangle: Deneb → Vega → Altair.",
                         (("aligned", "Constellation aligned"), ("skipped", "Skip minigame")),
                         kind=kind)

    def start_activity(self, kind, state=None, *, speaker=None, text=None):
        """Start a registered project activity on the native story owner thread."""
        self._require_activity_owner(bind=True)
        definition = self.activities.get(kind)
        data = {"version": definition.version, "state": definition.initial(state), "result": None}
        speaker = definition.title or kind if speaker is None else speaker
        text = definition.description or "Complete this activity or return to the story." if text is None else text
        choices = (("completed", "Activity completed"), ("cancelled", "Activity cancelled"))
        self._validate(speaker, text, choices, kind)
        with self._lock:
            self._revision += 1
            self._dialogue = Interlude(self._revision, speaker, text, choices, kind=kind, activity=data)
            self._history.append(self._dialogue)
            self._selection = None
            self._activity_commands.clear()
            self._activity_terminal_pending = False
            revision = self._revision
        self._notify()
        return revision

    def _queue_activity(self, revision, operation, name, payload):
        payload = plain_copy(payload)
        with self._lock:
            current = self._dialogue
            if (type(revision) is not int or self._restart or current is None or current.revision != revision
                    or current.activity is None or current.selected is not None
                    or self._activity_terminal_pending or len(self._activity_commands) >= 256):
                return False
            self._activity_commands.append((revision, operation, name, payload))
            if operation != "command":
                self._activity_terminal_pending = True
        return True

    def activity_command(self, revision, name, payload=None):
        """Accept detached UI data; native polling applies it in submission order."""
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,95}", name):
            raise ValueError("Activity commands require nonempty project IDs")
        return self._queue_activity(revision, "command", name, payload)

    def complete_activity(self, revision, value=None):
        return self._queue_activity(revision, "result", "completed", value)

    def cancel_activity(self, revision, value=None):
        return self._queue_activity(revision, "result", "cancelled", value)

    def process_activity_commands(self, revision=None):
        """Drain on Ren'Py's thread. Reducer errors keep the last valid model."""
        with self._lock:
            game = self._dialogue
            if game is None or game.activity is None or (revision is not None and game.revision != revision):
                return 0
        self._require_activity_owner()
        applied = 0
        # Bound each drain so a producer cannot starve the native story loop.
        for _ in range(256):
            with self._lock:
                if not self._activity_commands:
                    break
                target, operation, name, payload = self._activity_commands.popleft()
                game = self._dialogue
                if (self._restart or game is None or game.revision != target
                        or game.activity is None or game.selected is not None):
                    continue
                data = plain_copy(game.activity)
            try:
                definition = self.activities.get(game.kind)
                if operation == "command":
                    updated = definition.transition(data["state"], name, payload)
                else:
                    updated = {**data, "result": definition.result(ActivityResult(name, payload)).snapshot()}
                feedback = ""
            except Exception:
                logging.exception("RenFletPy activity %s command %s failed", game.kind, name)
                updated, feedback = data, "Activity input could not be applied. Please try again."
            with self._lock:
                current = self._dialogue
                if (self._restart or current is None or current.revision != target
                        or current.selected is not None):
                    continue
                result = updated["result"]
                selected = None if result is None else result["status"]
                self._dialogue = replace(current, activity=updated, selected=selected, feedback=feedback)
                self._history[-1] = self._dialogue
                if result is not None:
                    self._selection = (target, ActivityResult.from_snapshot(result))
                    self._activity_commands.clear()
                if operation != "command" or result is not None:
                    self._activity_terminal_pending = False
                applied += 1
            self._notify()
        return applied

    def tactics_state(self):
        """Give the native renderer a private copy, never the live save state."""
        with self._lock:
            game = self._dialogue
            if game is None or game.kind != "tactics":
                return None
            return TacticsState.from_positions(game.positions, game.selected_unit)

    def tactics_view(self):
        with self._lock:
            game = self._dialogue
            return game.view if game is not None and game.kind == "tactics" else None

    def set_tactics_view(self, revision, **changes):
        """Change only viewing settings; movement and result remain untouched."""
        with self._lock:
            game = self._dialogue
            if (self._restart or game is None or game.kind != "tactics"
                    or game.revision != revision or game.selected is not None):
                return False
            try:
                view = replace(game.view, **changes)
            except (TypeError, ValueError):
                return False
            if view == game.view:
                return False
            self._dialogue = replace(game, view=view)
            self._history[-1] = self._dialogue
        self._notify()
        return True

    def _edit_tactics(self, revision, edit):
        with self._lock:
            game = self._dialogue
            if (self._restart or game is None or game.kind != "tactics"
                    or game.revision != revision or game.selected is not None):
                return False
            state = TacticsState.from_positions(game.positions, game.selected_unit)
            if not edit(state):
                return False
            selected = "reached" if state.goal_reached else None
            self._dialogue = replace(game, positions=state.positions(), selected_unit=state.selected_uid,
                                     selected=selected)
            self._history[-1] = self._dialogue
            if selected is not None:
                self._selection = (revision, selected)
        self._notify()
        return True

    def select_tactics_unit(self, revision, uid):
        def select(state):
            unit = next((u for u in state.units if u.uid == uid and u.team == PLAYER), None)
            if unit is None or state.selected_uid == uid:
                return False
            state.select(unit)
            return True
        return self._edit_tactics(revision, select)

    def move_tactics_unit(self, revision, destination):
        return self._edit_tactics(revision, lambda state: state.move_selected(destination))

    def reset_tactics(self, revision):
        def reset(state):
            state.reset()
            state.selected_uid = "scout"
            return True
        return self._edit_tactics(revision, reset)

    def tap_star(self, revision, star_id):
        with self._lock:
            game = self._dialogue
            if (self._restart or game is None or game.revision != revision
                    or game.kind != "star_map" or game.selected is not None
                    or star_id not in dict(STAR_ORDER) or star_id in game.progress):
                return False
            if star_id != STAR_ORDER[len(game.progress)][0]:
                self._dialogue = replace(game, progress=(), feedback="Start with Deneb. Try again.")
            else:
                progress = game.progress + (star_id,)
                complete = len(progress) == len(STAR_ORDER)
                self._dialogue = replace(game, progress=progress,
                    feedback="Constellation aligned." if complete else "Keep following the triangle.",
                    selected="aligned" if complete else None)
                if complete:
                    self._selection = (revision, "aligned")
            self._history[-1] = self._dialogue
        self._notify()
        return True

    def choose(self, revision, choice_id):
        with self._lock:
            dialogue = self._dialogue
            if (self._restart or dialogue is None or dialogue.revision != revision
                    or dialogue.selected is not None
                    or dialogue.activity is not None
                    or choice_id not in dict(dialogue.choices)
                    or (dialogue.kind in ("star_map", "tactics") and choice_id != "skipped")):
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
            if self._dialogue is not None and self._dialogue.activity is not None:
                self._require_activity_owner()
            _, choice_id = self._selection
            self._selection = None
            return (ActivityResult.from_snapshot(choice_id.snapshot())
                    if isinstance(choice_id, ActivityResult) else choice_id)

    def close(self, revision):
        """Return input to Ren'Py without clearing the completed interlude history."""
        with self._lock:
            if self._dialogue is None or self._dialogue.revision != revision:
                return False
            self._dialogue = None
            self._selection = None
            self._activity_commands.clear()
            self._activity_terminal_pending = False
        self._notify()
        return True

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
            self._activity_commands.clear()
            self._activity_terminal_pending = False
        self._notify()


story = Story()


class SaveState:
    """Capture the live interlude whenever Ren'Py serializes its store.

    Keep one instance in a Ren'Py ``default`` variable. Native manual saves,
    autosaves and Android background saves all pickle it. Deserialization only
    holds data; the after-load callback restores the live model on Ren'Py's
    thread, after the native story context has been restored.
    """

    def __init__(self):
        self.data = None

    def __getstate__(self):
        return story.snapshot()

    def __setstate__(self, data):
        self.data = data
