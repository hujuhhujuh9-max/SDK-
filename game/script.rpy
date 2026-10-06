define config.name = "Before the First Light"
define config.version = "0.1.0"
define config.main_menu = False
define config.save_directory = "sdk-runner-integration"
define config.screen_width = 720
define config.screen_height = 1280

init python:
    import os
    import sdk_bridge
    from renfletpy import story
    _last_count = -1
    _last_presentation = None
    def refresh_shared_state():
        global _last_count, _last_presentation
        if sdk_bridge.quitting():
            renpy.quit()
        value = sdk_bridge.counter()
        mode = sdk_bridge.presentation()
        if value != _last_count or mode != _last_presentation:
            if value != _last_count:
                print("SDK_RUNNER_RENPY_COUNTER value=%s pid=%s" % (value, os.getpid()), flush=True)
            _last_count = value
            _last_presentation = mode
            renpy.restart_interaction()

    def poll_story_choice(revision):
        # Flet only submits data. Ren'Py actions always execute on this thread.
        if story.restarting():
            story.reset()
            renpy.full_restart()
        selected = story.consume(revision)
        if selected is not None:
            print("SDK_RUNNER_STORY_CHOICE revision=%s choice=%s pid=%s" %
                  (revision, selected, os.getpid()), flush=True)
            renpy.end_interaction(selected)
    config.quit_callbacks.append(sdk_bridge.stop)
    if renpy.android:
        sdk_bridge.start()

screen integration():
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
    timer 0.2 repeat True action Function(refresh_shared_state, _update_screens=False)

screen renfletpy_input(revision):
    # Android Back is owned by the shared menu, rather than a second game menu.
    key "game_menu" action NullAction()
    timer 0.1 repeat True action Function(poll_story_choice, revision, _update_screens=False)

default scene_color = "#182635"
default scene_title = "Before the First Light"

label renfletpy_say(speaker, text, choices=(("continue", "Continue"),)):
    $ _dialogue_revision = story.show(speaker, text, choices)
    call screen renfletpy_input(_dialogue_revision)
    return _return

label start:
    $ print("SDK_RUNNER_RENPY_READY pid=%s" % __import__("os").getpid(), flush=True)
    $ story.reset()
    $ scene_color = "#182635"
    $ scene_title = "Before the First Light"
    show screen integration

    call renfletpy_say("Mira", "You made it before sunrise. We have time for one last look before the observatory opens.", (("sky", "Look at the sky"), ("dome", "Enter the observatory")))
    if _return == "sky":
        $ scene_color = "#213b4a"
        $ scene_title = "A sky worth waiting for"
        call renfletpy_say("Mira", "There. That pale line above the hills. In a minute, the whole sky will change.")
    else:
        $ scene_color = "#302b45"
        $ scene_title = "Under the quiet dome"
        call renfletpy_say("Mira", "The telescope is still pointed at last night's stars. Let me show you where we were looking.")

    call renfletpy_say("Mira", "Next time, we should come earlier. There is always more to see.")
    call renfletpy_say("", "The first light reaches the observatory.", (("again", "Play again"),))
    jump start
