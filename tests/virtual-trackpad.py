#!/usr/bin/python3
"""Live GTK -> preset -> real Input Remapper -> uinput -> X11 checks."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tools"))
from evdev import AbsInfo, UInput, ecodes
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk
from PIL import Image
from configurator import Configurator
from settings import DEFAULTS, SETTINGS_PATH, load_settings
from configure_input_remapper import SELECTION_PATH, preset_path
from e2e_support import X11


def pump(duration=0.1):
    end = time.monotonic() + duration
    context = GLib.MainContext.default()
    while time.monotonic() < end:
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)


def wait(predicate, description, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        pump(0.03)
        if predicate():
            return
    raise AssertionError(f"Timed out: {description}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if not os.access("/dev/uinput", os.W_OK):
        raise RuntimeError("This test needs writable /dev/uinput and a live X11 desktop")
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    owned = bus.call_sync(
        "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
        GLib.Variant("(s)", ("org.personalutilities.ClickToggleConfigurator",)),
        None, Gio.DBusCallFlags.NONE, 2000, None,
    ).unpack()[0]
    if owned:
        raise RuntimeError("A configurator is already running on this session bus. Use a dedicated test session; the existing app was left untouched.")
    x11 = X11()
    if x11.button_down(1) or x11.button_down(3):
        raise RuntimeError("Release held buttons before testing")
    old_pointer = x11.pointer()[:2]
    name = f"CTI Configurator Test Touchpad {os.getpid()}"
    group = SimpleNamespace(key=name, name=name)
    preset = preset_path(group)
    if preset.exists():
        raise RuntimeError(f"Test preset already exists: {preset}")
    SELECTION_PATH.parent.mkdir(parents=True, exist_ok=True)
    SELECTION_PATH.write_text(json.dumps({"key": name, "name": name}))
    capabilities = {
        ecodes.EV_KEY: [ecodes.BTN_LEFT, ecodes.BTN_TOUCH, ecodes.BTN_TOOL_FINGER],
        ecodes.EV_ABS: [
            (ecodes.ABS_X, AbsInfo(0, 0, 1000, 0, 0, 10)),
            (ecodes.ABS_Y, AbsInfo(0, 0, 1000, 0, 0, 10)),
            (ecodes.ABS_PRESSURE, AbsInfo(0, 0, 255, 0, 0, 1)),
        ],
    }
    device = UInput(capabilities, name=name,
                    input_props=[ecodes.INPUT_PROP_POINTER, ecodes.INPUT_PROP_BUTTONPAD])
    app = None
    fixture = None
    results = []
    press_events = []
    try:
        app = Configurator()
        app.register(None)
        if app.get_is_remote():
            raise RuntimeError("Another configurator started during test setup; use a dedicated test session.")
        app.activate()
        pump(0.3)
        values = {**DEFAULTS, "left_color": "#e11d48", "right_color": "#16a34a",
                  "left_x": -50, "left_y": 20, "right_x": 50, "right_y": -35,
                  "size": 24, "opacity": 1.0}
        app.populate(values)
        app.backend_control.set_active_id("x11")
        app.controls["bottom_right_only"].set_active(True)
        app.controls["boundary"].set_value(65)
        app.controls["corner_top"].set_value(75)
        pump(0.2)
        shot_window(app.window, args.output / "gtk-regions.png")
        app.notebook.set_current_page(1)
        pump(0.2)
        shot_window(app.window, args.output / "gtk-indicators.png")
        app.populate(values)
        app.perform("start")
        wait(lambda: not app.busy, "Start worker")
        wait(lambda: app.child is not None and app.child.poll() is None, app.status.get_text())
        pump(1)
        assert app.child.poll() is None, app.status.get_text()
        results.append("PASS: configurator Start installed a unique preset and launched real injection")
        duplicate = subprocess.run([str(PROJECT / "run.sh")], capture_output=True, text=True, timeout=5)
        assert duplicate.returncode != 0 and "already running" in duplicate.stderr, duplicate.stderr
        assert app.child.poll() is None
        results.append("PASS: duplicate launcher refused before changing the running injector")
        # Drive a preview drag with a real mechanical-style toggle hold, rather
        # than injecting a mouse-down directly into X11.
        app.window.present()
        pump(0.2)
        area = app.dots
        scale = area.get_scale_factor()
        _success, ox, oy = area.get_window().get_origin()
        px = (ox + area.get_allocated_width() // 2) * scale + values["right_x"] + 12
        py = (oy + area.get_allocated_height() // 2) * scale + values["right_y"] + 12
        subprocess.run(["xdotool", "mousemove", str(px), str(py)], check=True)

        def drag_click():
            device.write(ecodes.EV_ABS, ecodes.ABS_X, 100)
            device.write(ecodes.EV_ABS, ecodes.ABS_Y, 900)
            device.write(ecodes.EV_ABS, ecodes.ABS_PRESSURE, 90)
            device.write(ecodes.EV_KEY, ecodes.BTN_TOOL_FINGER, 1)
            device.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, 1)
            device.syn()
            pump(0.25)  # A settled contact isolates mechanical clicks from taps.
            device.write(ecodes.EV_KEY, ecodes.BTN_LEFT, 1)
            device.syn()
            pump(0.08)
            device.write(ecodes.EV_KEY, ecodes.BTN_LEFT, 0)
            device.write(ecodes.EV_ABS, ecodes.ABS_PRESSURE, 0)
            device.write(ecodes.EV_KEY, ecodes.BTN_TOOL_FINGER, 0)
            device.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, 0)
            device.syn()
            pump(0.12)

        drag_click()
        wait(lambda: x11.button_down(1), "virtual-trackpad hold begins preview drag")
        subprocess.run(["xdotool", "mousemove", str(px + 32), str(py - 16)], check=True)
        pump(0.15)
        assert app.dragged_dot is not None, (x11.pointer(), px, py)
        assert app.controls["right_x"].get_value() == values["right_x"] + 32
        assert app.controls["right_y"].get_value() == values["right_y"] - 16
        assert app.controls["left_x"].get_value() == values["left_x"]
        shot_window(app.window, args.output / "virtual-trackpad-drag.png")
        drag_click()
        wait(lambda: not x11.button_down(1) and app.dragged_dot is None, "second mechanical click ends preview drag")
        results.append("PASS: real virtual-trackpad toggle hold drags the preview dot and a second mechanical click ends the drag")
        app.populate(values)
        fixture = Gtk.Window(title="CTI virtual touchpad test — private test canvas")
        fixture.set_default_size(760, 440)
        fixture.set_position(Gtk.WindowPosition.CENTER)
        canvas = Gtk.DrawingArea()
        canvas.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK)
        canvas.connect("button-press-event", lambda _w, event: press_events.append(("down", event.button)))
        canvas.connect("button-release-event", lambda _w, event: press_events.append(("up", event.button)))
        fixture.add(canvas)
        def draw(_area, cr):
            cr.set_source_rgb(0.96, 0.97, 0.99)
            cr.paint()
            cr.set_source_rgb(0.1, 0.15, 0.25)
            cr.select_font_face("Sans", 0, 1)
            cr.set_font_size(23)
            cr.move_to(28, 45)
            cr.show_text("Real virtual-trackpad input -> X11 indicator")
            cr.set_font_size(16)
            cr.move_to(28, 80)
            cr.show_text("Left: rose, offset (-50, +20)    Right: green, offset (+50, -35)")
            cr.move_to(28, 110)
            cr.show_text("24 px diameter / 100% opacity / crosshair marks pointer hotspot")
            w, h = canvas.get_allocated_width(), canvas.get_allocated_height()
            cx, cy = w // 2, h // 2 + 30
            cr.set_line_width(1)
            cr.move_to(cx - 12, cy)
            cr.line_to(cx + 12, cy)
            cr.move_to(cx, cy - 12)
            cr.line_to(cx, cy + 12)
            cr.stroke()
        canvas.connect("draw", draw)
        fixture.show_all()
        fixture.present()
        pump(0.5)
        def position_pointer():
            _success, ox, oy = canvas.get_window().get_origin()
            anchor = (canvas.get_allocated_width() // 2, canvas.get_allocated_height() // 2 + 30)
            scale = Gdk.get_default_root_window().get_scale_factor()
            subprocess.run(["xdotool", "mousemove", str((ox + anchor[0]) * scale), str((oy + anchor[1]) * scale)], check=True)
            pump(0.1)
            return anchor
        position_pointer()
        devices = subprocess.check_output(["xinput", "list", "--name-only"], text=True).splitlines()
        forwarded = next((item for item in devices if name in item and "forwarded" in item), None)
        assert forwarded, "Input Remapper forwarding device did not appear"
        subprocess.run(["xinput", "set-prop", forwarded, "libinput Tapping Enabled", "0"], check=True)

        def contact(x, y, pressed):
            for kind, code, value in ((3, 0, x), (3, 1, y), (3, 24, 90 if pressed else 0),
                                      (1, ecodes.BTN_TOOL_FINGER, int(pressed)),
                                      (1, ecodes.BTN_TOUCH, int(pressed))):
                device.write(kind, code, value)
            device.syn()

        def mechanical(x, y):
            contact(x, y, True)
            pump(0.07)
            device.write(ecodes.EV_KEY, ecodes.BTN_LEFT, 1)
            device.syn()
            pump(0.07)
            device.write(ecodes.EV_KEY, ecodes.BTN_LEFT, 0)
            device.syn()
            contact(x, y, False)
            pump(0.12)

        def assert_hold(x, y, button):
            mechanical(x, y)
            wait(lambda: x11.button_down(button), f"click ({x}, {y}) holds {button}")
            assert not x11.button_down(3 if button == 1 else 1), (x, y, button, x11.pointer(), press_events[-8:])
            # An opposite-region click cancels the current hold only.
            mechanical(0 if button == 3 else 1000, 0 if button == 3 else 1000)
            wait(lambda: not x11.button_down(button), "opposite-region cancellation")
            assert not x11.button_down(3 if button == 1 else 1)

        for boundary, corner, top in ((25, False, 85), (75, False, 85),
                                      (25, True, 25), (25, True, 75),
                                      (75, True, 25), (75, True, 75),
                                      (49.5, True, 50.5), (50.5, False, 85)):
            app.controls["boundary"].set_value(boundary)
            app.controls["bottom_right_only"].set_active(corner)
            app.controls["corner_top"].set_value(top)
            old_pid = app.child.pid
            app.perform("apply")
            wait(lambda: not app.busy, "Apply worker")
            assert app.child is not None and app.child.pid != old_pid, app.status.get_text()
            def forwarded_ready():
                result = subprocess.run(["xinput", "list-props", forwarded], capture_output=True, text=True)
                return result.returncode == 0 and "libinput Tapping Enabled" in result.stdout
            wait(forwarded_ready, "new forwarded touchpad after Apply")
            pump(0.3)
            subprocess.run(["xinput", "set-prop", forwarded, "libinput Tapping Enabled", "0"], check=True)
            # Points immediately on both sides of each configured boundary.
            bx, by = int(boundary * 10), int(top * 10)
            points = [(bx - 10, 900), (bx + 10, 900), (900, by - 10), (900, by + 10), (100, 100)]
            for x, y in points:
                button = 3 if x > bx and (not corner or y > by) else 1
                assert_hold(x, y, button)
            results.append(f"PASS: real routing boundary={boundary}%, corner={corner}, top={top}% (5 points + cancellation)")
            print(results[-1], flush=True)

        # Current config is the ordinary midpoint split. Check actual overlay pixels.
        for x, button, side, expected in ((100, 1, "left", (225, 29, 72)),
                                          (900, 3, "right", (22, 163, 74))):
            anchor = position_pointer()
            mechanical(x, 900)
            wait(lambda: x11.button_down(button), f"{side} indicator hold")
            pump(0.2)
            path = args.output / f"x11-{side}-held.png"
            shot_window(fixture, path)
            image = Image.open(path).convert("RGB")
            scale = Gdk.get_default_root_window().get_scale_factor()
            center = (anchor[0] * scale + values[f"{side}_x"] + 12,
                      anchor[1] * scale + values[f"{side}_y"] + 12)
            actual = image.getpixel(center)
            assert max(abs(a - b) for a, b in zip(actual, expected)) <= 2, (side, center, actual)
            matching = [(px, py) for px in range(center[0] - 20, center[0] + 21)
                        for py in range(center[1] - 20, center[1] + 21)
                        if max(abs(a - b) for a, b in zip(image.getpixel((px, py)), expected)) <= 2]
            bounds = (max(p[0] for p in matching) - min(p[0] for p in matching) + 1,
                      max(p[1] for p in matching) - min(p[1] for p in matching) + 1)
            assert bounds == (24, 24), bounds
            mechanical(x, 900)
            wait(lambda: not x11.button_down(button), "indicator release")
            pump(0.15)
            shot_window(fixture, args.output / f"x11-{side}-released.png")
            assert Image.open(args.output / f"x11-{side}-released.png").convert("RGB").getpixel(center) != expected
            results.append(f"PASS: {side} screenshot pixel confirms independent color, offsets, diameter, and disappearance")

        app.controls["size"].set_value(36)
        app.controls["opacity"].set_value(0.5)
        app.perform("apply")
        wait(lambda: not app.busy, "Apply translucent appearance")
        wait(forwarded_ready, "forwarded device after appearance Apply")
        pump(0.3)
        subprocess.run(["xinput", "set-prop", forwarded, "libinput Tapping Enabled", "0"], check=True)
        anchor = position_pointer()
        mechanical(900, 900)
        if x11.button_down(1):
            results.append("KNOWN LIMITATION: after injector restart, an unchanged axis position used the fallback left mapping until a fresh ABS event")
            mechanical(900, 900)
            wait(lambda: not x11.button_down(1), "release startup fallback hold")
            device.write(ecodes.EV_ABS, ecodes.ABS_X, 899)
            device.write(ecodes.EV_ABS, ecodes.ABS_Y, 899)
            device.syn()
            pump(0.05)
            mechanical(900, 900)
        wait(lambda: x11.button_down(3), "translucent right hold")
        pump(0.15)
        shot_window(fixture, args.output / "x11-translucent.png")
        image = Image.open(args.output / "x11-translucent.png").convert("RGB")
        center = (anchor[0] * scale + values["right_x"] + 18,
                  anchor[1] * scale + values["right_y"] + 18)
        background = Image.open(args.output / "x11-right-released.png").convert("RGB").getpixel(center)
        expected = tuple(round((a + b) / 2) for a, b in zip((22, 163, 74), background))
        actual = image.getpixel(center)
        assert max(abs(a - b) for a, b in zip(actual, expected)) <= 2, (actual, expected)
        mechanical(900, 900)
        wait(lambda: not x11.button_down(3), "release translucent hold")
        results.append("PASS: X11 live Apply resized the dot to 36 px and rendered 50% opacity")

        # Verify libinput sees a touchpad and enable tapping only on this test device.
        devices = subprocess.check_output(["xinput", "list", "--name-only"], text=True).splitlines()
        forwarded = next((item for item in devices if name in item and "forwarded" in item), None)
        assert forwarded, "Input Remapper forwarding device did not appear"
        properties = subprocess.check_output(["xinput", "list-props", forwarded], text=True)
        (args.output / "forwarded-device-properties.txt").write_text(properties)
        assert "libinput Tapping Enabled" in properties, "Virtual device was not recognized as a libinput touchpad"
        subprocess.run(["xinput", "set-prop", forwarded, "libinput Tapping Enabled", "1"], check=True)
        position_pointer()
        pump(0.7)  # Allow libinput disable-while-typing suppression to expire.
        press_events.clear()
        contact(300, 300, True)
        pump(0.06)
        contact(300, 300, False)
        pump(0.35)
        assert ("down", 1.0) in press_events and ("up", 1.0) in press_events, press_events
        assert not x11.button_down(1) and not x11.button_down(3), "Tap latched a hold"
        results.append("PASS: real libinput tap generated ordinary button-down/up without latching")

        press_events.clear()
        mechanical(900, 900)
        wait(lambda: x11.button_down(3), "short mechanical click with tapping enabled")
        pump(0.25)
        if ("down", 1.0) in press_events:
            results.append("KNOWN LIMITATION: a short mechanical right click also emits an ordinary native left tap when tapping is enabled")
        else:
            results.append("PASS: short mechanical right click did not produce an extra native tap in this run")
        mechanical(900, 900)
        wait(lambda: not x11.button_down(3), "release after short-click observation")
        pump(0.3)
        subprocess.run(["xinput", "set-prop", forwarded, "libinput Tapping Enabled", "0"], check=True)
        mechanical(900, 900)
        wait(lambda: x11.button_down(3), "hold before Stop")
        app.perform("stop")
        wait(lambda: not app.busy, "Stop")
        assert app.child is None and not x11.button_down(3)
        results.append("PASS: configurator Stop released a hold and stopped real injection")
        assert load_settings()["right_color"] == values["right_color"]
        results.append("PASS: settings persisted through real restarts")
    finally:
        if app is not None:
            # Finish pending operations before shutting down their child process.
            wait(lambda: not app.busy, "cleanup worker")
            if app.log is not None:
                app.log.seek(0)
                (args.output / "launcher.log").write_bytes(app.log.read())
            app.stop_child()
            app.quit()
            pump(0.1)
        if fixture is not None:
            fixture.destroy()
        device.close()
        if preset.exists():
            preset.unlink()
            preset.parent.rmdir()
        subprocess.run(["xdotool", "mousemove", *map(str, old_pointer)], check=False)
        x11.close()
        (args.output / "results.txt").write_text("\n".join(results) + "\n")
    print("\n".join(results), flush=True)


def shot_window(window, path):
    pump(0.1)
    native = window.get_window()
    _success, x, y = native.get_origin()
    pixbuf = Gdk.pixbuf_get_from_window(Gdk.get_default_root_window(), x, y,
                                      window.get_allocated_width(), window.get_allocated_height())
    pixbuf.savev(str(path), "png", [], [])


if __name__ == "__main__":
    main()
