# Select the optional app's save location before persistent-data reads.
python early:
    import os
    renpy.config.save_directory = "sdk-app-lantern-v1"
    if renpy.android:
        renpy.config.savedir = os.path.join(os.environ["ANDROID_PRIVATE"], "saves", "sdk-app-lantern-v1")
    else:
        renpy.config.savedir = renpy.__main__.path_to_saves(renpy.config.gamedir, "sdk-app-lantern-v1")
