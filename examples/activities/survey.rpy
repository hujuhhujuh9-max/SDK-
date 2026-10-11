# Copy this label into a generated project's game directory. The existing
# integration host owns initialization, native saves, command polling and UI.
label project_field_survey:
    "Before the sunrise, make a field survey of the instruments."
    call renfletpy_activity("field_survey") from project_field_survey_return
    if _return.status == "completed":
        $ instrument_count = len(_return.value["samples"])
        "You brought back observations for [instrument_count] instruments."
    else:
        "We can come back to the instruments another morning."
    return _return
