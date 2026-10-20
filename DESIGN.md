---
name: The Order 1886 Launcher
description: A charcoal and brass native Windows launcher with a cinematic launch console.
colors:
  brass: "#d4bd75"
  brass-active: "#e5cf8c"
  ivory: "#e9e5d8"
  muted: "#a8a497"
  charcoal: "#0b0b0a"
  console: "#141513"
  field: "#171817"
  control: "#20201c"
  field-border: "#64635b"
  quiet-rule: "#514932"
  button: "#25241f"
  button-active: "#3a3525"
typography:
  display:
    fontFamily: "Georgia, serif"
    fontWeight: 400
  title:
    fontFamily: "Georgia, serif"
    fontSize: "21pt"
    fontWeight: 400
  body:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "11pt"
    fontWeight: 400
  label:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "10pt"
    fontWeight: 400
  caption:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "9pt"
    fontWeight: 400
  action:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "22pt"
    fontWeight: 400
rounded:
  flat: "0px"
spacing:
  console-inline: "42px"
  console-block: "20px"
  control-gap: "24px"
  label-gap: "6px"
components:
  button-primary:
    backgroundColor: "{colors.brass}"
    textColor: "{colors.charcoal}"
    typography: "{typography.action}"
    rounded: "{rounded.flat}"
    padding: "8px 16px"
  button-primary-active:
    backgroundColor: "{colors.brass-active}"
    textColor: "{colors.charcoal}"
  button-secondary:
    backgroundColor: "{colors.button}"
    textColor: "{colors.ivory}"
    typography: "{typography.label}"
    rounded: "{rounded.flat}"
    padding: "9px 16px"
  button-secondary-active:
    backgroundColor: "{colors.button-active}"
    textColor: "{colors.brass}"
  input-home:
    backgroundColor: "{colors.field}"
    textColor: "{colors.ivory}"
    typography: "{typography.body}"
    rounded: "{rounded.flat}"
  select-home:
    backgroundColor: "{colors.field}"
    textColor: "{colors.ivory}"
    typography: "{typography.body}"
    padding: "9px 12px"
  launch-console:
    backgroundColor: "{colors.console}"
    padding: "20px 42px"
  compatibility-notice:
    backgroundColor: "{colors.console}"
    textColor: "{colors.brass}"
    typography: "{typography.label}"
---

# Design System: The Order 1886 Launcher

## Overview

**Creative North Star: "Charcoal and brass"**

The existing identity pairs dark, quiet surfaces with muted brass and ivory. Cinematic artwork provides atmosphere; a solid launch console gives text and controls a stable, readable surface. The user approved the cinematic launch-bar composition in `.impeccable/mocks/concept-a.png` on 2026-10-16. Its surface-specific direction lives in `.impeccable/surfaces/launcher-order1886-launcher-py.md`.

This is a Windows Tkinter application. The native title bar, focus behavior, dialogs, buttons and dropdown semantics are intentional adaptations of the composition. The current implementation in `launcher/order1886_common.py` (the Go launcher drives it; the Tk window was retired) is the token source. This document records the implemented system; it does not certify completion of the visual review or runtime compatibility.

**Key Characteristics:**

- Cinematic artwork with an opaque, anchored launch console.
- Georgia display lettering and readable Segoe UI controls.
- Brass reserved for identity, the main action, focus and the compatibility notice.
- Real controls and text remain separate from generated imagery.

## Colors

The palette uses warm, restrained highlights against near-black surfaces. The frontmatter is the normative color source.

### Primary

- **Brass:** wordmark, Play background, focus indication, selection and warning geometry.
- **Active brass:** the primary button's configured active background.

### Neutral

- **Charcoal:** artwork fallback, navigation and the advanced-settings backdrop.
- **Console:** the opaque home configuration surface.
- **Field / control:** home field backgrounds and combobox menus; control also appears in advanced settings.
- **Ivory:** primary labels and field values.
- **Muted:** captions, unavailable control text and secondary status.
- **Field border / quiet rule:** visible field edges and quieter separators respectively.
- **Button / active button:** secondary action surfaces and their configured active state.

The Play background includes a subtle generated brass texture. Texture supplies material variation; the brass token remains the fallback color.

## Typography

**Display Font:** Georgia, with the platform serif fallback.
**Body Font:** Segoe UI, with the platform sans-serif fallback.

The serif wordmark supplies the period character; functional UI uses the Windows interface face. Tk positive font sizes use points, while the canvas wordmark explicitly uses pixels. Do not treat these units as interchangeable.

### Hierarchy

- **Display:** the canvas draws individually spaced Georgia letters. The main line scales with canvas width, bounded to 36–67 pixels; the year is 78% of that size. The short brass rule belongs to the wordmark.
- **Title:** the advanced-settings title uses the title role.
- **Body:** home fields and dropdown values use the body role.
- **Label:** navigation, labels, notices and ordinary buttons use the label role.
- **Caption:** keyboard hints and longer explanatory text use the caption role.
- **Action:** Play uses the action role; the busy-state action reduces to 15 points to fit its label.

## Layout

The window opens at 1160 × 760 and has a minimum of 940 × 620. Artwork expands in the upper row; the opaque console occupies the lower row. The artwork uses a centered cover crop, so cropping changes with the window shape. Wordmark placement scales with the canvas; the secondary action group stays at its upper right.

The console has the inset tokens above. Its first row contains the game folder, Change and a readiness indicator. Beneath the divider, three equally weighted dropdown columns sit beside the Play column. Labels sit above their dropdowns. The notice wraps below the settings, and the keyboard hint sits below Play. These are desktop window constraints, not web or mobile breakpoints.

Advanced settings open in a 560-pixel-wide panel with scrolling and focus-driven visibility. Logs open in a separate native window. Preserve usable keyboard traversal and readable warning wrapping when changing density or window size.

**The One Primary Action Rule.** Play owns the strongest visual emphasis; its active session state becomes Stop. Settings, verification and logs remain secondary.

## Elevation & Depth

Depth comes from artwork, tonal separation and the brass material. Home controls are flat, with thin edges and focus indication. There is no custom drop-shadow vocabulary. Native Windows window chrome is supplied by the operating system.

## Shapes

The console and controls use a flat, square form. Fields have a one-pixel highlight border. Thin rules separate functions without introducing card stacks. The readiness check, warning triangle and Play triangle are authored geometry; they are not text glyphs or controls baked into an image.

## Components

### Buttons

The primary action is a native `tk.Button` with a mirror-tiled brass texture behind a semantic text label. The triangle is drawn into its presentation surface. Its fallback is the primary background token. During a session its label and enabled state reflect Stop or stopping; keep that state visible.

Secondary buttons use quiet dark surfaces. Navigation buttons sit directly against charcoal, with narrow separators between actions. All retain their native command and keyboard behavior, brass focus indication and explicit disabled state. Do not replace the widgets with raster hit targets.

### Inputs / Fields

The home folder entry and read-only `ttk.Combobox` controls use dark fills, ivory values and the field-border token. Focus changes the border to brass. Dropdown selection uses brass with charcoal text. While a session or advanced-settings panel owns interaction, the essential controls are disabled; muted text signals that state.

### Launch Console and Notices

The console is opaque so configuration and warnings do not depend on the artwork's contrast. The warning uses brass text with authored triangle geometry. Readiness uses its own text and, when appropriate, a circular check indicator. Keep the compatibility notice visible beside the launch workflow.

**The Semantic Overlay Rule.** Wordmark, labels, controls and state indicators are drawn by the application, never embedded as mockup UI in the background.

### Artwork

The loader tries `launcher/order1886/launcher-art.png`, then the selected game's `sce_sys/pic0.png`, then the bundled `background.png`. A failed image falls through to the next source. The player's folder remains read-only. The generated background provides the selected composition without shipping rasterized labels or buttons. Embedded prompt provenance and the adjacent text record describe the generated assets.

## Do's and Don'ts

### Do:

- **Do** preserve the charcoal, brass and ivory identity and the Georgia / Segoe UI pairing.
- **Do** keep Play, the game folder and essential settings immediately available.
- **Do** keep semantic native controls, visible focus and keyboard access.
- **Do** verify the minimum window and long warning states after layout changes.
- **Do** keep readiness and experimental-runtime compatibility messages visibly distinct.

### Don't:

- **Don't** bake interface text, controls or status claims into generated artwork.
- **Don't** replace the native stack solely to reproduce mockup chrome.
- **Don't** present a frame-rate choice or file-readiness indicator as gameplay or performance evidence.
- **Don't** treat this documentation as closure of the open Impeccable review gates.
