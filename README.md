# click-toggle-indicator

An Ubuntu X11 utility that turns the touchpad's mechanical left and right clicks into
click-to-hold controls:

1. when no button is held, a physical click on the left or right half holds the
   corresponding mouse button;
2. while either button is held, the next physical click anywhere on the clickpad
   releases it without pressing another button;
3. a translucent blue dot appears left or right of the cursor for the corresponding
   held button.

Ordinary tap-to-click continues to behave normally.

## How click and tap are separated

The kernel reports the mechanical switch as `BTN_LEFT` (event code **272**) and touch
contact as `BTN_TOUCH` (code **330**). Input Remapper changes code 272 to the
otherwise-unused keyboard key `KEY_F24` (code 194). Xorg receives that evdev key as
raw X11 keycode 202 (`194 + 8`), which the daemon grabs without requiring a keysym in
the active keyboard layout. A higher-priority combination of `ABS_X` in the right
half and `BTN_LEFT` is mapped to `KEY_F19` (189 / raw X11 keycode 197). One daemon
handles both keys so a finger crossing the midpoint while the switch is pressed
cannot toggle both buttons. Code 330 is never remapped.

## Requirements

- an Ubuntu **X11** session (not Wayland);
- Input Remapper, `gcc`, `make`, `pkg-config`, and Python 3;
- development packages for Xlib, XInput, XTest, XFixes, Xext, and Xrender.

```sh
sudo apt install input-remapper build-essential pkg-config \
  libx11-dev libxi-dev libxtst-dev libxfixes-dev libxext-dev libxrender-dev
```

Make sure the Input Remapper service is running. Installing the package normally
configures it; if needed:

```sh
sudo systemctl enable --now input-remapper
```

## Set up, build, and run

```sh
./setup.sh
make
./run.sh
```

`setup.sh` first checks Input Remapper device groups. If ordinary user permissions
hide them, it uses `pkexec` to run Input Remapper's own read-only device listing with
the same visibility as its daemon. It saves the selection and installs a narrowly
scoped preset in your user configuration. It refuses to overwrite a different preset
with the same name unless passed `--force`.

If more than one matching device exists, use one of the exact root-visible keys shown
by setup (normally also shown in the Input Remapper GUI):

```sh
INPUT_REMAPPER_DEVICE='Your Touchpad Name' ./setup.sh
INPUT_REMAPPER_DEVICE='Your Touchpad Name' ./run.sh
```

The launcher talks directly to Input Remapper's privileged D-Bus service. It does not
use the CLI's local `/dev/input` scan, which can legitimately return no devices for an
unprivileged desktop user.

Stop with Ctrl-C. The launcher stops its Input Remapper injection, and the daemon
always releases a held left button when exiting.

The indicator is translucent blue by default. Customize it by passing daemon options
through the launcher:

```sh
./run.sh --color '#22c55e' --opacity 0.8 --size 22 --offset-x 24 --offset-y 12
```

## GTK configurator and tray icon

Install the optional GTK/tray dependencies, then launch the configurator:

```sh
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
make
./configure.sh
```

On GNOME, enable the Ubuntu AppIndicators extension (package
`gnome-shell-extension-appindicator`) so the tray icon is visible. The tray menu
opens **Configure…**, starts/stops toggles, and quits. Closing the settings window
leaves the tray running; Ctrl+Q closes the configuration window the same way.
The tray menu’s Quit releases held buttons and stops injection.
`./configure.sh --tray` starts with the window hidden. Starting the configurator
does not enable input injection until you choose Start.

The **Click regions** tab previews the touchpad. Set where right click begins as a
percentage from the left. Enable **Restrict right click to the bottom-right corner**
and choose where that rectangle begins from the top. Everything outside the blue
rectangle produces left click. Input Remapper supports half-percent increments;
its signed axis thresholds cannot express exactly 50%, so the controls skip from
49.5% to 50.5% (the original default). ABS_X/ABS_Y must increase left-to-right and
top-to-bottom, as on ordinary clickpads.

The **Indicators** tab sets independent left/right colors and horizontal/vertical
cursor offsets, plus shared diameter and opacity. Offsets measure from the pointer
hotspot to the dot’s top-left; negative values move left/up. The preview shows both
dots together at actual size, with the desktop’s themed cursor anchored in the
center. Drag either dot with the primary mouse button to change its position;
the numeric offsets update as you drag. Click Apply to save. Changing one dot’s
offset moves only that dot; distant dots are clipped
at the preview’s edges. X11 dimensions use device pixels and GNOME dimensions
use logical pixels, matching their respective displays. Only the held button’s
dot appears during use.

**Discard edits** restores the last saved settings and the last applied backend
choice for this session. **Apply** is greyed out while the form matches those
values, and becomes available when you edit a control or drag a dot. Edits remain
in the form when the window is closed; Discard explicitly removes them.

**Apply** saves settings and updates the preset for the selected touchpad. If this
tray app is running toggles, it stops them, releases any hold, and restarts with the
new settings. **Start** also applies the form. Run `./setup.sh` first to select a
device, especially if detection is ambiguous. Errors appear below the controls;
manually edited or unrelated presets remain protected from replacement.
Stop any separately launched `run.sh`/`run-gnome.sh` before starting from the tray.
A launcher lock prevents multiple input daemons from running simultaneously.

Settings live in `~/.config/click-toggle-indicator/settings.json` (or under
`XDG_CONFIG_HOME`). Both command-line launchers read saved appearance settings;
`run.sh` arguments override those values for that invocation. `--color` and
`--offset-y` affect both indicators; put `--right-color`/`--right-offset-y` after
them to override the right indicator separately. Region settings are
written to the Input Remapper preset on Apply or `./setup.sh`. Choose **X11 overlay**
or **GNOME Shell extension** for the current tray session; the GNOME backend requires
the extension below. After updating this checkout, reinstall the extension and log
out/in once to load its new configuration interface.

## Test

See [docs/TESTING.md](docs/TESTING.md) for real virtual-trackpad tests, isolated
GNOME/tray screenshot checks, captured evidence, and known input-stack limitations.


```sh
make check
```

For the optional GTK smoke test (also needs `dbus-run-session`, `xvfb-run`,
`python3-pil`, and the Adwaita cursor theme):

```sh
make check-gui
# Optionally keep preview screenshots:
./tests/gtk-smoke.sh /tmp/click-toggle-screenshots
```

This runs on a private X server and D-Bus session. It checks window/tray actions,
saving, daemon restart, release on Stop, and rollback; physical-device injection is
mocked.

Settings tests also exercise generated regions through Input Remapper’s real event
pipeline using mocked input/output devices. They do not inject desktop events.

The integration test uses Xvfb when installed and otherwise reports a skip. Hardware
event separation can be inspected with `sudo evtest`: a physical click should show
code 272, while finger contact shows code 330.

For an end-to-end test on a live X11 desktop, stop any running toggle instances and run:

```sh
sudo apt install gnome-terminal xdotool x11-utils
make check-e2e
```

This test requires Input Remapper, Python `evdev`, GNOME Terminal, `xdotool`, `xwininfo`, `xprop`,
and write access to `/dev/uinput`.
It creates a temporary virtual touchpad and preset, sends physical-style clicks
through Input Remapper, and checks both synthetic mouse buttons. It also checks
left-click toggling while another X11 client grabs the keyboard and drags a
private GNOME Terminal window by its titlebar. The test removes its device and preset
when finished; it does not change the saved touchpad selection.

See [DESIGN.md](DESIGN.md) for the explored implementation alternatives.

## GNOME Shell indicator prototype

The `prototype/gnome-shell-indicator` branch includes an alternative display for
**GNOME Shell 46 on X11**. A Shell actor follows the pointer on the compositor's
frame clock, drawing an antialiased blue dot with a light/dark outline. Application
cursors (text, resize, links, drag, animated cursors) remain under application control.
The original daemon still handles mechanical clicks, taps, and synthetic buttons;
this prototype does **not** add Wayland input support.

Install the extension and the Python GObject bindings:

```sh
sudo apt install python3-gi
make
./tools/install_gnome_extension.sh
```

Log out and back in so GNOME discovers the extension, then enable it:

```sh
gnome-extensions enable click-toggle-indicator@personal-utilities
```

After the usual `./setup.sh`, stop any running `./run.sh` instance and launch:

```sh
./run-gnome.sh
```

Ctrl-C stops the daemon, releases the held button, hides the dot, and stops the
Input Remapper injection. Disabling the extension (including on session lock)
makes the bridge stop the daemon; restart `./run-gnome.sh` after unlocking.
The original `./run.sh` still uses the X11 indicator for comparison.

The prototype reads the saved appearance settings at startup. Use the GTK
configurator to change colors, offsets, size, and opacity. Launcher appearance flags
are not supported by `run-gnome.sh`; use `run.sh` for command-line overrides. The
Shell dot keeps its offset at screen edges, so it may be partially offscreen; the
X11 overlay moves back onto the screen at the edges.

Movement is updated once per compositor frame while held; a hardware cursor can
still move ahead of a separately rendered actor. This removes the external X11
window-following loop but does not guarantee zero visible lag. Active holds also
keep the frame clock running, even when the pointer is stationary.

`make check` covers the original input behavior, the external display state stream,
and release on bridge loss. The extension has also been checked in an isolated
GNOME 46 compositor for loading, pointer offsets, rendering, expiry, and cleanup.
The real daemon-to-Shell bridge and button release on extension disable were also
verified using a private X server.
Physical touchpad behavior, perceived lag, fractional scaling, multiple monitors,
fullscreen applications, and locking still need validation on the target desktop.

To return to the original display, stop `run-gnome.sh` and use `./run.sh`. To disable
the prototype extension:

```sh
gnome-extensions disable click-toggle-indicator@personal-utilities
```
