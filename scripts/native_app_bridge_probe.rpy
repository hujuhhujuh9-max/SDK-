# Copied only into verifier-created optional projects.
init 0 python:
    SDK_NATIVE_STORY_PROFILE = "sdk-app-lantern-v1"
    sdk_native_story_install_profile(auto_recover=True)

init 2 python:
    if renpy.game.args.command == "run":
        import os
        import sys
        sys.path[:0] = os.environ["SDK_NATIVE_APP_PYTHON_PATH"].split(os.pathsep)
        import native_app_bridge_check
        native_app_bridge_check.setup()
        config.overlay_screens.append("sdk_app_bridge_check")

screen sdk_app_bridge_check():
    timer 0.12 repeat True action Function(native_app_bridge_check.tick, _update_screens=False)
    timer 0.01 repeat True action Function(native_app_bridge_check.early_return, _update_screens=False)
