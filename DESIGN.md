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
