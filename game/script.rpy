define config.name = "Before the First Light"
define config.version = "0.1.0"
define config.main_menu = False
define config.save_directory = "sdk-runner-integration"
define config.screen_width = 720
define config.screen_height = 1280
define config.default_text_cps = 0
define config.history_length = 200
define config.auto_load = "_reload-1" if renpy.android else None
define mira = Character("Mira", color="#b9d7de")

init python:
    import os
    import logging
    import sdk_bridge
    from renfletpy import SaveState, story
    _last_count = -1
    _last_presentation = None
    _save_initialized = False
    RENFLETPY_SAVE_SLOT = "renfletpy-quick"

    def process_save_request():
        global _save_initialized
        if not _save_initialized:
            available = renpy.can_load(RENFLETPY_SAVE_SLOT)
            sdk_bridge.initialize_save_status(available)
            _save_initialized = True
        action = sdk_bridge.take_save_request()
        if action is None:
            return
        try:
            if action == "save":
                renpy.take_screenshot()
                renpy.save(RENFLETPY_SAVE_SLOT, extra_info=scene_title)
                sdk_bridge.update_save_status(True, "Saved. You can return here after closing the app.")
                current = story.current()
                print("SDK_RUNNER_SAVE action=saved progress=%s pid=%s" %
                      (len(current.progress) if current is not None else 0, os.getpid()), flush=True)
            elif renpy.can_load(RENFLETPY_SAVE_SLOT):
                renpy.load(RENFLETPY_SAVE_SLOT)
                # A successful load does not return. A declined save-signature
                # prompt can return, so release the menu's busy state in that case.
                sdk_bridge.update_save_status(True, "Load cancelled.")
            else:
                sdk_bridge.update_save_status(False, "No saved game yet.")
        except Exception:
            logging.exception("RenFletPy %s failed", action)
            sdk_bridge.update_save_status(renpy.can_load(RENFLETPY_SAVE_SLOT),
                                          "Could not %s. Please try again." % action)

    def restore_saved_interlude():
        global _interlude_revision, _renfletpy_saved_state
        saved = (_renfletpy_saved_state.data if isinstance(_renfletpy_saved_state, SaveState)
                 else _renfletpy_saved_state)
        if saved is None:
            # Older native background saves did not contain Flet progress.
            # A native scene is safe to resume; a missing interlude must replay.
            story.reset()
            if _interlude_revision is not None:
                renpy.unlink_save("_reload-1")
                sdk_bridge.update_save_status(renpy.can_load(RENFLETPY_SAVE_SLOT),
                                              "Restarting an older saved minigame.")
                renpy.full_restart()
            _interlude_revision = None
        else:
            _interlude_revision = story.restore(saved)
        # Upgrade the first quick-save format as well as missing old state.
        if not isinstance(_renfletpy_saved_state, SaveState):
            _renfletpy_saved_state = SaveState()
        renpy.block_rollback()
        # Recovery is temporary. A successful load establishes the new live
        # timeline; later launches must not reopen an older background snapshot.
        renpy.unlink_save("_reload-1")
        publish_story_history()
        sdk_bridge.update_save_status(renpy.can_load(RENFLETPY_SAVE_SLOT), "Loaded saved game.")
        sdk_bridge.resume_story()
        print("SDK_RUNNER_RENPY_READY pid=%s" % os.getpid(), flush=True)
        current = story.current()
        print("SDK_RUNNER_SAVE action=loaded kind=%s progress=%s pid=%s" %
              (current.kind if current is not None else "scene",
               len(current.progress) if current is not None else 0, os.getpid()), flush=True)

    def publish_story_history():
        entries = [(renpy.filter_text_tags(entry.who or "", allow=[]),
                    renpy.filter_text_tags(entry.what, allow=[]),
                    getattr(entry, "renfletpy_result", ""))
                   for entry in _history_list]
        current = story.current()
        if current is not None:
            entries.append((current.speaker, current.text,
                            dict(current.choices).get(current.selected, "")))
        sdk_bridge.publish_transcript(entries[-200:])

    def refresh_shared_state():
        global _last_count, _last_presentation
        if sdk_bridge.quitting():
            renpy.quit()
        if story.restarting():
            story.reset()
            renpy.full_restart()
        process_save_request()
        publish_story_history()
        value = sdk_bridge.counter()
        mode = sdk_bridge.presentation()
        if value != _last_count or mode != _last_presentation:
            if value != _last_count:
                print("SDK_RUNNER_RENPY_COUNTER value=%s pid=%s" % (value, os.getpid()), flush=True)
            _last_count = value
            _last_presentation = mode
            renpy.restart_interaction()

    def poll_story_choice():
        # Flet submits data. Flow and renderer APIs always run on Ren'Py's thread.
        if story.restarting():
            story.reset()
            renpy.full_restart()
        # A delayed Flet completion can arrive after a menu save/load click.
        # Keep this native waiting context until that command has completed.
        if sdk_bridge.save_status()["busy"]:
            return
        revision = _interlude_revision
        selected = story.consume(revision)
        if selected is not None:
            current = story.current()
            narrator.add_history("interlude", current.speaker, current.text,
                                 renfletpy_result=dict(current.choices)[selected])
            print("SDK_RUNNER_INTERLUDE_RESULT revision=%s result=%s pid=%s" %
                  (revision, selected, os.getpid()), flush=True)
            story.close(revision)
            publish_story_history()
            renpy.end_interaction(selected)

    def scene_marker(stage):
        print("SDK_RUNNER_SCENE stage=%s pid=%s" % (stage, os.getpid()), flush=True)

    config.quit_callbacks.append(sdk_bridge.stop)
    config.after_load_callbacks.append(restore_saved_interlude)
    if renpy.android:
        sdk_bridge.start()

screen integration():
    zorder -10
    if sdk_bridge.presentation() == "diagnostics":
        add Solid("#1b2838")
        vbox:
            align (0.5, 0.5)
            spacing 20
            text "Ready" size 50 xalign 0.5
            text "Count: [sdk_bridge.counter()]" size 40 xalign 0.5
    else:
        add Solid(scene_color)
        add Solid("#263e50"):
            yalign 0.65
            ysize 120
        vbox:
            xalign 0.5
            yalign 0.28
            spacing 16
            text "THE OBSERVATORY" size 20 color "#b9d7de" xalign 0.5
            text "[scene_title]" size 42 color "#f4f0e8" xalign 0.5
        textbutton "Menu":
            xalign 0.94
            ypos 32
            text_size 24
            text_color "#b9d7de"
            action Function(sdk_bridge.open_menu, _update_screens=False)
    key "game_menu" action Function(sdk_bridge.open_menu, _update_screens=False)
    timer 0.2 repeat True action Function(refresh_shared_state, _update_screens=False)

# Normal dialogue belongs to Ren'Py, including its interaction and history.
screen say(who, what):
    window:
        id "window"
        at Transform(alpha=0.0 if sdk_bridge.presentation() == "diagnostics" else 1.0)
        yalign 1.0
        xfill True
        ysize 330
        padding (40, 32)
        background Solid("#101b2bed")
        vbox:
            spacing 20
            if who:
                text who id "who" size 26 color "#b9d7de"
            text what id "what" size 32 color "#f4f0e8"
            text "Tap to continue" size 20 color "#b9c5d0"

screen renfletpy_input():
    key "dismiss" action NullAction()
    timer 0.1 repeat True action Function(poll_story_choice, _update_screens=False)

default scene_color = "#182635"
default scene_title = "Before the First Light"
default _renfletpy_saved_state = SaveState()
default _interlude_revision = None

# Call an interlude only where the story needs one, then use _return normally.
label renfletpy_minigame(kind):
    $ renpy.block_rollback()
    $ _interlude_revision = story.minigame(kind)
    $ renpy.retain_after_load()
    call screen renfletpy_input
    $ _interlude_revision = None
    $ renpy.block_rollback()
    return _return

label renfletpy_panel(title, text, choices=(("continue", "Continue"),)):
    $ renpy.block_rollback()
    $ _interlude_revision = story.show(title, text, choices)
    $ renpy.retain_after_load()
    call screen renfletpy_input
    $ _interlude_revision = None
    $ renpy.block_rollback()
    return _return

label start:
    $ print("SDK_RUNNER_RENPY_READY pid=%s" % os.getpid(), flush=True)
    $ story.reset()
    $ scene_color = "#182635"
    $ scene_title = "Before the First Light"
    show screen integration
    $ scene_marker("opening")

    mira "You made it before sunrise. Help me find the summer triangle before the stars disappear."
    call renfletpy_minigame("star_map")
    if _return == "aligned":
        $ scene_color = "#213b4a"
        $ scene_title = "A sky worth waiting for"
        $ scene_marker("aligned")
        mira "You found it. Deneb, Vega, Altair — one last constellation before the morning light."
    else:
        $ scene_color = "#302b45"
        $ scene_title = "Under the quiet dome"
        $ scene_marker("skipped")
        mira "We can leave the star map for another night. Come inside; I'll show you the telescope."

    call renfletpy_panel("Field journal", "What will you keep from this morning?", (("constellation", "The constellation"), ("company", "The company")))
    if _return == "constellation":
        $ scene_marker("journal_constellation")
        mira "I'll put the triangle in our journal. We can find it again next summer."
    else:
        $ scene_marker("journal_company")
        mira "Then let's make this our place to watch the sunrise."

    $ scene_marker("first_light")
    mira "The first light reaches the observatory. Next time, we should come earlier."
    $ scene_marker("ending")
    call renfletpy_panel("First light", "The night is over. Your morning stays in the story history.", (("replay", "Play again"), ("quit", "Close story")))
    if _return == "replay":
        $ renpy.full_restart()
    $ renpy.quit()
