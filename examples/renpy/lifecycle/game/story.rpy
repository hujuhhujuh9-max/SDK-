# Copyable native story. Merely loading this file installs no entry point,
# save profile, callbacks, services or changes to the existing demo.
define SDK_NATIVE_STORY_ID = "lantern"
define SDK_NATIVE_STORY_PROFILE = "sdk-native-lantern-v1"
define SDK_NATIVE_STORY_SLOT = "sdk-native-lantern-checkpoint"

default sdk_native_story_state = None
default sdk_native_story_message = ""

init python:
    import logging
    import os
    import uuid

    _sdk_native_story_profile_installed = False
    _sdk_native_story_auto_recover = False

    def sdk_native_story_valid(state):
        if not isinstance(state, dict) or set(state) != {"story_id", "run_id", "status", "phase", "route"}:
            return False
        if state["story_id"] != SDK_NATIVE_STORY_ID or not isinstance(state["run_id"], str) or not state["run_id"]:
            return False
        status, phase, route = state["status"], state["phase"], state["route"]
        if status not in ("running", "returned", "completed"):
            return False
        if phase in ("arrival", "choice"):
            return status != "completed" and route is None
        if phase == "ending":
            return status != "completed" and route in ("garden", "tower")
        return phase == "done" and status == "completed" and route in ("garden", "tower")

    def sdk_native_story_status():
        """Plain data for an app shell; reading status never loads a save."""
        state = sdk_native_story_state
        if not sdk_native_story_valid(state):
            return {"story_id": SDK_NATIVE_STORY_ID, "status": "unavailable", "phase": None,
                    "run_id": None, "result": None}
        return {"story_id": state["story_id"], "status": state["status"], "phase": state["phase"],
                "run_id": state["run_id"], "result": state["route"] if state["status"] == "completed" else None}

    def sdk_native_story_can_resume():
        return sdk_native_story_valid(sdk_native_story_state) and sdk_native_story_state["status"] == "returned"

    def sdk_native_story_input_allowed():
        # An optional mailbox host replaces this during init. Check again in
        # each action: an event can arrive after its control was disabled.
        return True

    def sdk_native_story_prepare_return():
        # Optional hosts may stage their plain Return command before yielding.
        return True

    def sdk_native_story_choose(value):
        if not sdk_native_story_input_allowed():
            return False
        renpy.end_interaction(value)

    def sdk_native_story_save_from_scene():
        if not sdk_native_story_input_allowed():
            return False
        return sdk_native_story_save_checkpoint()

    def sdk_native_story_return():
        """Native-thread Return command for an app shell or a screen action."""
        if (not sdk_native_story_valid(sdk_native_story_state)
                or sdk_native_story_state["status"] != "running"
                or renpy.get_screen("sdk_native_story_scene") is None
                or not sdk_native_story_input_allowed()
                or not sdk_native_story_prepare_return()):
            return False
        renpy.end_interaction("return")

    def _sdk_native_story_metadata(data):
        # Native autosave can invoke this on a worker. Only immutable identity
        # crosses here: no renderer, Flet loop or service is read or serialized.
        data["sdk_native_story"] = {"profile": SDK_NATIVE_STORY_PROFILE,
                                    "story_id": SDK_NATIVE_STORY_ID, "schema": 1}

    def sdk_native_story_owns_slot(slot):
        if not _sdk_native_story_profile_installed or slot not in (SDK_NATIVE_STORY_SLOT, "_reload-1"):
            return False
        try:
            metadata = renpy.slot_json(slot)
            identity = metadata.get("sdk_native_story") if isinstance(metadata, dict) else None
            return (renpy.can_load(slot) and isinstance(metadata, dict)
                    and isinstance(identity, dict) and type(identity.get("schema")) is int
                    and identity == {"profile": SDK_NATIVE_STORY_PROFILE,
                                     "story_id": SDK_NATIVE_STORY_ID, "schema": 1})
        except Exception:
            return False

    def _sdk_native_story_clear_recovery():
        # Never delete a foreign/old/unrecognized profile's recovery archive.
        if sdk_native_story_owns_slot("_reload-1"):
            renpy.unlink_save("_reload-1")

    def _sdk_native_story_startup():
        # Save locations are initialized before start_callbacks, not during init.
        # An environment auto-load override otherwise bypasses config.auto_load.
        override = os.environ.get("RENPY_AUTO_LOAD")
        if override:
            if override not in (SDK_NATIVE_STORY_SLOT, "_reload-1") or not sdk_native_story_owns_slot(override):
                raise RuntimeError("RENPY_AUTO_LOAD must identify a checkpoint owned by the native story profile")
        config.auto_load = "_reload-1" if _sdk_native_story_auto_recover and sdk_native_story_owns_slot("_reload-1") else None

    def _sdk_native_story_after_load():
        global sdk_native_story_message
        if sdk_native_story_state is not None and not sdk_native_story_valid(sdk_native_story_state):
            raise ValueError("Invalid native story continuation")
        _sdk_native_story_clear_recovery()
        sdk_native_story_message = "Story restored."

    def sdk_native_story_install_profile(auto_recover=None):
        """Opt in once during init, after early save-profile selection.

        Copy profile.rpy into the optional project too: regular init is too late
        to select a directory before the engine's first persistent-data read.
        """
        global _sdk_native_story_profile_installed, _sdk_native_story_auto_recover
        if _sdk_native_story_profile_installed:
            return
        if not renpy.is_init_phase():
            raise RuntimeError("Install the native story profile during init")
        if config.save_directory != SDK_NATIVE_STORY_PROFILE:
            raise ValueError("Select the native story profile with profile.rpy before installing its callbacks")
        if renpy.android:
            expected = os.path.join(os.environ["ANDROID_PRIVATE"], "saves", SDK_NATIVE_STORY_PROFILE)
            if os.path.realpath(config.savedir) != os.path.realpath(expected):
                raise ValueError("Android native story saves require their app-private profile directory")
        _sdk_native_story_auto_recover = renpy.android if auto_recover is None else bool(auto_recover)
        config.auto_load = None
        config.save_json_callbacks.append(_sdk_native_story_metadata)
        config.start_callbacks.append(_sdk_native_story_startup)
        config.after_load_callbacks.append(_sdk_native_story_after_load)
        _sdk_native_story_profile_installed = True

    def sdk_native_story_save_checkpoint():
        global sdk_native_story_message
        if not _sdk_native_story_profile_installed or not sdk_native_story_valid(sdk_native_story_state):
            sdk_native_story_message = "No native story to save."
            return False
        try:
            renpy.take_screenshot()
            renpy.save(SDK_NATIVE_STORY_SLOT, extra_info="The lantern: " + sdk_native_story_state["phase"])
            sdk_native_story_message = "Checkpoint saved. Resume still continues your live story."
            return True
        except Exception:
            logging.exception("Native story checkpoint save failed")
            sdk_native_story_message = "Could not save the checkpoint. Please try again."
            return False

    def sdk_native_story_load_checkpoint():
        global sdk_native_story_message
        if not sdk_native_story_owns_slot(SDK_NATIVE_STORY_SLOT):
            sdk_native_story_message = "No compatible saved checkpoint."
            return False
        try:
            renpy.load(SDK_NATIVE_STORY_SLOT)
            # Successful native load transfers control, rather than returning.
            sdk_native_story_message = "Checkpoint load cancelled."
        except Exception:
            logging.exception("Native story checkpoint load failed")
            sdk_native_story_message = "Could not load the checkpoint. Your live story is kept."
        return False

screen sdk_native_story_scene(state):
    modal True
    zorder 100
    add Solid("#182635")
    vbox:
        xalign 0.5
        yalign 0.5
        xsize 620
        spacing 24
        text "THE LAST LANTERN" size 38 color "#f4f0e8"
        text "Keeper" size 26 color "#b9d7de"
        if state["phase"] == "arrival":
            text "One lantern is still burning. Will you carry it home before the rain?" size 32 color "#f4f0e8"
            textbutton "Continue" action Function(sdk_native_story_choose, "continue", _update_screens=False) sensitive sdk_native_story_input_allowed()
        elif state["phase"] == "choice":
            text "The garden path is sheltered. The tower path lets you see the harbor." size 32 color "#f4f0e8"
            textbutton "Take the garden path" action Function(sdk_native_story_choose, "garden", _update_screens=False) sensitive sdk_native_story_input_allowed()
            textbutton "Climb the tower" action Function(sdk_native_story_choose, "tower", _update_screens=False) sensitive sdk_native_story_input_allowed()
        else:
            if state["route"] == "garden":
                text "You bring the lantern through the garden. Its light reaches the waiting windows." size 32 color "#f4f0e8"
            else:
                text "From the tower, you lift the lantern. A light answers across the harbor." size 32 color "#f4f0e8"
            textbutton "Finish story" action Function(sdk_native_story_choose, "finish", _update_screens=False) sensitive sdk_native_story_input_allowed()
        textbutton "Save checkpoint" action Function(sdk_native_story_save_from_scene) sensitive sdk_native_story_input_allowed()
        textbutton "Return" action Function(sdk_native_story_return, _update_screens=False) sensitive sdk_native_story_input_allowed()
        text sdk_native_story_message size 20 color "#b9c5d0"
    key "game_menu" action Function(sdk_native_story_return, _update_screens=False)
    key "dismiss" action NullAction()

# Call in the normal top-level native story context, never call_in_new_context.
# Return preserves only plain continuation data. Resume never reads the disk.
label sdk_native_story(action="start"):
    if not _sdk_native_story_profile_installed:
        $ renpy.error("Install the isolated native story profile during init before calling this label.")
    if action not in ("start", "resume"):
        $ renpy.error("Use start or resume; load checkpoints with sdk_native_story_load_checkpoint().")
    if sdk_native_story_valid(sdk_native_story_state) and sdk_native_story_state["status"] == "running":
        return {"story_id": SDK_NATIVE_STORY_ID, "status": "busy", "phase": sdk_native_story_state["phase"], "run_id": sdk_native_story_state["run_id"], "result": None}
    if action == "start":
        $ _sdk_native_story_clear_recovery()
        $ sdk_native_story_state = {"story_id": SDK_NATIVE_STORY_ID, "run_id": str(uuid.uuid4()), "status": "running", "phase": "arrival", "route": None}
        $ sdk_native_story_message = ""
    elif sdk_native_story_can_resume():
        $ sdk_native_story_state["status"] = "running"
        $ sdk_native_story_message = "Continuing your live story."
    else:
        return {"story_id": SDK_NATIVE_STORY_ID, "status": "unavailable", "phase": None, "run_id": None, "result": None}

    # The modified engine needs a load point after the first initialization too.
    $ renpy.checkpoint()
    while sdk_native_story_state["status"] == "running":
        $ renpy.retain_after_load()
        call screen sdk_native_story_scene(sdk_native_story_state)
        if _return == "return":
            $ sdk_native_story_state["status"] = "returned"
            $ _sdk_native_story_clear_recovery()
        elif sdk_native_story_state["phase"] == "arrival" and _return == "continue":
            $ sdk_native_story_state["phase"] = "choice"
        elif sdk_native_story_state["phase"] == "choice" and _return in ("garden", "tower"):
            $ sdk_native_story_state["route"] = _return
            $ sdk_native_story_state["phase"] = "ending"
        elif sdk_native_story_state["phase"] == "ending" and _return == "finish":
            $ sdk_native_story_state["status"] = "completed"
            $ sdk_native_story_state["phase"] = "done"
            $ _sdk_native_story_clear_recovery()
        else:
            $ renpy.error("Invalid native story result")
        $ renpy.checkpoint()
    return sdk_native_story_status()
