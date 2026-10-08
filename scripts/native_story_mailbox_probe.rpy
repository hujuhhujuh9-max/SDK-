# Only copied into verifier-created projects; never included in the recipe.
init 1 python:
    sdk_native_story_install_profile(auto_recover=True)

init 2 python:
    import native_story_mailbox_check
    native_story_mailbox_check.setup()
    config.overlay_screens.append("sdk_native_story_mailbox_check")
    config.default_fullscreen = True

screen sdk_native_story_mailbox_check():
    timer 0.12 repeat True action Function(native_story_mailbox_check.tick, _update_screens=False)
