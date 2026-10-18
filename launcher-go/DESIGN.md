---
name: The Order 1886 Go launcher preview
description: Cinematic Home and compact settings using official artwork, charcoal and brass.
colors:
  ground: "#101315"
  panel: "#171b1d"
  field: "#202527"
  border: "#41484a"
  ink: "#ece8dd"
  muted: "#b9b9af"
  brass: "#d4bd75"
  focus: "#f2d894"
typography:
  display:
    fontFamily: "Georgia, serif"
    fontSize: "32px"
    fontWeight: 400
  body:
    fontFamily: "Segoe UI, Arial, sans-serif"
    fontSize: "16px"
    fontWeight: 400
rounded:
  control: "6px"
spacing:
  page-inline: "34px"
  row-block: "21px"
components:
  button-primary:
    backgroundColor: "{colors.brass}"
    textColor: "#171910"
    rounded: "{rounded.control}"
    padding: "11px 24px"
---
## Overview

Operate mode. Players select a local game installation, configure a real launch and manage their local content. The accepted reference hybrid combines cinematic Home art/prominent Play with compact sidebar navigation and solid settings pages. Canonical sources are `frontend/src/style.css`, `main.ts` and the explicit worker catalogue.

This is a migration preview. The repository's existing root DESIGN.md describes the retained Tk launcher; this file records the separate Go module.

## Colors

The tokens above describe the dark appearance. The light system-theme variant uses ground #f0eee7, panel #e7e3d8, field #fcfbf7, ink #242c26, muted #52584f and brass #715517. The sidebar and Home artwork keep their dark treatment. Focus uses a visible outline, and failure feedback uses an additional text cue.

## Typography

Georgia carries headings; Segoe UI carries controls and content. Page headings are 32px; the Home heading is 35px. Navigation uses 14px, option labels 15px and explanatory copy 12px. Text and path wrapping must remain usable at Windows scaling settings; broad DPI/locale acceptance remains pending.

## Layout

A 206px sidebar leads to Home, Graphics, Performance, Controls, Game & Content, Achievements and System. The main grid reserves header/content/launch-bar rows; only content scrolls. The sidebar narrows to 174px below 1080px. Home carries the large official artwork; settings use divided rows with descriptions and controls. Global search crosses all pages.

## Shapes

Controls use restrained 5–7px corners. Plain divided settings rows carry the option hierarchy. Native Windows title-bar behavior remains.

## Components

Play/Stop is persistent. Autosave reports valid changes and retains previous values on failure. Unavailable choices stay visible with reasons. Confirmations protect save restoration and cache clearing. A selected save backup is an explicit pending restore before Play, not an implied in-game checkpoint load.

## Do's and Don'ts

- Reuse canonical official assets through `scripts/copy-assets.mjs`; preserve source bytes.
- Keep keyboard focus, accessible labels, search, readable descriptions and native file dialogs.
- Preserve rendered/generated/displayed FPS distinctions.
- Never turn an unavailable provider, configured setting or successful preparation into a gameplay-quality claim.

