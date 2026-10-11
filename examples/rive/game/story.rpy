init -10 python:
    config.label_overrides["app_recipe_story"] = "project_story"

label project_story:
    "The observatory needs a transmission. Its controls are a project activity."
    call renfletpy_activity("rive_console")
    $ transmission = _return
    if transmission.status == "completed":
        "The Rive state machine acknowledged the finished transmission."
        $ progress = transmission.value["progress"]
        "The native story received [progress] percent progress."
    else:
        "Transmission cancelled. The story received an explicit cancellation."
    return
