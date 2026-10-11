# Original project workload. It uses native authoring and never changes SDK routes.
init -1 python:
    renpy.register_shader("sdk_scale.ripple", variables="""
        uniform sampler2D tex0;
        varying vec2 v_tex_coord;
        uniform float u_time;
    """, fragment_300="""
        vec2 sdk_wave_uv = v_tex_coord;
        sdk_wave_uv.x += sin(v_tex_coord.y * 30.0 + u_time * 2.0) * 0.015;
        gl_FragColor = texture2D(tex0, sdk_wave_uv);
    """)
    renpy.register_shader("sdk_scale.scanline", variables="""
        varying vec2 v_tex_coord;
        uniform float u_time;
    """, fragment_400="""
        float sdk_scan_gain = 0.72 + 0.28 * sin(v_tex_coord.y * 90.0 + u_time * 3.0);
        gl_FragColor.rgb *= sdk_scan_gain;
    """)
    import scale_native
    import json

transform sdk_scale_shader(part):
    mesh True
    shader part

transform sdk_scale_orbit(index):
    rotate 0
    alpha 0.55
    parallel:
        linear (1.8 + index % 7 * 0.1) rotate 360
        repeat
    parallel:
        linear 0.7 xoffset 12 yoffset 8
        linear 0.7 xoffset 0 yoffset 0
        repeat
    parallel:
        linear 0.5 alpha 1.0
        linear 0.5 alpha 0.55
        repeat

screen sdk_scale_native_stage(tier="nominal", animated=True, shaders=True, probe=False):
    modal True
    frame:
        align (0.5, 0.5)
        xsize min(720, config.screen_width)
        padding (16, 16)
        background Solid("#101b2bf5")
        vbox:
            spacing 14
            text "2D native workload" size 28 color "#f4f0e8"
            add scale_native.scene(tier, min(688, config.screen_width - 32), 480, animated=animated, shaders=shaders):
                id "sdk_scale_native_field"
            text "ATL · compositing · ripple and scanline shaders" size 20 color "#b9d7de"
            button:
                id "sdk_scale_continue"
                yminimum 64
                padding (12, 12)
                background Solid("#263e50")
                action Return({"tier": tier, "outcome": "continued"})
                text "Continue 2D journey" size 24 color "#f4f0e8"

label sdk_scale_animation(tier="nominal"):
    $ renpy.checkpoint()
    call screen sdk_scale_native_stage(tier)
    $ scale_native.release()
    return _return

default sdk_scale_canvas_result = None
default sdk_scale_rive_result = None

# Use Ren'Py's project-owned label override. The copied SDK starter still owns
# Start/Resume/Return and bookmarks; the default SDK story remains unchanged.
init 10 python:
    if renpy.has_label("app_recipe_story"):
        config.label_overrides["app_recipe_story"] = "sdk_scale_journey"

label sdk_scale_journey:
    mira "The 2D lab has a moving light field, a map and a control console. Your application draft stays at home."
    call sdk_scale_animation from sdk_scale_animation_return
    mira "Now pan the story map, zoom it, select a node and save your place halfway through."
    call renfletpy_activity("scale_canvas") from sdk_scale_canvas_return
    $ sdk_scale_canvas_result = {"status": _return.status, "value": _return.value}
    $ print("SDK_2D_ACTIVITY_RESULT " + json.dumps({"kind": "scale_canvas", "result": sdk_scale_canvas_result}, sort_keys=True), flush=True)
    mira "The console connects saved game values with live animation. Adjust it, then send its event."
    call renfletpy_activity("rive_console") from sdk_scale_rive_return
    $ sdk_scale_rive_result = {"status": _return.status, "value": _return.value}
    $ print("SDK_2D_ACTIVITY_RESULT " + json.dumps({"kind": "rive_console", "result": sdk_scale_rive_result}, sort_keys=True), flush=True)
    return "2D journey complete. Canvas: %s; Rive: %s." % (sdk_scale_canvas_result["status"], sdk_scale_rive_result["status"])
