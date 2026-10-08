# Optional standalone app host. Do not copy this over the runner's start label.
define config.name = "Native story lifecycle recipe"
define config.main_menu = False
define config.screen_width = 720
define config.screen_height = 1280
define config.default_text_cps = 0

default sdk_native_story_last_result = None

init 1 python:
    sdk_native_story_install_profile()

screen sdk_native_story_home():
    add Solid("#101b2b")
    vbox:
        xalign 0.5
        yalign 0.5
        xsize 620
        spacing 24
        text "The last lantern" size 42 color "#f4f0e8"
        text "A callable native story" size 26 color "#b9d7de"
        textbutton "Start" action Return("start")
        textbutton "Resume live story" action Return("resume") sensitive sdk_native_story_can_resume()
        textbutton "Load checkpoint" action Function(sdk_native_story_load_checkpoint) sensitive sdk_native_story_owns_slot(SDK_NATIVE_STORY_SLOT)
        textbutton "Close recipe" action Quit(confirm=False)
        if sdk_native_story_last_result is not None:
            text ("Last result: " + sdk_native_story_last_result["status"]) size 24 color "#b9d7de"
        text sdk_native_story_message size 20 color "#b9c5d0"

label start:
    while True:
        $ renpy.checkpoint()
        $ renpy.retain_after_load()
        call screen sdk_native_story_home
        call sdk_native_story(_return)
        $ sdk_native_story_last_result = _return
