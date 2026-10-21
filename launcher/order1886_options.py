# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit player settings; availability describes the actual Order launch path."""
from launcher.order1886_lang import LANGUAGES
from scripts.order1886_input import BUTTONS, UNBOUND

PAGES = [
    {"id": "home", "title": "Home"}, {"id": "graphics", "title": "Graphics"},
    {"id": "performance", "title": "Performance"}, {"id": "controls", "title": "Controls"},
    {"id": "game", "title": "Game & Content"}, {"id": "achievements", "title": "Achievements"},
    {"id": "system", "title": "System"},
]
TEMPORAL = ("Two things are missing: verified Order depth, motion, jitter, history and HUD inputs "
            "(#7), and a temporal renderer in this build. The runtime also forces the upscaler off, so "
            "selecting one of these cannot take effect yet (#10-#13).")
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
field("performance_capture", "Record performance data", "system", "boolean", False,
      "Save frame times and slow-frame diagnostics with each session's logs. Turn this off after recording the slow scene.")
field("display_mode", "Display mode", "graphics", "select", "borderless", "Window mode is independent of framing and game timing.",
      [("windowed", "Windowed", ""), ("borderless", "Borderless", ""), ("fullscreen", "Fullscreen", "")])
field("aspect_ratio", "Framing", "graphics", "select", "original", "Original preserves cinematic framing. The 16:9 patch is executable-specific and experimental.",
      [("original", "Original cinematic aspect", ""), ("16:9", "16:9 — experimental", "")])
field("presentation_filter", "Upscaling", "graphics", "select", "fsr1", "Choose Linear / no FSR for the original-resolution path. Presentation scaling does not establish native internal resolution: the scene renders at the size the game chooses, and larger output is not native 4K (docs/order1886-resolution.md).",
      [("linear", "Linear / no FSR", ""), ("fsr1", "FSR 1", ""),
       ("taa", "Native temporal AA", TEMPORAL), ("dlss", "NVIDIA DLSS Super Resolution", TEMPORAL),
       ("fsr3", "AMD FSR 3.1", TEMPORAL), ("fsr4", "AMD FSR 4", TEMPORAL),
       # XeSS has no identifier in the runtime's upscaler names yet; the runtime's "fsr411" has no
       # launcher label either, so both sides are honest about the mismatch.
       ("xess", "Intel XeSS", "The runtime has no XeSS identifier yet, so even a qualified temporal "
        "renderer could not select it (#13).")])
field("vsync", "VSync", "graphics", "boolean", True, "Synchronize presentation with the display.")
field("output_resolution", "Output resolution", "graphics", "select", "automatic",
      "Size of the presented image before it is fitted to the window. The game still renders at its own size, so a larger output is upscaled by the Upscaling filter, not native 4K; a smaller one costs less and is stretched to the window. Output dimensions and game-rendered dimensions are reported separately.",
      [("automatic", "Match the window", ""), ("1280x720", "1280 × 720 output", ""),
       ("1920x1080", "1920 × 1080 output", ""), ("2560x1440", "2560 × 1440 output", ""),
       ("3840x2160", "3840 × 2160 output (upscaled, not native 4K)", "")])
field("upscale_preset", "Upscaler quality", "graphics", "select", "quality", "Quality presets require a qualified temporal provider.",
      [(x, x.title(), TEMPORAL) for x in ("native", "quality", "balanced", "performance")], reason=TEMPORAL)
field("sharpness", "Sharpening", "graphics", "number", 0,
      "RCAS sharpening strength in percent; 0 turns it off. It runs with FSR 1 upscaling, or when the output matches the game's size; with Linear upscaling to a larger output it has no pass to run in.",
      minimum=0, maximum=100)
field("anisotropy", "Anisotropic filtering", "graphics", "select", 1,
      "Raises filtering to at least this level on filtered, mipmapped textures; depth and point-sampled textures keep the game's own sampling. Applies on next launch; visual qualification is pending.",
      [(x, "Game default" if x == 1 else str(x) + "×", "") for x in (1, 2, 4, 8, 16)])
for key, label in (("film_grain", "Film grain"), ("motion_blur", "Motion blur"),
                   ("depth_of_field", "Depth of field"), ("chromatic_aberration", "Chromatic aberration"),
                   ("model_detail", "Model detail")):
    field(key, label, "graphics", "boolean", True, "Preserve the original effect until a verified game-specific control is implemented (#16).", reason=PATCH)
# The backend accepts 30 and 60 only and pins vblank to 60, so a higher rate needs both a
# hash-verified recipe and that ceiling lifted: the PATCH reason alone under-described it.
FRAME_RATE_REASON = ("The backend accepts 30 and 60 and pins vblank to 60 Hz, and no hash-verified "
                     "recipe exists to raise either. Nothing here is a simulation-timing control.")
field("frame_rate", "Game frame rate", "performance", "select", 30, "30 FPS is native. 60 FPS is experimental; Chapter 6/9 QTE checks remain required.",
      [(30, "30 FPS — native", ""), (60, "60 FPS — experimental", ""),
       (90, "90 FPS", FRAME_RATE_REASON), (0, "Unlocked", FRAME_RATE_REASON)])
field("in_game_menu", "In-game settings menu", "performance", "boolean", False, "Off by default. The menu, its tabs and the settings it changes while the game runs are unqualified for this title: input capture, focus and stability have not been verified in gameplay, so enable it only to help test it. Insert or R3+R2 toggles it when enabled.")
field("fps_cap", "Presentation frame cap", "performance", "number", 120, "Limits how often the runtime presents, not how fast the engine runs (#14). The game frame rate still wins while it is lower, so the default of 120 never changes pacing; lowering it throttles presentation only. This is not a simulation-timing control.", minimum=30, maximum=240)
field("frame_generation", "Frame generation", "performance", "select", "off", "Generated frames do not increase simulation rate. All three providers remain in the gold plan.",
      [("off", "Off", ""), ("fsr", "AMD FSR Frame Generation", FG),
       ("dlss", "NVIDIA DLSS Frame Generation", FG + " Requires supported NVIDIA hardware."),
       ("xess", "Intel XeSS Frame Generation", FG + " Requires the Windows D3D12 presentation bridge.")], reason=FG)
field("show_fps", "Performance overlay", "performance", "boolean", True, "Show the runtime performance overlay.")
field("htile_unqualified", "HTILE metadata adaptation (unqualified)", "performance", "boolean", False,
      "Off by default. The adapted HTILE metadata read path has no matched gameplay, visual or frame-cost qualification yet (#5), so leave it off unless you are helping to measure it. Turning it on lets buffer reads take the tracked HTILE word instead.")
field("synchronous_recording", "Synchronous command recording (unqualified)", "performance", "boolean", False,
      "Off by default and unqualified for performance, stability and visuals. The runtime normally records Vulkan commands on its own recording thread and hands them over; turning this on records each command on the thread that submits it, so no work moves between threads. It does not change what the game draws. A runtime honours it only when its build declares the live switch file.")
field("texture_update_locking", "Locked texture update checks (unqualified)", "performance", "boolean", False,
      "Off by default and unqualified for performance, stability and visuals. Before an upload the runtime checks a clean image's flags without taking the mutex it shares with the guest fault handlers; turning this on takes that mutex for every check. Uploads and image contents are otherwise unchanged, and the extra locking costs GPU-thread time. It is here to isolate a suspected race, not to change the picture. A runtime honours it only when its build declares the live switch file.")
field("readbacks", "GPU readback policy", "performance", "select", "relaxed",
      "Relaxed keeps the existing behavior. Selective synchronizes CPU reads of small GPU output buffers; precise tracks all GPU-written buffers. Both can add waits and require gameplay/performance qualification.",
      [("relaxed", "Relaxed (existing baseline)", ""), ("selective", "Selective — experimental", ""),
       ("precise", "Precise — experimental", ""), ("disabled", "Disabled", "Required buffer readbacks cannot be disabled in the Order profile.")])
for key, label, default in (("overlay_frametime", "Overlay: frame time", True), ("overlay_gpu", "Overlay: GPU", False),
                            ("overlay_cpu", "Overlay: CPU", False), ("overlay_memory", "Overlay: RAM / VRAM", False)):
    field(key, label, "performance", "boolean", default, "Shown in the performance overlay when it is on.")
field("frames_queued", "Queued frames", "performance", "select", 1,
      "How many frames the GPU command thread may run ahead of the GPU. 1 is the paced baseline; 2 can raise throughput at the cost of latency; Unbounded removes the wait and can make frame delivery bursty.",
      [(1, "1 — baseline", ""), (2, "2 (unqualified)", ""), (0, "Unbounded (unqualified)", "")])
UNQUALIFIED = "Off by default: the correctness baseline. Turning it on is unqualified for stability and visuals; use it to help measure the path."
for key, label, detail in (
        ("async_shaders", "Asynchronous shaders (unqualified)",
         "Compile new pipelines off the GPU thread; draws that need one are skipped until it is ready, so stutter becomes brief missing geometry."),
        ("background_warmup", "Background pipeline warmup (unqualified)",
         "Load cached pipelines while the game runs instead of on a loading screen before the first frame."),
        ("parallel_warmup", "Parallel pipeline warmup (unqualified)",
         "Build cached pipelines on several CPU threads during warmup."),
        ("speculative_readbacks", "Deferred image readbacks (unqualified)",
         "Copy GPU-written images back to guest memory later, in batches, instead of waiting at each CPU access.")):
    field(key, label, "performance", "boolean", False, detail + " " + UNQUALIFIED)
field("mouse_look", "Mouse camera", "controls", "boolean", True, "Map mouse movement to the game camera; release capture when focus is lost.")
field("mouse_sensitivity", "Mouse sensitivity", "controls", "number", 100, "Camera sensitivity in percent.", minimum=10, maximum=500)
field("mouse_invert_y", "Invert vertical camera", "controls", "boolean", False, "Invert vertical mouse movement.")
field("vibration", "Controller vibration", "controls", "boolean", True, "Independent vibration configuration is pending runtime validation.", reason=RENDERER)
for kind, label in (("keyboard", "Keyboard buttons"), ("controller", "Controller buttons")):
    field(kind + "_bindings", label, "controls", "bindings", {},
          "Choose the host input for each PS4 digital button. Default restores the original source. Shared inputs press all assigned buttons; keyboard stick keys, mouse buttons and overlay shortcuts stay active. Physical sticks, analog triggers and real touch input are unchanged. Applies on next launch.",
          choices=[(UNBOUND, "No digital source", "Select a matching native runtime to remove a digital binding.")],
          input_kind=kind, buttons=[{"id": key, "label": title, "default": []} for key, title in BUTTONS.items()])
field("input_remapping", "Stick axes and analog trigger remapping", "controls", "text", "", "Keyboard stick axes, physical analog triggers and real touch input are not independently remappable yet (#4).", reason=RENDERER)
field("ui_language", "Launcher language", "system", "select", "en", "Apply the launcher catalog immediately. Game language changes take effect on its next launch when assets are installed.",
      [(key, title, "") for key, title in LANGUAGES.items()])
field("game_text_language", "Game text language", "game", "select", "follow", "Independent text selection remains tracked in #21.",
      [("follow", "Follow launcher language", "")] + [(key, title, PATCH) for key, title in LANGUAGES.items()], reason=PATCH)
field("game_voice_language", "Game voice language", "game", "select", "follow", "Independent voice selection requires installed language assets (#21).",
      [("follow", "Follow launcher language", "")] + [(key, title, PATCH) for key, title in LANGUAGES.items()], reason=PATCH)
field("selected_patches", "Catalogued patches", "game", "patches", [], "Recipes that edit the prepared image are applied on the next preparation, and each one must match this build`s title id, APP_VER, VERSION, image hashes and expected bytes or the preparation refuses it. The 60 FPS and 16:9 recipes are configured by the game frame rate and framing settings instead, so they are not selectable here.")
field("mods_dir", "Mods folder", "game", "directory", "", "Mount loose-file overlays without changing original game files.")
field("mods_enabled", "Enable mods", "game", "boolean", False, "Only enabled folders in the saved order are mounted.")
field("mod_order", "Enabled mod order", "game", "order", [], "One folder name per line. Later enabled mods take priority; newly discovered mods remain disabled.")
for key, label in (("infinite_health", "Infinite health"), ("infinite_ammo", "Infinite ammunition"),
                   ("skip_reload", "Skip reload")):
    field(key, label, "game", "boolean", False, "Cheats require version-verified recipes and gameplay acceptance (#15).", reason=PATCH)
field("automatic_updates", "Check for updates on start", "system", "boolean", False,
      "Check the selected channel once when the launcher starts and show a notice. Nothing is downloaded or installed without a click.")
field("update_channel", "Update channel", "system", "select", "preview",
      "Preview follows every published Go preview, which is the only channel that carries a launcher package today. Stable stays quiet until a release without a preview suffix exists.",
      [("preview", "Preview — every published Go preview", ""),
       ("stable", "Stable — released builds only", "")])

