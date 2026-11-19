# Design alternatives

Linux reports the mechanical switch as `EV_KEY/BTN_LEFT` (code 272), while touch
contact used by tap-to-click is `BTN_TOUCH` (code 330). XInput sees both only after
libinput has converted them to logical button behavior, so XInput remapping alone
cannot reliably distinguish them.

## 1. Input Remapper bridge + X11 grab + XTEST (implemented)

Input Remapper changes ordinary `BTN_LEFT` 272 to the otherwise-unused keyboard key
F24. A higher-priority combination of right-half `ABS_X` and `BTN_LEFT` emits F19
for clicks anywhere on the right half of the clickpad.
`BTN_TOUCH` 330 is forwarded unchanged. Xorg exposes evdev `KEY_F24` 194 as raw X11
keycode 202; the daemon grabs that keycode directly, toggles logical button 1 through
XTEST, and displays an input-transparent cursor indicator. A keyboard
trigger is used because it remains grabbable while synthetic mouse button 1 is held;
a passive mouse-button grab cannot reliably receive the release toggle in that state.
One daemon receives both keycodes and treats a key transition during one switch press
as one click, including a brief release between the two key events.
When either synthetic button is held, the next physical click releases it regardless
of which half emits the trigger. Only a click starting with no held button can begin
a new hold.

- **Advantages:** correctly separates click from tap, preserves gestures, and relies
  on Input Remapper for privileged device forwarding and hot-plug behavior.
- **Costs:** requires Input Remapper and X11.
- **Fit:** selected implementation.

### GNOME Shell display prototype

The optional `--state-stdout` mode keeps the same X11 input handling but creates no
indicator windows. It emits newline-delimited `0` (off), `1` (left), or `2` (right)
on startup, state transitions, and shutdown. These are sides, independent of the
configured synthetic button numbers. If its output pipe loses its reader, the
daemon exits through its normal synthetic-button cleanup.

`tools/gnome_indicator_bridge.py` launches that mode, forwards each state over the
session bus to the extension's `SetState(u)` method on `org.gnome.Shell`, and renews
the display state every 500 ms. Pointer coordinates never pass through this bridge.
The extension hides stale state after two seconds. Failure to reach the extension
stops the daemon, releasing any held button; the existing launcher then stops
Input Remapper. Default extension lifecycle behavior disables the display on lock.

The extension uses a nonreactive `St.DrawingArea` in Shell's top chrome, with no
input region, and a `Clutter.Timeline` tied to the actor. While held, each frame
reads the current pointer position and applies a fixed offset directly. Cairo draws
the circle with antialiased alpha edges and contrasting outline rings. It neither
replaces nor hides the native cursor. A separate actor can still trail a hardware
cursor; the prototype is intended to evaluate how much this improves perceived lag.
The frame clock stops when the display is off. The current prototype targets Shell
46 and retains the X11 input backend; Wayland input would need a separate design.

## 2. Dedicated `libevdev` + `uinput` bridge

Exclusively clone the touchpad into a virtual device, translating only code 272.

- **Advantages:** self-contained and exact event handling.
- **Costs:** requires `/dev/uinput` permission, careful virtual-device recreation, and
  more responsibility for device discovery and lifecycle behavior.

## 3. Disable tapping + XInput remap

Disable libinput tapping temporarily, then remap X11 button 1 to a spare button.

- **Advantages:** very little native code and no low-level device access.
- **Costs:** tap-to-click stops working and user preferences must be restored safely.

## 4. Desktop automation

Use `xbindkeys` plus `xdotool mousedown`/`mouseup` and a separate overlay.

- **Advantages:** quick prototype.
- **Costs:** still needs click/tap separation, state files can race, and crashes can
  strand the synthetic button state.

## 5. Xorg/libinput modification

Implement toggle semantics inside the input stack.

- **Advantages:** clean source-level event semantics.
- **Costs:** system-wide installation, ABI sensitivity, and high maintenance burden.
