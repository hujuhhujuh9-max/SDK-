# Project-defined field survey

Generate a project with `python3 create_project.py ../survey-app`. Copy
`survey_activity.py` into its `app/` directory and `survey.rpy` into its `game/`
directory. Add `"project_setup": "survey_activity:register"` to its
`renfletpy.json`. Call `project_field_survey` from the project's own story.
The SDK's normal story/menu/save routes render it; no SDK route or kind edit
is required.

Select an instrument, type an unfinished observation and record it. Select a
second instrument and leave a draft in the text field. Open Menu, save halfway,
close/reopen, and load the save. The selected instrument, first observation and
unfinished text restore. Finish after recording the second instrument. The
native story receives one `ActivityResult("completed", {"samples": ...,
"notes": ...})`; **Do this later** returns an explicit cancelled result.
Saving after cancellation records the cancelled outcome; resuming an unfinished
survey requires a save made before cancellation.

Version 2 migrates version 1's `found`/`note` data into collected instruments,
per-instrument notes, draft and selection. Controls and callback closures are
created again by the renderer. The saved values contain no Flet objects,
threads or services.

Host acceptance, including a separate Python process reopening a half-save:

```sh
python3 -m unittest discover -s tests -p test_story_activities.py -v
```

Native Ren'Py acceptance with the pinned SDK and Xvfb:

```sh
python3 examples/activities/verify_native.py \
  --renpy-sdk /path/to/renpy-8.5.3-sdk --xvfb /path/to/Xvfb
```

This compiles the actual native activity wait label and saves/loads the live
adapter in separate native processes, with a second independently compiled
project and a version 1 save migrated by version 2. It does not measure Android
phone performance.
