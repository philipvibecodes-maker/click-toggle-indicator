# Virtual-trackpad and screenshot testing

The GTK configurator was tested on 2026-11-18 on the
`feature/gtk-tray-configurator` branch with Input Remapper 2.0.1, GNOME Shell
46.0/Mutter 46.2, GTK 3, and an X11 desktop. The live desktop used GTK scale 2;
the private GNOME compositor used a 1024×768 logical monitor.

## Results from this run

- `make check`: five settings/preset/lifecycle tests and all Xvfb checks passed.
- `make check-gui`: GTK lifecycle/rollback smoke test passed.
- Original live virtual-touchpad suite: all six tests passed, including terminal drag.
- Extended live configurator/trackpad: 40 routing starts and cancellations passed;
  color/position/size/release and 50%-opacity pixel checks passed; ordinary native
  tap-to-click, duplicate-launcher refusal, and real Start/Apply/Stop passed. Read
  the recorded limitations below.
- Private GNOME: renderer, bridge loss/release, and actual AppIndicator menu launch passed.

Raw summaries: [live trackpad](testing/gtk-configurator/results.txt),
[GNOME](testing/gtk-configurator/gnome-results.txt),
[original live suite](testing/gtk-configurator/e2e-results.txt),
[regular checks](testing/gtk-configurator/check-results.txt), and
[GTK smoke](testing/gtk-configurator/gui-results.txt).

## What each test exercises

| Command | Input and display path | Limits |
| --- | --- | --- |
| `make check` | Settings validation, actual Input Remapper event-handler pipeline with mocked devices, C daemon on Xvfb | No real evdev device or desktop tray host |
| `make check-gui` | GTK controls, persistence, rollback, C restart/button release, close-to-tray/reopen on private Xvfb and D-Bus | Physical injection is replaced by direct daemon launch |
| `make check-e2e` | Kernel-created uinput touchpad → privileged Input Remapper → virtual keyboard → live X11 daemon | Uses the original midpoint preset; requires a live desktop |
| `make check-virtual-trackpad` | GTK Start/Apply/Stop → saved settings/preset → real privileged Input Remapper → kernel virtual devices → live X11; libinput taps and screenshot pixel checks | Opens a test window and moves the pointer; use a dedicated test desktop |
| `make check-gnome` | Real GNOME extension, D-Bus Configure, Python bridge, C daemon on private Xvfb, Ubuntu AppIndicators host, virtual-pointer click on Configure | The compositor is private/headless Wayland; daemon input remains X11, supplied with XTest keys rather than the kernel trackpad |

The distinction matters: sending F19/F24 alone cannot detect remapper restart
races, axis-event initialization, native libinput taps, or an absent tray host.
The kernel trackpad test and GNOME test complement each other; the complete
kernel-trackpad-to-GNOME path has not been exercised in one session.

## Reproduce

Build first with `make`. Install the normal project dependencies and GTK/tray
packages from the README. Additional tools/packages are:

```sh
sudo apt install xvfb xauth x11-utils x11-xserver-utils xinput xdotool \
  dbus-daemon python3-evdev python3-pil python3-gi-cairo gnome-terminal \
  gnome-shell-extension-appindicator
```

The GNOME test additionally requires GNOME Shell 46/Mutter 14, a working headless
renderer, and the Ubuntu AppIndicators extension under `/usr/share/gnome-shell/extensions`.
It does not require `/dev/uinput` or a live desktop. These optional tests report
errors when prerequisites are unavailable; a failure is not a PASS.

The live tests need access to `/dev/uinput`, the Input Remapper system service,
and an authenticated X11 display. Stop other toggle instances **on that display**.
Use a test desktop because pointer movement, native clicks and a terminal drag
are intentional parts of the tests. Do not run the live commands blindly against
an unattended working desktop.

```sh
make check
make check-gui
make check-e2e
./tests/virtual-trackpad.sh artifacts/virtual-trackpad
./tests/gnome-smoke.sh artifacts/gnome
```

The last two commands also have Make targets (`check-virtual-trackpad` and
`check-gnome`), with the same default artifact directories. Supply a different
output directory to keep named screenshots and result files. `artifacts/` is
ignored by Git; selected evidence from this run is retained in
[testing/gtk-configurator](testing/gtk-configurator).

On this machine the available test desktop was `:1`, with its own Xauthority
and session bus; the inherited shell advertised another user's display/login.
The live run explicitly selected the test desktop:

```sh
env DISPLAY=:1 XAUTHORITY=/run/user/1001/gdm/Xauthority \
  DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1001/bus \
  XDG_RUNTIME_DIR=/run/user/1001 \
  ./tests/virtual-trackpad.sh docs/testing/gtk-configurator
```

Those display numbers/paths are machine-specific. The live wrapper creates a
test-only `sitecustomize.py` so Input Remapper resolves `os.getlogin()` to the
current effective UID, including in the launcher subprocesses. This avoids
inherited multiplexer login identities selecting another user's preset directory;
it does not change `HOME` or production code. The older `make check-e2e` run on
this machine used this equivalent test-process override before unittest discovery
(with the same display/session environment shown above):

```sh
/usr/bin/python3 - <<'PY'
import os
import pwd
import unittest
os.getlogin = lambda: pwd.getpwuid(os.getuid()).pw_name
suite = unittest.defaultTestLoader.discover("tests", pattern="test_e2e_*.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
PY
```

## How the live virtual trackpad works

`tests/virtual-trackpad.py` creates a uniquely named `evdev.UInput` device with
BTN_LEFT (mechanical switch), BTN_TOUCH, BTN_TOOL_FINGER, ABS_X/Y (0–1000),
ABS_PRESSURE, and pointer/buttonpad properties. The privileged Input Remapper
service can enumerate/grab it even when the test user cannot read its event node.
The forwarded node is recognized by libinput as a touchpad, not just a keyboard
or generic absolute pointer.

The wrapper gives the configurator temporary `XDG_CONFIG_HOME` settings and a
saved selection containing only that unique device. The real configurator Start
and Apply actions write its preset and launch unmodified `run.sh`. The preset is
created under the effective user's Input Remapper directory with a unique device
name, leaving the saved physical touchpad selection/preset untouched. The test
never calls `stop_all`; cleanup stops only its launcher/injector, closes the
uinput device, removes its preset, destroys its windows, and restores the pointer.
The service's config-directory setting is shared for future injections, as in
normal project use; existing injections are kept alive by Input Remapper.

Mechanical clicks send contact/position events, wait 70 ms, press BTN_LEFT for
70 ms, then release button/contact. Region tests temporarily disable tapping
**only on the new forwarded test device**, including after each restart, to
separate mechanical routing from native tap synthesis. The tap test explicitly
enables it and sends a 60 ms contact with no BTN_LEFT. GTK records the ordinary
button-down/up pair, and XQueryPointer confirms neither button remains held.

Eight configurations cover horizontal boundaries at 25%, 75%, 49.5%, and 50.5%,
plus bottom-right restrictions whose top boundary is at 25%, 75%, or 50.5%.
Each configuration tests five points, including immediately either side of the
boundaries, and an opposite-region cancellation after every hold: **40 starts
and 40 cancellations through the real input stack**, with real Apply/restart
between configurations. The original six live tests additionally cover midpoint
crossings, keyboard grabs, independent toggles, cancellation, and terminal dragging.

## Screenshot checks

The live test opens its own neutral GTK canvas with a crosshair at the pointer
hotspot. It captures only that window's rectangle from the composited X11 root,
so actual overlay windows are included without capturing unrelated desktop content.
The assertions check rose/green center pixels (allowing a two-level compositor
rounding tolerance), the colored dot's 24×24-pixel bounds, configured offsets,
and disappearance on release. The canvas legend describes the initial 24-pixel/
100%-opacity baseline; the translucent screenshot intentionally uses different
settings from that fixed legend. A further live Apply changes size/opacity to
36 pixels/50% and checks the blended center against the released background.

GTK's root-window scale factor must be applied when moving the pointer with
`xdotool` and translating screenshot coordinates. On this desktop the canvas
is 760×440 GTK units but its screenshot is 1520×880 device pixels. X11 daemon
offsets and diameter use device pixels; Shell offsets use logical pixels.

The GNOME test starts a **private session bus**, temporary XDG data/config,
private Xvfb, and `gnome-shell --headless --wayland --no-x11 --virtual-monitor
1024x768`. It copies the extension and installed Ubuntu AppIndicators extension
into that temporary data directory. A test-only extension enables Shell Eval for
assertions, virtual-pointer motion, and Shell screenshots. It is never installed
into the real desktop; all temporary settings/extensions disappear on exit.
Notification banners are disabled only in this private settings directory.

The real Shell renderer is checked for independent colors/offsets/size, live
36-pixel/50%-opacity Configure, pointer following, hide/release state, lease expiry,
and rejection of invalid colors/sizes. The actual Python bridge and C daemon
are then started against private Xvfb. Disabling the extension must make the
bridge exit and release the held synthetic button. Finally the real Ubuntu tray
host displays the configurator icon/menu; a Clutter virtual pointer moves to
Configure and presses/releases button 1. GTK must reopen via the real D-BusMenu
protocol, rather than a direct invocation of the configurator callback. The two invalid
Configure calls intentionally produce error/stack-trace messages in the private
Shell log; those are expected validation failures.

Selected screenshots (inspect these as well as the assertions):

- [GTK click-region preview](testing/gtk-configurator/gtk-regions.png)
- [GTK indicator controls](testing/gtk-configurator/gtk-indicators.png)
- [Actual X11 left hold](testing/gtk-configurator/x11-left-held.png) and [right hold](testing/gtk-configurator/x11-right-held.png)
- [X11 released](testing/gtk-configurator/x11-right-released.png) and [translucent dot](testing/gtk-configurator/x11-translucent.png)
- [Actual GNOME left hold](testing/gtk-configurator/gnome-left-held.png), [right hold](testing/gtk-configurator/gnome-right-held.png), and [translucent dot](testing/gtk-configurator/gnome-translucent.png)
- [Actual GNOME tray menu](testing/gtk-configurator/gnome-tray-menu.png)

## True-size indicator preview regression checks

The Indicators tab now anchors the pointer hotspot at the center of its drawing
area. Offsets move only the selected dot. Dots outside the available area are
clipped; the preview never rescales or recenters its contents to fit them. X11
dots use device pixels and Shell dots use logical pixels, including the Shell
outline rings. The preview uses the desktop's themed cursor surface, preserving
its native pixel density and hotspot. `Gdk.Cursor.get_image()` can downsample the
cursor on HiDPI displays, so it is not an adequate native-size reference.

The GTK smoke test independently reads the actual display cursor with
`XFixesGetCursorImage`, composites its premultiplied pixels against the preview
background, and compares those pixels at the preview's hotspot. It also measures
24-pixel dot bounds for both backends, sets each side's offsets to extreme
values, and compares the unchanged cursor/opposite dot pixel-for-pixel. The
private Xvfb fixture has a large enough screen for the GTK window at 2× scale
and explicitly selects Adwaita, so a missing desktop cursor theme cannot silently
substitute an unrelated X server font cursor.

These checks passed at 1× and 2× GTK scale, plus a 48-pixel cursor at 2×:

```sh
./tests/gtk-smoke.sh artifacts/preview-scale1
GDK_SCALE=2 ./tests/gtk-smoke.sh artifacts/preview-scale2
GDK_SCALE=2 CTI_TEST_CURSOR_SIZE=48 ./tests/gtk-smoke.sh artifacts/preview-cursor48
```

The regular `make check`, live virtual-trackpad suite, and private GNOME suite
also passed during this change. The previously documented unchanged-axis
limitation was observed again; the short-click extra native tap did not reproduce
in this rerun. Those input-stack limitations remain unresolved.

Retained evidence, visually inspected as well as checked numerically:

- [Full Indicators tab at 2×](testing/indicator-preview/indicators-scale2.png)
- [X11 1×](testing/indicator-preview/x11-scale1.png) and [X11 2×](testing/indicator-preview/x11-scale2.png)
- [Left dot moved outside preview](testing/indicator-preview/left-moved-scale2.png) and [right dot moved outside preview](testing/indicator-preview/right-moved-scale2.png)
- [GNOME logical-pixel preview at 2×](testing/indicator-preview/gnome-scale2.png)
- [Native 48-pixel cursor at 2×](testing/indicator-preview/cursor48-scale2.png)
- [1× results](testing/indicator-preview/scale1-results.txt), [2× results](testing/indicator-preview/scale2-results.txt), and [48-pixel cursor results](testing/indicator-preview/cursor48-results.txt)
- [Live virtual-trackpad results](testing/indicator-preview/live-results.txt) and [GNOME results](testing/indicator-preview/gnome-results.txt)

## Dragging indicator dots

The preview accepts primary-button drags on either circle. A drag preserves the
grab point, updates that side's two spin buttons, and keeps the cursor/opposite
dot fixed. It uses the same backend coordinate conversion as rendering, clamps
to the supported −512…512 offsets, and continues when the pointer leaves the
preview. Where circles overlap, the right dot is visually on top and receives
the drag. Clicking/dragging empty space changes neither dot. Changes remain in
the form until Apply or Start saves them, just like numeric edits.

The GTK smoke test uses actual XTest pointer motion/button events through
`xdotool`, not direct gesture callback calls. It drags both sides for both
backends at 1× and 2× scale, grabs off-center to check for jumps, compares cursor
and opposite-dot screenshot pixels, checks release, overlap, empty space, and
clamping outside the preview, then verifies Apply persisted the dragged offsets.
These checks passed using the same `gtk-smoke.sh` commands documented above.

The live virtual-trackpad test also performs a preview drag through the real
input stack. It places the pointer on the right preview dot, sends a settled
contact and mechanical left-region click through the kernel device/Input
Remapper/C daemon, moves the pointer while the synthetic left hold is active,
and checks the changed right offsets. A second mechanical click must release
the hold and end the GTK gesture. The contact settles for 250 ms before clicking
to isolate this check from the previously observed short-contact tap interaction.
The subsequent 40 region/cancellation cases and renderer checks still pass.

Evidence retained for this change:

- [X11 dot dragged at 2×](testing/indicator-drag/x11-drag-scale2.png)
- [GNOME dot dragged at 2×](testing/indicator-drag/gnome-drag-scale2.png)
- [Drag using a real virtual-trackpad toggle hold](testing/indicator-drag/virtual-trackpad-drag.png); this frame includes the real daemon's held-button dot in addition to the two preview dots
- [1× GTK results](testing/indicator-drag/scale1-results.txt), [2× GTK results](testing/indicator-drag/scale2-results.txt), [live results](testing/indicator-drag/live-results.txt), and [private GNOME results](testing/indicator-drag/gnome-results.txt)

## Discard, Apply sensitivity, and Ctrl+Q

The configurator retains a snapshot of the last successfully saved form values
and the backend choice for this session. Discard edits restores that snapshot,
including dragged offsets, colors, region options, numeric text, and backend.
Apply and Discard are disabled while the form matches the snapshot or an
operation is busy. Typed spin-button text also counts as an edit before Enter
or focus loss; Apply commits that text before validating/saving. Returning to
the saved values makes Apply grey again. Failed saves retain edits and the old
snapshot; a successful save updates it. If startup cannot load a valid settings
file, Apply remains available to repair it with valid form values.

Ctrl+Q activates a window action that follows the existing close-to-tray path.
It hides the settings window, retains pending edits, and leaves the tray and
any running toggle child alive. The tray's Configure action reopens the same
form. The tray menu's Quit still stops toggles and exits the application.

The GTK smoke test passed at 1× and 2×, checking clean/edit/manual-revert states,
raw unfinished numeric text, colors/checkboxes/backend discard, backend-only
changes, floating-point step round-off, successful/failed saves, reset/discard,
and persistence of typed/dragged values. Actual Ctrl+Q key events were sent with
focus in a visible spin control, both before starting and during a held synthetic
right button; the latter must leave the child PID and held button unchanged.
`xdotool --clearmodifiers` is intentionally not used for that check because it
also clears held mouse buttons. Regular `make check` and the private GNOME suite
passed as well.

The first live virtual-trackpad rerun for this change was **blocked**, not passed:
an existing configurator and toggle instance were running on the test desktop.
The runner now checks the session bus before creating a test device and reports
that prerequisite instead of activating the existing app or failing later with
an empty remote form. That session was left running during the blocked attempt.

**Follow-up live rerun:** After the user closed the window and requested the live
tests, the remaining background tray/toggle instance was stopped with SIGTERM
and allowed to release its buttons and injector cleanly. The full live
virtual-trackpad suite then passed: real toggle-hold preview dragging, all 40
region starts/cancellations, repeated Apply/restart, independent indicator
color/position/diameter, 50% opacity, ordinary tap-to-click, Stop/release, and
saved settings. The unchanged-axis startup fallback limitation reproduced again;
the short-click extra native tap did not reproduce in this run. The original
live suite also passed all six tests, including keyboard-grab handling and
terminal titlebar dragging. Test devices/presets were removed, buttons were
released, and the pointer was restored. The previously closed application was
not restarted after testing.

Evidence:

- [Unedited form: Apply/Discard disabled](testing/edit-controls/clean-scale2.png)
- [Edited form: Apply/Discard enabled](testing/edit-controls/dirty-scale2.png)
- [1× GTK results](testing/edit-controls/scale1-results.txt) and [2× GTK results](testing/edit-controls/scale2-results.txt)
- [Regular checks](testing/edit-controls/check-results.txt), [private GNOME results](testing/edit-controls/gnome-results.txt), and [blocked live run](testing/edit-controls/live-blocked.txt)
- [Successful follow-up live results](testing/edit-controls/live-results.txt) and [all six original live tests](testing/edit-controls/e2e-results.txt)
- [Current UI dragged through the real input stack](testing/edit-controls/live-drag.png) and [actual 50%-opacity indicator](testing/edit-controls/live-translucent.png)

## Findings and remaining checks

The live tests exposed a launcher race that mock tests could not: Input Remapper
acknowledges Start/Stop before the injector has completed its grab/release.
Starting the replacement immediately could lose its forwarded device or race the
old grab. `daemon_action` now polls for RUNNING on start and a terminal stopped
state on stop, reports failures, and has a five-second timeout. A regression test
covers state transitions and failed grabs; repeated real Apply cycles validate
this against the running service.

The 50%-opacity X11 screenshot also caught an existing XRender bug: solid-fill
RGB channels were not premultiplied by alpha, so translucent colors appeared
washed out or saturated. The renderer now premultiplies RGB; screenshot assertions
compare its blended center against the same canvas without the dot.

Gdk 3 is now also explicitly selected alongside
GTK 3 to avoid accidentally importing Gdk 4 on systems with both installed.

Two input-stack limitations were observed and are deliberately not hidden by the
mechanical-routing PASS results:

1. With tapping enabled, a sufficiently short mechanical click can also be
   interpreted by libinput as an ordinary left tap. The mechanical button was
   remapped to a keyboard key, so the forwarded contact stream cannot tell
   libinput that this contact mechanically clicked. A 70 ms pre-contact plus
   70 ms mechanical right click reproduced an extra native left press alongside
   the held right button. Ordinary tap-only contacts still work without latching.
   The final runner records whether this timing-sensitive extra tap reproduced.
2. After injector restart, a repeated position can produce no fresh ABS event
   because the kernel filters unchanged values. Input Remapper's axis-combination
   state is initially inactive, so a click at that unchanged right-side position
   can use the fallback left mapping. Moving the virtual contact one unit before
   clicking primes the axis and restores correct routing. The appearance test
   records this case before priming; it does not call that first click a PASS.

Neither issue is resolved by the configurator changes. They need input-backend
work and physical-device reproduction. Tests may exit successfully while
reporting `KNOWN LIMITATION`; read the result files, not just the exit code.

Still unverified: actual clickpad firmware/mechanical timing, physical tapping
and palm rejection, perceived cursor/dot lag, fractional scaling, mixed-DPI
multiple monitors, fullscreen applications, actual session locking/unlocking,
and GNOME X11 compositor behavior end-to-end with the virtual kernel trackpad.
Extension disable is a cleanup test, not a claim that a real lock cycle passed.
