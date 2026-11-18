# Bug review

Review performed on 2026-11-17/18 against this checkout. `make check` passed all
three Xvfb checks. Additional checks used Xvfb, Xephyr, and temporary virtual
touchpads with Input Remapper 2.0.1. The virtual touchpads included separate
mouse-button and touch-position event nodes, like the physical device on the
review machine. Physical clicks and tap-to-click on that device were not tested.

**#1 — Click crosses the midpoint while held:** reported fixed by the user.
Reproduction steps are omitted as requested.

## Common isolated X11 setup

Build with `make`, then use a fresh `xvfb-run -a bash` shell for each applicable
case below. In that shell, run:

```bash
export XDG_SESSION_TYPE=x11
xmodmap -e 'keycode 202 = F24'
xmodmap -e 'keycode 197 = F19'
pointer_id=$(xinput list --id-only 'Virtual core XTEST pointer')
```

These commands keep synthetic button holds away from the live desktop. Stop a
test daemon after each case. For a virtual touchpad test, use an isolated X11
session and remove its temporary Input Remapper preset and device afterward.

## #2 — A second launcher stops the first launcher's injection

**Impact:** The first launcher stays alive, but physical clicks stop reaching it.
The second launcher's unconditional `--stop` in [run.sh](run.sh) acts on the same
device. Input Remapper 2.0.1 also stops an existing injection when a new
`start_injecting` request for that device arrives.

**Reproduce without changing the live remapper:** In the isolated Xvfb shell,
run:

```bash
tmp=$(mktemp -d)
cp run.sh click-toggle-indicator "$tmp/"
mkdir "$tmp/tools"
cat > "$tmp/tools/configure_input_remapper.py" <<'PY'
import sys
from pathlib import Path

Path('/tmp/cti-launch-actions.log').open('a').write(sys.argv[1] + '\n')
PY
: > /tmp/cti-launch-actions.log
"$tmp/run.sh" > /tmp/cti-first.log 2>&1 & first=$!
sleep 0.3
"$tmp/run.sh" > /tmp/cti-second.log 2>&1
cat /tmp/cti-launch-actions.log
kill -0 "$first" && echo 'first launcher still running'
kill "$first"
wait "$first"
```

The actions before stopping the first launcher are `--start`, `--start`,
`--stop`. The second launcher reports X11 grab errors, yet the first remains
running. With the real service, that `--stop` stops its injection.

For a direct service check, use only a disposable virtual touchpad and its
temporary preset: start two real launcher instances against that device, then
query `Daemon.get_state(group_key)` after the second exits. The first launcher
should still be alive while the device's injection reports stopped. This
service check was not run against the live touchpad during the review.

## #3 — Mouse-button trigger cannot release its own hold

**Scope:** This affects the optional `--toggle-button` mode, not the F24/F19
triggers used by `run.sh`.

**Reproduce:** In the isolated Xvfb shell:

```bash
./click-toggle-indicator --toggle-button 8 --hold-button 1 & daemon=$!
sleep 0.2
xdotool click 8
sleep 0.1
xinput query-state "$pointer_id" | rg 'button\[1\]'
xdotool click 8
sleep 0.1
xinput query-state "$pointer_id" | rg 'button\[1\]'
kill "$daemon"
wait "$daemon"
```

Both queries say `button[1]=down`; the second trigger should release it. The
same result occurred when the trigger came from Xephyr's separate mouse device.
The relevant passive grab is in [src/click-toggle-indicator.c](src/click-toggle-indicator.c).

## #4 — Queued key presses can collapse into one toggle

**Scope:** Ordinary clicks processed separately worked. This needs two click
cycles to reach the daemon before it can rearm, such as after a scheduling stall.

**Reproduce:** In the isolated Xvfb shell:

```bash
./click-toggle-indicator --toggle-keycode 202 & daemon=$!
sleep 0.2
xdotool key --repeat 2 --delay 0 202
sleep 0.1
xinput query-state "$pointer_id" | rg 'button\[1\]'
kill "$daemon"
wait "$daemon"
```

The query says `down`, although two toggles should end `up`. A second test
paused the daemon, sent two full key cycles 100 ms apart, then resumed it;
that also ended `down`. The [event loop](src/click-toggle-indicator.c) ignores
the core key releases delivered by its passive grab and checks the keymap only
after draining queued events.

## #5 — An unexpected child exit can strand a synthetic button

**Reproduce:** In the isolated Xvfb shell:

```bash
./click-toggle-indicator --toggle-keycode 202 & daemon=$!
sleep 0.2
xdotool key 202
xinput query-state "$pointer_id" | rg 'button\[1\]'
kill -KILL "$daemon"
wait "$daemon" 2>/dev/null
xinput query-state "$pointer_id" | rg 'button\[1\]'
xdotool mouseup 1  # Release the test server's stranded button.
```

The button remains `down` after the child dies. Killing the child of a
disposable `run.sh` copy produced the same result after launcher cleanup.
Normal SIGTERM shutdown released the button correctly. See the
[launcher cleanup](run.sh) and the daemon's [normal release](src/click-toggle-indicator.c).

## #6 — First stationary right-side click can select left

**Precondition:** Input Remapper begins injection while the touchpad's ABS_X
value is in the right half, and no changed ABS_X event arrives before the
mechanical switch event.

**Reproduce:** On an isolated X11 session with writable `/dev/uinput`, create a
temporary virtual touchpad with `ABS_X` range 0–1000 and initial value 900,
`ABS_Y`, `BTN_TOUCH`, and `BTN_LEFT`. Install the project's `PRESET` for that
device and start injection. Send `BTN_TOUCH=1`, then `BTN_LEFT=1` and
`BTN_LEFT=0`, without changing ABS_X. Monitor `xinput test-xi2 --root`, or run
both indicator daemons and query their buttons. The output is F24/button 1,
not F19/button 3. The result also reproduced when `BTN_LEFT` and ABS_X came
from separate virtual event nodes. See the [preset](tools/configure_input_remapper.py).

The event sequence for a Python `evdev.UInput` device is:

```python
device.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, 1)
device.syn()
device.write(ecodes.EV_KEY, ecodes.BTN_LEFT, 1)
device.syn()
device.write(ecodes.EV_KEY, ecodes.BTN_LEFT, 0)
device.syn()
```

## #7 — Indicator can move outside the screen after a resize

**Reproduce:** On an X11 desktop, with display `:98` free:

```bash
Xephyr :98 -screen 800x600 -ac & xephyr=$!
sleep 0.2
DISPLAY=:98 xmodmap -e 'keycode 202 = F24'
DISPLAY=:98 ./click-toggle-indicator --toggle-keycode 202 \
    --size 40 --offset-x 30 --offset-y 30 & daemon=$!
sleep 0.2
DISPLAY=:98 xrandr -s 320x240
DISPLAY=:98 xdotool mousemove 300 220 key 202
sleep 0.1
DISPLAY=:98 xwininfo -root -tree
kill "$daemon"
wait "$daemon"
kill "$xephyr"
wait "$xephyr"
```

The mapped 40×40 window is at `+330+250`, beyond the 320×240 screen. Toggling
it off and on does not fix its position. [move_indicator](src/click-toggle-indicator.c)
uses screen dimensions cached before the resize. Stop the test Xephyr server
afterward if the script was interrupted.

## #8 — XInput-only touchpad discovery can return unusable names

**Precondition:** Unprivileged evdev enumeration and the privileged `pkexec`
probe are unavailable.

**Reproduce:** On a live X11 desktop with Input Remapper's forwarded touchpad,
run `xinput list --name-only | rg -i 'touchpad|clickpad|trackpad'`. On the review
machine this returned both the physical and forwarded touchpads, while the
saved Input Remapper group key was the device's `Mouse` name. To force the
fallback without invoking `pkexec`, run:

```python
import sys
from types import SimpleNamespace

sys.path.insert(0, 'tools')
import configure_input_remapper as m

m.groups = SimpleNamespace(filter=lambda: [])
m.privileged_groups = lambda: []
m.find_group(use_saved=False)
```

It raises `Multiple touchpads were found`. Even a single XInput name can differ
from the Input Remapper group key. See [xinput_groups](tools/configure_input_remapper.py).

## #9 — Preset replacement protections are inconsistent

**Reproduce without touching the real preset:** Run this from the repository
root:

```python
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, 'tools')
import configure_input_remapper as m

with tempfile.TemporaryDirectory() as directory:
    m.CONFIG_PATH = directory
    m.SELECTION_PATH = Path(directory) / 'device.json'
    group = SimpleNamespace(key='test', name='test')
    path = m.preset_path(group)
    path.parent.mkdir(parents=True)

    legacy = [dict(m.LEGACY_PRESET[0], release_combination_keys=False)]
    path.write_text(json.dumps(legacy))
    m.install(group, force=False)
    print('custom setting lost:', json.loads(path.read_text()) == m.PRESET)

    path.write_text('{')
    try:
        m.install(group, force=True)
    except RuntimeError as error:
        print('force rejected corrupt preset:', error)
```

Run it as `python3` with the code saved to a temporary file, or paste it into
a Python prompt. The first case prints `True`; the second raises a read error
instead of replacing the file.

The permissive legacy check and the unconditional JSON read are in
[configure_input_remapper.py](tools/configure_input_remapper.py).

## #10 — A documented offset override makes both indicators overlap

**Reproduce:** Use the disposable launcher setup from #2, then run its
`run.sh --offset-x 24` in the isolated Xvfb shell. Run
`xdotool mousemove 200 200 key 202 key 197`, wait 0.1 seconds, then run
`xwininfo -root -tree`. Both 18×18 indicator windows have the same coordinates
(at pointer position 200,200, both mapped at `+224+218`). The final argument
overrides each instance's distinct offset in [run.sh](run.sh).

## #11 — Opacity has no visible effect without a compositor

**Reproduce:** In an isolated Xvfb shell, which has no compositor:

```bash
xsetroot -solid white
./click-toggle-indicator --toggle-keycode 202 --opacity 0.05 \
    --size 40 --offset-x 30 --offset-y 30 & daemon=$!
sleep 0.2
xdotool mousemove 100 100 key 202
sleep 0.1
import -window root /tmp/cti-opacity.png  # ImageMagick, if installed.
kill "$daemon"
wait "$daemon"
```

Inspect the captured indicator centered at 150,150. Its center is full blue
`(59,130,246)`, rather than a blue/white blend. [Rendering](src/click-toggle-indicator.c)
relies on ARGB compositing, but the README does not list a compositor
requirement.

## #12 — NaN passes opacity validation and causes undefined conversion

**Reproduce:** In the isolated Xvfb shell, build and run a sanitizer variant:

```bash
cc -O1 -g -fsanitize=undefined,float-cast-overflow \
    -fno-sanitize-recover=all -std=c11 \
    $(pkg-config --cflags x11 xi xtst xfixes xext xrender) \
    src/click-toggle-indicator.c -o /tmp/cti-ubsan \
    $(pkg-config --libs x11 xi xtst xfixes xext xrender)
/tmp/cti-ubsan --toggle-keycode 202 --opacity NaN & daemon=$!
sleep 0.2
xdotool key 202
wait "$daemon"
```

The program accepts `NaN`; triggering the indicator reports a runtime error
at the [floating-point to integer alpha conversion](src/click-toggle-indicator.c).
