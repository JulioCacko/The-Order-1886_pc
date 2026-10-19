# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit player settings; availability describes the actual Order launch path."""
from launcher.order1886_lang import LANGUAGES

PAGES = [
    {"id": "home", "title": "Home"}, {"id": "graphics", "title": "Graphics"},
    {"id": "performance", "title": "Performance"}, {"id": "controls", "title": "Controls"},
    {"id": "game", "title": "Game & Content"}, {"id": "achievements", "title": "Achievements"},
    {"id": "system", "title": "System"},
]
TEMPORAL = "Requires verified Order depth, motion, jitter, history and HUD inputs (#7)."
RENDERER = "This setting is not exposed by the validated Order launch profile yet; backend wiring and qualification are pending."
PATCH = "No hash-verified recipe for this executable is available yet."
FG = "Frame-generation presentation, synchronization and latency qualification are pending."
FIELDS = []


def field(key, label, page, kind, default, description, choices=None, reason="", **limits):
    item = dict(key=key, label=label, page=page, kind=kind, default=default,
                description=description, available=not bool(reason), reason=reason,
                apply="next_launch", **limits)
    if choices is not None:
        item["choices"] = [
            dict(value=value, label=title, available=not bool(why), reason=why)
            for value, title, why in choices
        ]
    FIELDS.append(item)


field("game_dir", "Game folder", "game", "directory", "", "Select the extracted CUSA00076 game. Original files remain unchanged.")
field("runtime", "Runtime executable", "system", "file", "", "Leave empty to use the installation's verified Order runtime.")
field("display_mode", "Display mode", "graphics", "select", "borderless", "Window mode is independent of framing and game timing.",
      [("windowed", "Windowed", ""), ("borderless", "Borderless", ""), ("fullscreen", "Fullscreen", "")])
field("aspect_ratio", "Framing", "graphics", "select", "original", "Original preserves cinematic framing. The 16:9 patch is executable-specific and experimental.",
      [("original", "Original cinematic aspect", ""), ("16:9", "16:9 — experimental", "")])
field("presentation_filter", "Upscaling", "graphics", "select", "fsr1", "Presentation scaling does not establish native internal resolution.",
      [("linear", "Linear / no FSR", ""), ("fsr1", "FSR 1", ""),
       ("taa", "Native temporal AA", TEMPORAL), ("dlss", "NVIDIA DLSS Super Resolution", TEMPORAL),
       ("fsr3", "AMD FSR 3.1", TEMPORAL), ("fsr4", "AMD FSR 4", TEMPORAL),
       ("xess", "Intel XeSS", TEMPORAL)])
field("vsync", "VSync", "graphics", "boolean", True, "Synchronize presentation with the display.")
field("output_resolution", "Output resolution", "graphics", "select", "automatic", "Output dimensions and game-rendered dimensions are reported separately.",
      [("automatic", "Current runtime default", ""), ("1280x720", "1280 × 720", RENDERER),
       ("1920x1080", "1920 × 1080", RENDERER), ("2560x1440", "2560 × 1440", RENDERER),
       ("3840x2160", "3840 × 2160", RENDERER)], reason=RENDERER)
field("upscale_preset", "Upscaler quality", "graphics", "select", "quality", "Quality presets require a qualified temporal provider.",
      [(x, x.title(), TEMPORAL) for x in ("native", "quality", "balanced", "performance")], reason=TEMPORAL)
field("sharpness", "Sharpening", "graphics", "number", 0, "RCAS is currently disabled by the Order profile.", reason=RENDERER, minimum=0, maximum=100)
field("anisotropy", "Anisotropic filtering", "graphics", "select", 1, "Texture-filter overrides need matched visual validation.",
      [(x, str(x) + "×", RENDERER) for x in (1, 2, 4, 8, 16)], reason=RENDERER)
for key, label in (("film_grain", "Film grain"), ("motion_blur", "Motion blur"),
                   ("depth_of_field", "Depth of field"), ("chromatic_aberration", "Chromatic aberration"),
                   ("model_detail", "Model detail")):
    field(key, label, "graphics", "boolean", True, "Preserve the original effect until a verified game-specific control is implemented (#16).", reason=PATCH)
field("frame_rate", "Game frame rate", "performance", "select", 30, "30 FPS is native. 60 FPS is experimental; Chapter 6/9 QTE checks remain required.",
      [(30, "30 FPS — native", ""), (60, "60 FPS — experimental", ""),
       (90, "90 FPS", PATCH), (0, "Unlocked", PATCH)])
field("fps_cap", "Unlocked frame cap", "performance", "number", 120, "Host cap is distinct from simulation timing (#14).", reason=PATCH, minimum=30, maximum=240)
field("frame_generation", "Frame generation", "performance", "select", "off", "Generated frames do not increase simulation rate. All three providers remain in the gold plan.",
      [("off", "Off", ""), ("fsr", "AMD FSR Frame Generation", FG),
       ("dlss", "NVIDIA DLSS Frame Generation", FG + " Requires supported NVIDIA hardware."),
       ("xess", "Intel XeSS Frame Generation", FG + " Requires the Windows D3D12 presentation bridge.")], reason=FG)
field("show_fps", "Performance overlay", "performance", "boolean", True, "Show the runtime performance overlay.")
field("readbacks", "GPU readback policy", "performance", "select", "relaxed",
      "Relaxed keeps the existing behavior. Selective synchronizes CPU reads of small GPU output buffers; precise tracks all GPU-written buffers. Both can add waits and require gameplay/performance qualification.",
      [("relaxed", "Relaxed (existing baseline)", ""), ("selective", "Selective — experimental", ""),
       ("precise", "Precise — experimental", ""), ("disabled", "Disabled", "Required buffer readbacks cannot be disabled in the Order profile.")])
for key, label, default in (("overlay_frametime", "Overlay: frame time", True), ("overlay_gpu", "Overlay: GPU", False),
                            ("overlay_cpu", "Overlay: CPU", False), ("overlay_memory", "Overlay: RAM / VRAM", False)):
    field(key, label, "performance", "boolean", default, "Individual overlay items are not yet wired to this launch profile.", reason=RENDERER)
for key, label, kind, default in (("frames_queued", "Queued frames", "number", 2),
                                ("async_shaders", "Asynchronous shaders", "boolean", False),
                                ("background_warmup", "Background pipeline warmup", "boolean", False),
                                ("parallel_warmup", "Parallel pipeline warmup", "boolean", False),
                                ("speculative_readbacks", "Speculative GPU readbacks", "boolean", False)):
    field(key, label, "performance", kind, default, "Retain the correctness baseline until this path is qualified.", reason=RENDERER, minimum=1, maximum=4)
field("mouse_look", "Mouse camera", "controls", "boolean", True, "Map mouse movement to the game camera; release capture when focus is lost.")
field("mouse_sensitivity", "Mouse sensitivity", "controls", "number", 100, "Camera sensitivity in percent.", minimum=10, maximum=500)
field("mouse_invert_y", "Invert vertical camera", "controls", "boolean", False, "Invert vertical mouse movement.")
field("vibration", "Controller vibration", "controls", "boolean", True, "Independent vibration configuration is pending runtime validation.", reason=RENDERER)
field("input_remapping", "Keyboard / controller bindings", "controls", "text", "", "Complete remapping and direct-camera acceptance remain tracked in #4.", reason=PATCH)
field("ui_language", "Launcher language", "system", "select", "en", "Apply the launcher catalog immediately. Game language changes take effect on its next launch when assets are installed.",
      [(key, title, "") for key, title in LANGUAGES.items()])
field("game_text_language", "Game text language", "game", "select", "follow", "Independent text selection remains tracked in #21.",
      [("follow", "Follow launcher language", "")] + [(key, title, PATCH) for key, title in LANGUAGES.items()], reason=PATCH)
field("game_voice_language", "Game voice language", "game", "select", "follow", "Independent voice selection requires installed language assets (#21).",
      [("follow", "Follow launcher language", "")] + [(key, title, PATCH) for key, title in LANGUAGES.items()], reason=PATCH)
field("mods_dir", "Mods folder", "game", "directory", "", "Mount loose-file overlays without changing original game files.")
field("mods_enabled", "Enable mods", "game", "boolean", False, "Only enabled folders in the saved order are mounted.")
field("mod_order", "Enabled mod order", "game", "order", [], "One folder name per line. Later enabled mods take priority; newly discovered mods remain disabled.")
for key, label in (("infinite_health", "Infinite health"), ("infinite_ammo", "Infinite ammunition"),
                   ("skip_reload", "Skip reload")):
    field(key, label, "game", "boolean", False, "Cheats require version-verified recipes and gameplay acceptance (#15).", reason=PATCH)
field("automatic_updates", "Automatic updates", "system", "boolean", False, "Transactional downloads, interruption recovery and rollback are still required (#9).", reason="The current updater uses manual release downloads.")

