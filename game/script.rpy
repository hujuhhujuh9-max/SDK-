define config.name = "Before the First Light"
define config.version = "0.1.0"
define config.main_menu = False
define config.save_directory = "sdk-runner-integration"
define config.screen_width = 720
define config.screen_height = 1280
define config.default_text_cps = 0
define mira = Character("Mira", color="#b9d7de")

init python:
    import os
    import logging
    import sdk_bridge
    from renfletpy import story
    _last_count = -1
    _last_presentation = None
    _save_initialized = False
    RENFLETPY_SAVE_SLOT = "renfletpy-quick"

    def process_save_request():
        global _save_initialized, _renfletpy_saved_state
        if not _save_initialized:
            available = renpy.can_load(RENFLETPY_SAVE_SLOT)
            sdk_bridge.initialize_save_status(available)
            _save_initialized = True
        action = sdk_bridge.take_save_request()
        if action is None:
            return
        try:
            if action == "save":
                _renfletpy_saved_state = story.snapshot()
                # Loading normally rolls store data back to the start of this
                # interaction. Keep the exact puzzle snapshot taken at save time.
                renpy.retain_after_load()
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
        global _interlude_revision
        _interlude_revision = story.restore(_renfletpy_saved_state)
        renpy.block_rollback()
        sdk_bridge.update_save_status(renpy.can_load(RENFLETPY_SAVE_SLOT), "Loaded saved game.")
        sdk_bridge.resume_story()
        current = story.current()
        print("SDK_RUNNER_SAVE action=loaded kind=%s progress=%s pid=%s" %
              (current.kind if current is not None else "scene",
               len(current.progress) if current is not None else 0, os.getpid()), flush=True)

    def refresh_shared_state():
        global _last_count, _last_presentation
        if sdk_bridge.quitting():
            renpy.quit()
        if story.restarting():
            story.reset()
            renpy.full_restart()
        process_save_request()
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
        revision = _interlude_revision
        selected = story.consume(revision)
        if selected is not None:
            print("SDK_RUNNER_INTERLUDE_RESULT revision=%s result=%s pid=%s" %
                  (revision, selected, os.getpid()), flush=True)
            story.close(revision)
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
default _renfletpy_saved_state = None
default _interlude_revision = None

# Call an interlude only where the story needs one, then use _return normally.
label renfletpy_minigame(kind):
    $ renpy.block_rollback()
    $ _interlude_revision = story.minigame(kind)
    call screen renfletpy_input
    $ _interlude_revision = None
    $ renpy.block_rollback()
    return _return

label renfletpy_panel(title, text, choices=(("continue", "Continue"),)):
    $ renpy.block_rollback()
    $ _interlude_revision = story.show(title, text, choices)
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

    $ scene_marker("first_light")
    mira "The first light reaches the observatory. Next time, we should come earlier."
    jump start
