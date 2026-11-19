#!/usr/bin/python3
"""Private GNOME 46 compositor: real extension, bridge, pixels, and tray host."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tools"))
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gio, GLib
from PIL import Image
from configurator import Configurator
from settings import DEFAULTS, save_settings
from e2e_support import X11, stop_process

UUID = "click-toggle-indicator@personal-utilities"
TRAY_UUID = "ubuntu-appindicators@ubuntu.com"
PATH = "/org/gnome/Shell/Extensions/ClickToggleIndicator"
IFACE = "org.gnome.Shell.Extensions.ClickToggleIndicator"
EXTENSION = f"Main.extensionManager.lookup('{UUID}').stateObj"
TRAY = "Object.values(Main.panel.statusArea).find(i => i?._indicator?.id === 'click-toggle-indicator')"


def pump(duration=0.1):
    deadline = time.monotonic() + duration
    context = GLib.MainContext.default()
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)


def wait(predicate, description, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pump(0.05)
        if predicate():
            return
    raise AssertionError(f"Timed out: {description}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    def call(path, interface, method, params):
        return bus.call_sync("org.gnome.Shell", path, interface, method, params, None,
                             Gio.DBusCallFlags.NO_AUTO_START, 2000, None).unpack()
    def evaluate(code):
        success, value = call("/org/gnome/Shell", "org.gnome.Shell", "Eval", GLib.Variant("(s)", (code,)))
        if not success:
            raise RuntimeError(value)
        return json.loads(value) if value else None
    def state(value):
        call(PATH, IFACE, "SetState", GLib.Variant("(u)", (value,)))
    def configure(values):
        call(PATH, IFACE, "Configure", GLib.Variant("(s)", (json.dumps(values),)))
    def screenshot(name):
        path = (args.output / f"{name}.png").resolve()
        evaluate("(()=>{const Gio=imports.gi.Gio; global._ctiShotDone=false; "
                 f"const stream=Gio.File.new_for_path({json.dumps(str(path))}).replace(null,false,Gio.FileCreateFlags.NONE,null); "
                 "const shot=new imports.gi.Shell.Screenshot(); shot.screenshot(true,stream,(obj,res)=>{"
                 "obj.screenshot_finish(res);stream.close(null);global._ctiShotDone=true;});return true;})()")
        wait(lambda: evaluate("global._ctiShotDone"), "Shell screenshot")
        return Image.open(path).convert("RGB")
    base = Path(os.environ["XDG_DATA_HOME"]) / "gnome-shell/extensions"
    base.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PROJECT / "gnome-extension", base / UUID)
    tray_source = Path("/usr/share/gnome-shell/extensions") / TRAY_UUID
    shutil.copytree(tray_source, base / TRAY_UUID)
    driver = base / "test-driver@cti"
    driver.mkdir()
    (driver / "metadata.json").write_text(json.dumps({"uuid": "test-driver@cti", "name": "Private test driver", "description": "Test only", "shell-version": ["46"]}))
    (driver / "extension.js").write_text("import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js'; export default class extends Extension {enable(){global.context.unsafe_mode=true;} disable(){global.context.unsafe_mode=false;}}")
    subprocess.run(["gsettings", "set", "org.gnome.shell", "enabled-extensions",
                    str(["test-driver@cti", UUID, TRAY_UUID])], check=True)
    subprocess.run(["gsettings", "set", "org.gnome.desktop.notifications", "show-banners", "false"], check=True)
    env = {**os.environ, "GNOME_SHELL_SESSION_MODE": "user", "LIBGL_ALWAYS_SOFTWARE": "1"}
    bridge = None
    app = None
    x11 = X11()
    results = []
    with (args.output / "gnome-shell.log").open("w") as log:
        shell = subprocess.Popen(["gnome-shell", "--headless", "--wayland", "--no-x11",
                                  "--virtual-monitor", "1024x768", "--wayland-display", "cti-private-test"],
                                 env=env, stdout=log, stderr=log)
        try:
            def ready():
                if shell.poll() is not None:
                    raise RuntimeError("GNOME Shell exited; inspect gnome-shell.log")
                try:
                    state(0)
                    return True
                except GLib.Error:
                    return False
            wait(ready, "GNOME extension export")
            wait(lambda: call("/org/gnome/Shell", "org.gnome.Shell", "Eval",
                              GLib.Variant("(s)", ("true",)))[0], "private test driver enables Eval")
            evaluate("Main.overview.hide(); true")
            pump(1)
            evaluate("global._ctiPointer=imports.gi.Clutter.get_default_backend().get_default_seat().create_virtual_device(imports.gi.Clutter.InputDeviceType.POINTER_DEVICE); true")
            def move(x, y):
                evaluate(f"global._ctiPointer.notify_absolute_motion(imports.gi.GLib.get_monotonic_time(),{x},{y}); true")
                pump(0.15)
            values = {**DEFAULTS, "left_color": "#e11d48", "right_color": "#16a34a",
                      "left_x": -50, "left_y": 20, "right_x": 50, "right_y": -35,
                      "size": 24, "opacity": 1.0}
            save_settings(values)
            configure(values)
            move(450, 330)
            for number, side, color in ((1, "left", (225, 29, 72)), (2, "right", (22, 163, 74))):
                state(number)
                pump(0.15)
                position = evaluate(f"{EXTENSION}._dot.get_position()")
                expected = [450 + values[f"{side}_x"], 330 + values[f"{side}_y"]]
                assert position == expected, (position, expected)
                assert evaluate(f"{EXTENSION}._dot.get_size()") == [24, 24]
                image = screenshot(f"gnome-{side}-held")
                assert image.getpixel((expected[0] + 12, expected[1] + 12)) == color
                results.append(f"PASS: GNOME {side} pixels, color, independent offsets and size")
            move(700, 500)
            assert evaluate(f"{EXTENSION}._dot.get_position()") == [750, 465]
            state(0)
            assert evaluate(f"{EXTENSION}._dot.visible") is False
            background = screenshot("gnome-released")
            translucent = {**values, "opacity": 0.5, "size": 36}
            configure(translucent)
            state(2)
            pump(0.15)
            image = screenshot("gnome-translucent")
            center = (750 + 18, 465 + 18)
            expected = tuple(round((a + b) / 2) for a, b in zip((22, 163, 74), background.getpixel(center)))
            assert max(abs(a - b) for a, b in zip(image.getpixel(center), expected)) <= 2
            assert evaluate(f"{EXTENSION}._dot.get_size()") == [36, 36]
            results.append("PASS: live Configure resized the held dot and rendered 50% opacity")
            configure(values)
            state(1)
            pump(2.25)
            assert evaluate(f"{EXTENSION}._dot.visible") is False
            results.append("PASS: pointer motion, off state, and lease expiry")
            for invalid in ({**values, "size": 200}, {**values, "left_color": "red"}):
                try:
                    configure(invalid)
                except GLib.Error:
                    pass
                else:
                    raise AssertionError("Invalid Configure call was accepted")
            results.append("PASS: D-Bus appearance validation rejects invalid values")
            # Verify the Python bridge loads the saved settings and drives Shell.
            with (args.output / "bridge.log").open("w") as bridge_log:
                bridge = subprocess.Popen(["/usr/bin/python3", str(PROJECT / "tools/gnome_indicator_bridge.py")],
                                          stdout=bridge_log, stderr=bridge_log)
                pump(0.4)
                assert bridge.poll() is None
                subprocess.run(["xdotool", "key", "197"], check=True)
                wait(lambda: evaluate(f"{EXTENSION}._state") == 2, "real bridge right hold")
                assert x11.button_down(3)
                # Extension disable models its actual session-lock/disable cleanup.
                evaluate(f"{EXTENSION}.disable(); true")
                wait(lambda: bridge.poll() is not None, "bridge exit after disable")
                assert not x11.button_down(3)
                assert evaluate(f"{EXTENSION}._dot === null")
                results.append("PASS: real C daemon/bridge loads settings; extension loss releases button")
                bridge = None

            # This is the real Ubuntu tray host, not a direct GTK menu callback.
            app = Configurator()
            app.register(None)
            app.activate()
            pump(0.5)
            app.window.hide()
            wait(lambda: evaluate(f"Boolean({TRAY})"), "AppIndicator registered with Shell host")
            wait(lambda: evaluate(f"Boolean(({TRAY})?.visible)"), "visible tray icon")
            evaluate(f"({TRAY}).menu.open(); true")
            pump(0.5)
            labels = evaluate(f"({TRAY}).menu._getMenuItems().map(i => i.label?.text ?? '')")
            assert "Configure…" in labels, labels
            item = evaluate(f"(()=>{{const i=({TRAY}).menu._getMenuItems().find(i=>i.label?.text==='Configure…'); return [...i.get_transformed_position(), ...i.get_size()];}})()")
            move(item[0] + item[2] / 2, item[1] + item[3] / 2)
            screenshot("gnome-tray-menu")
            evaluate("global._ctiPointer.notify_button(imports.gi.GLib.get_monotonic_time(),1,imports.gi.Clutter.ButtonState.PRESSED); true")
            pump(0.1)
            evaluate("global._ctiPointer.notify_button(imports.gi.GLib.get_monotonic_time(),1,imports.gi.Clutter.ButtonState.RELEASED); true")
            wait(lambda: app.window.get_visible(), "Configure activated over real D-BusMenu")
            results.append("PASS: real GNOME AppIndicator icon/menu rendered; Configure reopened GTK over D-BusMenu")
            print("\n".join(results))
        finally:
            if app is not None:
                app.quit()
                pump(0.1)
            if bridge is not None:
                stop_process(bridge)
            stop_process(shell)
            x11.close()
            (args.output / "gnome-results.txt").write_text("\n".join(results) + "\n")


if __name__ == "__main__":
    main()
