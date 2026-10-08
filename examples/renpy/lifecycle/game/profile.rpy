# Opt-in project configuration, deliberately separate from the callable library.
# The engine loads persistent data BEFORE regular init Python executes.
python early:
    import os
    renpy.config.save_directory = "sdk-native-lantern-v1"
    if renpy.android:
        # save_directory alone is ignored on Android. Never share the default
        # runner's saves directory or its engine-owned _reload-1 archive.
        renpy.config.savedir = os.path.join(os.environ["ANDROID_PRIVATE"], "saves", "sdk-native-lantern-v1")
    else:
        renpy.config.savedir = renpy.__main__.path_to_saves(renpy.config.gamedir, "sdk-native-lantern-v1")
