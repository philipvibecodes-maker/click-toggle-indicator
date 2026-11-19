#!/usr/bin/python3
"""GTK settings window and AppIndicator launcher for click-toggle-indicator."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
except ValueError:
    try:
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3 as AppIndicator
    except ValueError:
        sys.exit("Install gir1.2-ayatanaappindicator3-0.1 for the tray icon.")
from gi.repository import Gdk, Gio, GLib, Gtk

from settings import DEFAULTS, SETTINGS_PATH, load_settings, save_settings, validate_settings

PROJECT = Path(__file__).resolve().parents[1]


class Configurator(Gtk.Application):
    def __init__(self, tray_only=False):
        super().__init__(application_id="org.personalutilities.ClickToggleConfigurator",
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.tray_only = tray_only
        self.child = None
        self.busy = False
        self.log = None
        self.window = None
        self.controls = {}
        self.action_buttons = {}
        self.saved_settings = None
        self.saved_spin_text = {}
        self.dragged_dot = None
        self.axis_values = {key: DEFAULTS[key] for key in ("boundary", "corner_top")}
        self.pending_quit = False
        self.backend = "gnome" if os.environ.get("CLICK_TOGGLE_GNOME") == "1" else "x11"
        self.saved_backend = self.backend

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.hold()  # Closing the window keeps the tray and input handling alive.
        self.tray = AppIndicator.Indicator.new(
            "click-toggle-indicator", "input-mouse",
            AppIndicator.IndicatorCategory.APPLICATION_STATUS)
        self.tray.set_title("Click Toggle Indicator")
        self.tray.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        menu = Gtk.Menu()
        self.menu_items = []
        for label, callback in (("Configure…", self.present_window),
                                ("Start toggles", lambda: self.perform("start")),
                                ("Stop toggles", lambda: self.perform("stop")),
                                ("Quit", self.quit_safely)):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _item, action=callback: action())
            menu.append(item)
            self.menu_items.append(item)
        menu.show_all()
        self.tray.set_menu(menu)
        self.build_window()
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, self.quit_signal)
        GLib.timeout_add(500, self.check_child)

    def do_activate(self):
        if not self.tray_only or self.window.get_visible():
            self.present_window()
        self.tray_only = False

    def quit_signal(self):
        self.quit_safely()
        return GLib.SOURCE_CONTINUE

    def present_window(self):
        self.window.show_all()
        self.update_preview()
        self.window.present()

    def build_window(self):
        self.window = Gtk.ApplicationWindow(application=self, title="Click Toggle Settings")
        self.window.set_default_size(640, 700)
        self.window.connect("delete-event", lambda window, _event: window.hide() or True)
        close_action = Gio.SimpleAction.new("close-settings", None)
        close_action.connect("activate", lambda *_args: self.window.close())
        self.window.add_action(close_action)
        self.set_accels_for_action("win.close-settings", ["<Primary>q"])
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=16)
        self.window.add(outer)
        title = Gtk.Label(xalign=0)
        title.set_markup("<big><b>Click Toggle Indicator</b></big>")
        outer.pack_start(title, False, False, 0)
        subtitle = Gtk.Label(label="Mechanical clicks toggle a hold. Taps work normally.", xalign=0)
        outer.pack_start(subtitle, False, False, 0)
        notebook = Gtk.Notebook()
        self.notebook = notebook
        outer.pack_start(notebook, True, True, 0)

        regions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=12)
        notebook.append_page(regions, Gtk.Label(label="Click regions"))
        self.pad = Gtk.DrawingArea()
        self.pad.set_size_request(360, 140)
        self.pad.connect("draw", self.draw_pad)
        regions.pack_start(self.pad, True, True, 0)
        grid = Gtk.Grid(column_spacing=16, row_spacing=12)
        regions.pack_start(grid, False, False, 0)
        self.add_spin(grid, 0, "Right-click starts at (% from left)", "boundary", 0.5, 99.5, 0.5)
        corner = Gtk.CheckButton(label="Restrict right click to the bottom-right corner")
        self.controls["bottom_right_only"] = corner
        corner.connect("toggled", self.update_preview)
        grid.attach(corner, 0, 1, 2, 1)
        self.add_spin(grid, 2, "Corner starts at (% from top)", "corner_top", 0.5, 99.5, 0.5)
        note = Gtk.Label(label="Blue area: right click. Everywhere else: left click.\n"
                         "The midpoint uses 50.5% to match Input Remapper’s axis threshold.\n"
                         "While holding either button, a click anywhere releases it.", xalign=0)
        note.set_line_wrap(True)
        regions.pack_start(note, False, False, 0)

        appearance = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=12)
        notebook.append_page(appearance, Gtk.Label(label="Indicators"))
        self.dots = Gtk.DrawingArea()
        self.dots.set_size_request(400, 110)
        self.dots.connect("draw", self.draw_dots)
        self.dot_drag = Gtk.GestureDrag.new(self.dots)
        self.dot_drag.set_button(1)
        self.dot_drag.connect("drag-begin", self.begin_dot_drag)
        self.dot_drag.connect("drag-update", self.update_dot_drag)
        self.dot_drag.connect("drag-end", self.end_dot_drag)
        self.dot_drag.connect("cancel", self.cancel_dot_drag)
        appearance.pack_start(self.dots, True, True, 0)
        grid = Gtk.Grid(column_spacing=18, row_spacing=12)
        appearance.pack_start(grid, False, False, 0)
        for column, side in enumerate(("left", "right"), 1):
            grid.attach(Gtk.Label(label=f"{side.title()} hold"), column, 0, 1, 1)
            color = Gtk.ColorButton()
            color.set_title(f"{side.title()} indicator color")
            color.connect("color-set", self.update_preview)
            self.controls[f"{side}_color"] = color
            grid.attach(color, column, 1, 1, 1)
            for row, axis in ((2, "x"), (3, "y")):
                spin = Gtk.SpinButton.new_with_range(-512, 512, 1)
                spin.connect("value-changed", self.update_preview)
                spin.connect("changed", self.update_edit_buttons)
                self.controls[f"{side}_{axis}"] = spin
                grid.attach(spin, column, row, 1, 1)
        for row, label in enumerate(("Color", "Horizontal offset (px)", "Vertical offset (px)"), 1):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
        self.add_spin(grid, 4, "Diameter (px)", "size", 8, 96, 1)
        self.add_spin(grid, 5, "Opacity", "opacity", 0.05, 1, 0.05)
        note = Gtk.Label(label="Drag a dot to position it, or edit its offsets below.\n"
                         "Offsets locate each dot’s top-left from the pointer.\n"
                         "Actual size; distant dots may be outside the preview.", xalign=0)
        note.set_line_wrap(True)
        appearance.pack_start(note, False, False, 0)

        row = Gtk.Box(spacing=12)
        row.pack_start(Gtk.Label(label="Display backend"), False, False, 0)
        self.backend_control = Gtk.ComboBoxText()
        self.backend_control.append("x11", "X11 overlay")
        self.backend_control.append("gnome", "GNOME Shell extension")
        self.backend_control.set_active_id(self.backend)
        self.backend_control.connect("changed", self.update_preview)
        row.pack_start(self.backend_control, False, False, 0)
        outer.pack_start(row, False, False, 0)
        buttons = Gtk.Box(spacing=8)
        for label, action in (("Reset defaults", "reset"), ("Discard edits", "discard"),
                              ("Apply", "apply"),
                              ("Start", "start"), ("Stop", "stop")):
            button = Gtk.Button(label=label)
            self.action_buttons[action] = button
            button.connect("clicked", lambda _button, value=action: self.perform(value))
            buttons.pack_start(button, True, True, 0)
        self.buttons = buttons
        outer.pack_start(buttons, False, False, 0)
        self.status = Gtk.Label(label="Stopped. Apply saves settings; Start enables toggles.", xalign=0)
        self.status.set_line_wrap(True)
        self.status.set_selectable(True)
        outer.pack_start(self.status, False, False, 0)
        outer.pack_start(Gtk.Label(label="Ctrl+Q closes this window; the tray keeps running.", xalign=0), False, False, 0)
        try:
            self.populate(load_settings())
            self.remember_saved(self.read_controls(), self.saved_backend)
            self.update_edit_buttons()
        except (OSError, ValueError) as error:
            self.populate(DEFAULTS)
            self.status.set_text(f"Could not load settings: {error}. Reset defaults and Apply to replace them.")

    def add_spin(self, grid, row, label, key, low, high, step):
        grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
        spin = Gtk.SpinButton.new_with_range(low, high, step)
        spin.set_digits(2 if key == "opacity" else 1 if step == 0.5 else 0)
        spin.connect("value-changed", self.update_preview)
        spin.connect("changed", self.update_edit_buttons)
        self.controls[key] = spin
        grid.attach(spin, 1, row, 1, 1)

    def populate(self, settings):
        for key, value in settings.items():
            control = self.controls[key]
            if key.endswith("_color"):
                color = Gdk.RGBA()
                color.parse(value)
                control.set_rgba(color)
            elif key == "bottom_right_only":
                control.set_active(value)
            else:
                control.set_value(value)
        self.update_preview()

    def read_controls(self):
        result = {}
        for key, control in self.controls.items():
            if key.endswith("_color"):
                color = control.get_rgba()
                result[key] = "#{:02x}{:02x}{:02x}".format(
                    round(color.red * 255), round(color.green * 255), round(color.blue * 255))
            elif key == "bottom_right_only":
                result[key] = control.get_active()
            else:
                value = round(control.get_value(), control.get_digits())
                result[key] = int(value) if key in ("size", "left_x", "left_y", "right_x", "right_y") else value
        return result

    def update_preview(self, *_args):
        # The remapper has no zero threshold; keep the displayed value honest.
        for key in ("boundary", "corner_top"):
            value = self.controls[key].get_value()
            if value == 50:
                self.controls[key].set_value(49.5 if self.axis_values[key] > 50 else 50.5)
            self.axis_values[key] = self.controls[key].get_value()
        self.controls["corner_top"].set_sensitive(self.controls["bottom_right_only"].get_active())
        self.pad.queue_draw()
        self.dots.queue_draw()
        self.update_edit_buttons()

    def remember_saved(self, values, backend):
        self.saved_settings = values.copy()
        self.saved_backend = backend
        self.saved_spin_text = {key: control.get_text() for key, control in self.controls.items()
                                if isinstance(control, Gtk.SpinButton)}

    def update_edit_buttons(self, *_args):
        if not self.action_buttons:
            return
        dirty = (self.read_controls() != self.saved_settings
                 or self.backend_control.get_active_id() != self.saved_backend
                 or any(self.controls[key].get_text() != text
                        for key, text in self.saved_spin_text.items()))
        for action in ("apply", "discard"):
            self.action_buttons[action].set_sensitive(not self.busy and dirty)

    def draw_pad(self, area, cr):
        values = self.read_controls()
        width, height = area.get_allocated_width(), area.get_allocated_height()
        x, y, w, h = 24, 12, width - 48, height - 30
        cr.set_source_rgb(0.89, 0.91, 0.94)
        cr.rectangle(x, y, w, h)
        cr.fill()
        boundary = values["boundary"] / 100
        top = values["corner_top"] / 100 if values["bottom_right_only"] else 0
        cr.set_source_rgb(0.23, 0.51, 0.96)
        cr.rectangle(x + w * boundary, y + h * top, w * (1 - boundary), h * (1 - top))
        cr.fill()
        cr.set_source_rgb(0.2, 0.23, 0.3)
        cr.set_line_width(2)
        cr.rectangle(x, y, w, h)
        cr.stroke()
        cr.set_font_size(14)
        cr.move_to(x + 12, y + 24)
        cr.show_text("LEFT")
        cr.move_to(x + w * boundary + 6, y + h * top + 24)
        cr.show_text("RIGHT")
        return False

    def begin_dot_drag(self, gesture, x, y):
        self.dragged_dot = None
        if self.busy:
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        values = self.read_controls()
        units = self.dots.get_scale_factor() if self.backend_control.get_active_id() == "x11" else 1
        x = (x - self.dots.get_allocated_width() // 2) * units
        y = (y - self.dots.get_allocated_height() // 2) * units
        radius = values["size"] / 2
        # Right is drawn last, so it receives a drag when the dots overlap.
        for side in ("right", "left"):
            start_x, start_y = values[f"{side}_x"], values[f"{side}_y"]
            if (x - start_x - radius) ** 2 + (y - start_y - radius) ** 2 <= radius ** 2:
                self.dragged_dot = (side, start_x, start_y, units)
                gesture.set_state(Gtk.EventSequenceState.CLAIMED)
                return
        gesture.set_state(Gtk.EventSequenceState.DENIED)

    def update_dot_drag(self, _gesture, offset_x, offset_y):
        if self.dragged_dot is None:
            return
        side, start_x, start_y, units = self.dragged_dot
        # Gesture offsets are cumulative from the press point, preserving where
        # the dot was grabbed. Spin buttons clamp to the supported offset range.
        self.controls[f"{side}_x"].set_value(round(start_x + offset_x * units))
        self.controls[f"{side}_y"].set_value(round(start_y + offset_y * units))

    def end_dot_drag(self, gesture, offset_x, offset_y):
        self.update_dot_drag(gesture, offset_x, offset_y)
        self.dragged_dot = None

    def cancel_dot_drag(self, _gesture, _sequence):
        self.dragged_dot = None

    def draw_dots(self, area, cr):
        values = self.read_controls()
        # Keep the hotspot fixed regardless of either dot's size or position.
        cr.translate(area.get_allocated_width() // 2, area.get_allocated_height() // 2)
        device_scale = area.get_scale_factor()
        shell = self.backend_control.get_active_id() == "gnome"
        # X11 uses device pixels; Shell uses logical pixels. GTK's drawing
        # coordinates are logical, so undo its scale only for the X11 dots.
        cr.save()
        if not shell:
            cr.scale(1 / device_scale, 1 / device_scale)
        radius = values["size"] / 2
        for side in ("left", "right"):
            color = Gdk.RGBA()
            color.parse(values[f"{side}_color"])
            x = values[f"{side}_x"] + radius
            y = values[f"{side}_y"] + radius
            if shell:
                # Match the Shell renderer's two contrasting outline rings.
                cr.arc(x, y, radius - 0.5, 0, 6.283185)
                cr.set_source_rgba(0.06, 0.09, 0.16, 0.95)
                cr.set_line_width(1)
                cr.stroke()
                cr.arc(x, y, radius - 1.5, 0, 6.283185)
                cr.set_source_rgba(1, 1, 1, 0.95)
                cr.stroke()
            cr.arc(x, y, radius - 2.5 if shell else radius, 0, 6.283185)
            cr.set_source_rgba(color.red, color.green, color.blue, values["opacity"])
            cr.fill()
        cr.restore()

        # The themed surface preserves its native pixel density and logical
        # hotspot. get_image() would downsample it on HiDPI displays. Draw the
        # cursor above the dots, as the desktop's hardware cursor is.
        cursor = Gdk.Cursor.new_from_name(area.get_display(), "default")
        if cursor is None:
            cursor = Gdk.Cursor.new_for_display(area.get_display(), Gdk.CursorType.LEFT_PTR)
        surface, hot_x, hot_y = cursor.get_surface()
        cr.save()
        if surface is not None:
            cr.set_source_surface(surface, -hot_x, -hot_y)
            cr.paint()
        else:
            # Some cursor backends cannot expose their bitmap. Retain a fixed
            # 16-by-22 device-pixel arrow rather than scaling with the offsets.
            cr.scale(1 / device_scale, 1 / device_scale)
            cr.set_source_rgb(0.25, 0.28, 0.34)
            cr.move_to(0, 0)
            for point in ((0, 18), (5, 13), (11, 22), (15, 19), (9, 10), (16, 10)):
                cr.line_to(*point)
            cr.close_path()
            cr.fill()
        cr.restore()
        return False

    def stop_child(self):
        if self.child is not None:
            if self.child.poll() is None:
                try:
                    os.killpg(self.child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            # run.sh waits for the daemon to release buttons and stops injection.
            self.child.wait()
            self.child = None

    def perform(self, action):
        if self.busy:
            return
        if action == "discard":
            self.populate(self.saved_settings if self.saved_settings is not None else DEFAULTS)
            for key, text in self.saved_spin_text.items():
                self.controls[key].set_text(text)
            self.backend_control.set_active_id(self.saved_backend)
            self.status.set_text("Edits discarded." if self.saved_settings is not None
                                 else "Defaults restored. Apply to replace the invalid settings file.")
            return
        if action == "reset":
            self.populate(DEFAULTS)
            self.status.set_text("Defaults restored in the form.")
            return
        try:
            if action != "stop":
                for control in self.controls.values():
                    if isinstance(control, Gtk.SpinButton):
                        control.update()
            values = None if action == "stop" else validate_settings(self.read_controls())
        except ValueError as error:
            self.status.set_text(str(error))
            return
        backend = self.backend_control.get_active_id()
        was_running = self.child is not None and self.child.poll() is None
        self.set_busy(True)
        self.status.set_text("Stopping…" if action == "stop" else "Applying settings…")

        def work():
            committed = None
            try:
                self.stop_child()
                if action != "stop":
                    from configure_input_remapper import find_group, install, preset_path, SELECTION_PATH
                    group = find_group()
                    paths = (SETTINGS_PATH, preset_path(group), SELECTION_PATH)
                    previous = {path: path.read_bytes() if path.exists() else None for path in paths}
                    try:
                        install(group, force=False, settings=values)
                        save_settings(values)
                        committed = values.copy()
                    except Exception:
                        for path, contents in previous.items():
                            if contents is None:
                                path.unlink(missing_ok=True)
                            else:
                                path.write_bytes(contents)
                        raise
                    if action == "start" or was_running:
                        if self.log is not None:
                            self.log.close()
                        self.log = tempfile.TemporaryFile(mode="w+b")
                        launcher = "run-gnome.sh" if backend == "gnome" else "run.sh"
                        self.child = subprocess.Popen([str(PROJECT / launcher)],
                                                      env={**os.environ, "CLICK_TOGGLE_GNOME": "1" if backend == "gnome" else "0"},
                                                      stdout=self.log, stderr=self.log,
                                                      start_new_session=True)
                message = "Stopped." if action == "stop" else "Settings saved." if self.child is None else "Starting toggles…"
            except Exception as error:
                message = f"Could not {action}: {error}. Toggles are stopped."
            GLib.idle_add(self.finish_work, message, committed, backend)
        threading.Thread(target=work, daemon=True).start()

    def set_busy(self, busy):
        self.busy = busy
        self.buttons.set_sensitive(not busy)
        self.notebook.set_sensitive(not busy)
        self.backend_control.set_sensitive(not busy)
        self.update_edit_buttons()
        for item in self.menu_items[1:]:
            item.set_sensitive(not busy)

    def finish_work(self, message, committed=None, backend=None):
        if committed is not None:
            self.remember_saved(committed, backend)
        self.set_busy(False)
        self.status.set_text(message)
        if self.pending_quit:
            self.quit_safely()
        return GLib.SOURCE_REMOVE

    def check_child(self):
        if not self.busy and self.child is not None:
            code = self.child.poll()
            if code is not None:
                self.child = None
                self.log.seek(0)
                detail = self.log.read().decode(errors="replace")[-2000:].strip()
                self.status.set_text(f"Toggles stopped (exit {code}).\n{detail}")
                self.present_window()
            elif self.status.get_text() == "Starting toggles…":
                self.status.set_text("Running. Apply restarts toggles with these settings.")
        return GLib.SOURCE_CONTINUE

    def quit_safely(self):
        if self.busy:
            self.pending_quit = True
            return
        self.set_busy(True)
        self.status.set_text("Stopping toggles before quitting…")

        def work():
            self.stop_child()
            GLib.idle_add(self.quit)
        threading.Thread(target=work, daemon=True).start()

    def do_shutdown(self):
        self.tray.set_status(AppIndicator.IndicatorStatus.PASSIVE)
        if self.log is not None:
            self.log.close()
        Gtk.Application.do_shutdown(self)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tray", action="store_true", help="start with the settings window hidden")
    args = parser.parse_args()
    if os.environ.get("XDG_SESSION_TYPE", "x11") != "x11":
        sys.exit("The click-toggle input backend requires an X11 session.")
    sys.exit(Configurator(args.tray).run([sys.argv[0]]))
