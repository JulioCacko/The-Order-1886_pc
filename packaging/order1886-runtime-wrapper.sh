#!/bin/sh
# Sun-shadow chain (theorder1886-port#26). The v0.2.10 note killed the page sync here because
# its synchronous drain (scheduler.Finish) handed the shadow pass half-updated depth. That fix
# held for Chapter I, but The Chase flickers every other frame without the sync: the deferred
# readback serves the sun's EVSM ranges a frame stale. The runtime now defaults to the staging
# sync (sun_sync=1 in runtime.ini): the copy is batched at the EVSM dispatch and a CPU fault
# takes the newest completed batch - no drain, no stale frame. ORDER1886_SUN_SYNC=0 or 2 in
# this file would still override the ini; do not add it back.

# One-shot gamepad diagnostics. Best-effort, never fatal, silent when all is well. The launcher
# verifies the runtime by exec-ing this entry with --runtime-info/--gamepad/--input-options and
# parsing stdout, so the scan runs ONLY for a real game boot (first argument is the prepared
# image path, a --flag means a probe). ORDER1886_PAD_DIAG=0 skips; ORDER1886_SYSFS points the
# scan at a fake sysfs for tests. Every line starts with "Order1886: pad check:" to stay greppable.
first=$1
case $first in
  --*|"") diag=0 ;;
  *) diag=1 ;;
esac
diag=${ORDER1886_PAD_DIAG:-$diag}
if [ "$diag" = 1 ]; then
  SYS=${ORDER1886_SYSFS:-/sys}
  if [ ! -d "/lib/modules/$(uname -r)" ]; then
    printf 'Order1886: pad check: the running kernel (%s) has no module folder: gamepad drivers (xpad, hid-microsoft) cannot load. Reboot into the installed kernel.\n' "$(uname -r)"
  fi
  pads=0
  for u in "$SYS"/bus/usb/devices/*/; do
    [ -f "$u/idVendor" ] || continue
    v=$(cat "$u/idVendor" 2>/dev/null)
    [ "$v" = 045e ] || [ "$v" = 1720 ] || continue
    pads=1
    bound=
    p=$(basename "$u")
    for i in "$u$p":*/driver; do
      [ -e "$i" ] && bound=1 && break
    done
    [ "$bound" ] && continue
    printf 'Order1886: pad check: an Xbox pad (%s:%s) is visible on USB but no driver took it: the kernel module is missing or failed to load (reboot after a kernel update, or load xpad).\n' "$v" "$(cat "$u/idProduct" 2>/dev/null)"
  done
  for h in "$SYS"/class/hidraw/hidraw*; do
    uev=$(cat "$h/device/uevent" 2>/dev/null)
    case $uev in
      *0000045E*|*0000045e*) pads=1
        node=/dev/$(basename "$h")
        [ -e "$node" ] && [ ! -r "$node" ] && printf 'Order1886: pad check: %s is present but your user cannot read it. Add the udev rule from the CONTROLLERS section of QUICKSTART.txt, or grant the input group.\n' "$node"
        ;;
    esac
  done
  if [ "$pads" = 0 ] && [ -d "$SYS"/class/input ]; then
    found=0
    for n in "$SYS"/class/input/input*; do
      name=$(cat "$n/name" 2>/dev/null)
      case $name in
        *[Xx][Bb]ox*|*XBOX*|*Microsoft*) found=1
          for e in "$n"/event*; do
            [ -e "$e" ] || continue
            ev=/dev/input/$(basename "$e")
            [ -r "$ev" ] || printf 'Order1886: pad check: "%s" (%s) is not readable by your user: quit Steam or grant input access.\n' "$name" "$ev"
          done
          ;;
      esac
    done
  fi
fi
exec "$(dirname "$0")/order1886-runtime.bin" "$@"
