# Repository Guidelines

## Project Structure & Module Organization

`src/click-toggle-indicator.c` contains the X11 daemon and cursor indicator. `tools/configure_input_remapper.py` selects a touchpad, writes the Input Remapper preset, and starts or stops injection. `setup.sh` installs that preset; `run.sh` launches the shared toggle daemon. `tools/configurator.py` provides the GTK window/tray app, and `tools/settings.py` validates the shared settings. `tests/integration-xvfb.sh` exercises both toggles in a virtual X server. `README.md` covers installation and use, while `DESIGN.md` explains the input-event architecture. The root `click-toggle-indicator` executable is a generated build artifact.

## Build, Test, and Development Commands

- `./setup.sh`: detect the touchpad and install the user-level Input Remapper preset. Set `INPUT_REMAPPER_DEVICE='Exact Device Name'` when detection is ambiguous.
- `make`: compile the C daemon with C11 and the X11/XTest/XFixes/Xext/Xrender libraries.
- `./run.sh`: start Input Remapper injection and both indicator instances in an X11 session; Ctrl-C stops them.
- `make check`: build, validate settings/preset routing, and run the Xvfb integration test.
- `make check-gui`: GTK lifecycle tests on private Xvfb/D-Bus, with physical injection mocked.
- `make check-e2e`: real virtual touchpad and Input Remapper tests on a live X11 desktop.
- `./tests/virtual-trackpad.sh artifacts/virtual-trackpad`: real configurator/injection tests and screenshots; requires a live X11 desktop and writable `/dev/uinput`.
- `./tests/gnome-smoke.sh artifacts/gnome`: private GNOME 46 compositor, real tray host/bridge, and screenshot checks.
- `make clean`: remove the compiled executable.

Install the packages listed in `README.md` before building. The integration test also needs Xvfb, `xdpyinfo`, `xmodmap`, `xinput`, and `xdotool` to run fully.

## Coding Style & Naming Conventions

Follow the surrounding code: four-space indentation in C, Python, and Bash; `snake_case` for C and Python functions and variables; uppercase names for constants. Keep shell scripts in Bash with `set -euo pipefail`. Build with the Makefile's `-Wall -Wextra -Wpedantic` flags and resolve new warnings. No formatter or linter is configured; preserve existing formatting and keep changes focused.

## Testing Guidelines

Run `make check` for changes to toggle behavior or X11 rendering. The test is a shell script under `tests/` and checks that F24 and F19 independently press and release synthetic mouse buttons. It reports `SKIP` when Xvfb is absent; confirm a `PASS` result when changing behavior. For touchpad mapping changes, also verify physical clicks and tap-to-click on an X11 machine. There is no stated coverage threshold.

### Remember virtual-device and screenshot testing

For changes to click regions, injection lifecycle, the configurator/tray, or either
indicator renderer, run the virtual-trackpad and screenshot tests when their
prerequisites are available. Do not stop at mocked tests or injected F19/F24 keys:
those skip evdev, Input Remapper device grabs, libinput classification/tapping,
and the real desktop tray host. Confirm PASS results; record failures, skipped
checks, and known limitations rather than describing untested behavior as verified.

Follow [docs/TESTING.md](docs/TESTING.md) for the test architecture, reproducible
commands, prerequisites, screenshots, and findings. Inspect the captured images
with an image viewer as well as checking pixel assertions. Preserve useful
screenshots and results for visible changes. Use only a unique temporary uinput
trackpad/preset and temporary configurator settings; stop its injector, release
held buttons, destroy the device, and restore pointer position during cleanup.
The live test moves the pointer and opens its own canvas, so use a test desktop
and stop other toggle instances on that DISPLAY. The GNOME test runs an isolated
compositor/D-Bus session; its test-only Shell Eval driver must never be installed
in the user’s real extension directory. Respect GTK/device-pixel scaling when
checking screenshot positions.

A kernel-created trackpad can exercise real taps, but it cannot validate a
physical clickpad’s firmware, mechanical timing, contact geometry, perceived
lag, or every monitor/scaling arrangement. Keep those remaining checks explicit.

## Commit & Pull Request Guidelines

Git history is unavailable in this checkout, so no existing commit convention can be confirmed. Use short, imperative subjects such as `Fix right-click toggle cleanup`. Pull requests should explain the behavior changed, include the `make check` result, and note any hardware validation. Link a related issue when one exists; include a screenshot or short recording for visible indicator changes.
