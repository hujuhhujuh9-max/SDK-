# This recipe is enabled only by the build-selected application template.
# The observatory labels and their statement/save identities stay unchanged.
python early:
    import project_config
    if project_config.STARTUP_TEMPLATE == "app":
        import app_story
        app_story.configure_save_location(renpy)

init 1 python:
    print("SDK_RUNNER_NATIVE_SAVE_DIR path=%s pid=%s" % (config.savedir, os.getpid()), flush=True)
    if project_config.STARTUP_TEMPLATE == "app":
        import app_story
        import app_session
        app_story.bind(renpy, app_session.session, sdk_bridge, story, poll_story_choice)
        def poll_story_choice():
            app_story.native.poll_choice()
        config.label_overrides["start"] = "app_recipe_entry"
        RENFLETPY_SAVE_SLOT = app_story.SAVE_SLOT
        config.save_json_callbacks.append(app_story.native.save_metadata)
        config.after_load_callbacks.append(app_story.native.restore)
        layout.screen_yesno_prompt()

default _app_recipe_state = {"version": 1, "story_id": "app-recipe", "phase": "ready", "value": None}

# The starter has no legacy theme or GUI setup. Provide just the native screen
# used by the SDK's signature check, without registering it in story mode.
init 2:
    if project_config.STARTUP_TEMPLATE == "app":
        screen confirm(message, yes_action, no_action):
            modal True
            zorder 200
            add Solid("#101b2b")
            text _("Saved story confirmation"):
                xpos 60
                ypos 330
                xsize 600
                size 32
                color "#f4f0e8"
            text _(message):
                xpos 60
                ypos 410
                xsize 600
                size 28
                color "#b9c5d0"
            textbutton _("Yes"):
                xpos 100
                ypos 820
                xsize 220
                ysize 90
                background Solid("#42685e")
                hover_background Solid("#42685e")
                text_size 32
                text_color "#f4f0e8"
                text_xalign 0.5
                text_yalign 0.5
                action yes_action
            textbutton _("No"):
                xpos 400
                ypos 820
                xsize 220
                ysize 90
                background Solid("#294559")
                hover_background Solid("#294559")
                text_size 32
                text_color "#f4f0e8"
                text_xalign 0.5
                text_yalign 0.5
                action no_action
            key "game_menu" action no_action

screen app_recipe_commands():
    timer 0.1 repeat True action Function(app_story.native.poll, _update_screens=False)

screen app_recipe_home_wait():
    key "dismiss" action NullAction()

screen app_recipe_completion_wait():
    key "dismiss" action NullAction()
    timer 0.1 repeat True action Function(app_story.native.finish_completion, _update_screens=False)

label app_recipe_entry:
    $ scene_title = "The Lighthouse Note"
    $ scene_color = "#182635"
    show screen integration
    show screen app_recipe_commands
    $ app_story.native.enter_home()
    jump app_recipe_home

label app_recipe_home:
    $ renpy.checkpoint()
    call screen app_recipe_home_wait
    jump app_recipe_home

label app_recipe_start:
    $ scene_title = "The Lighthouse Note"
    $ scene_color = "#183c46"
    $ _history_list = []
    $ renpy.checkpoint()
    call app_recipe_story
    $ app_story.native.prepare_completion(_return)
    $ renpy.retain_after_load()
    call screen app_recipe_completion_wait
    jump app_recipe_home

# A normal callable native story: dialogue remains on SDL, the optional panel
# supplies a plain choice, and return supplies the application result.
label app_recipe_story:
    mira "Someone left a folded note at the lighthouse. The tide will be back before sunset."
    call renfletpy_panel("The folded note", "What will you do with the note?", (("keep", "Keep a copy"), ("share", "Share it with Mira")))
    if _return == "keep":
        mira "Then we will remember where the path began."
        return "You kept a note from the lighthouse."
    mira "Thank you. We can find our way back together."
    return "You shared the lighthouse note."
