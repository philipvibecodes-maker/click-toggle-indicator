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

## Test

```sh
make check
```

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

The prototype uses an 18-pixel circle whose center is 28 logical pixels to the left
or right of the pointer hotspot and 18 pixels below it. Change the constants and
colors in `gnome-extension/extension.js`, reinstall, and log out/in to reload.
Launcher appearance flags are not supported by `run-gnome.sh` yet. The dot keeps
its offset at screen edges, so it may be partially offscreen.

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
