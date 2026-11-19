#!/usr/bin/python3
"""Exercise real GTK and X11 lifecycles; fake only physical-device injection."""

import ctypes
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import traceback
from unittest.mock import patch

from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import configurator
import configure_input_remapper as remapper
from settings import appearance_args, load_settings
from e2e_support import X11

GLib, Gdk = configurator.GLib, configurator.Gdk
app = configurator.Configurator()
x11 = X11()
original_popen = subprocess.Popen
processes = []
failed = False
started = time.monotonic()


def spawn_daemon(_command, **kwargs):
    # Replace the launcher that contacts the system Input Remapper service.
    child = original_popen([
        str(configurator.PROJECT / "click-toggle-indicator"),
        "--toggle-keycode", "202", "--right-toggle-keycode", "197",
        *appearance_args(load_settings()),
    ], **kwargs)
    processes.append(child)
    return child


def capture(name):
    window = app.window.get_window()
    directory = Path(sys.argv[1])
    directory.mkdir(parents=True, exist_ok=True)
    Gdk.pixbuf_get_from_window(window, 0, 0, app.window.get_allocated_width(),
                              app.window.get_allocated_height()).savev(
                                  str(directory / f"{name}.png"), "png", [], [])


def preview_snapshot(name):
    area = app.dots
    path = Path(sys.argv[1]) / f"{name}.png"
    native = area.get_window()
    assert area.get_has_window(), "Preview snapshot needs the drawing area's window"
    Gdk.pixbuf_get_from_window(native, 0, 0, area.get_allocated_width(),
                              area.get_allocated_height()).savev(str(path), "png", [], [])
    return Image.open(path).convert("RGB")


def actual_cursor(background):
    class CursorImage(ctypes.Structure):
        _fields_ = [("x", ctypes.c_short), ("y", ctypes.c_short),
                    ("width", ctypes.c_ushort), ("height", ctypes.c_ushort),
                    ("xhot", ctypes.c_ushort), ("yhot", ctypes.c_ushort),
                    ("serial", ctypes.c_ulong), ("pixels", ctypes.POINTER(ctypes.c_ulong)),
                    ("atom", ctypes.c_ulong), ("name", ctypes.c_char_p)]
    fixes = ctypes.CDLL("libXfixes.so.3")
    fixes.XFixesGetCursorImage.argtypes = [ctypes.c_void_p]
    fixes.XFixesGetCursorImage.restype = ctypes.POINTER(CursorImage)
    x11.lib.XFree.argtypes = [ctypes.c_void_p]
    raw = fixes.XFixesGetCursorImage(x11.display)
    assert raw, "XFixes must expose the actual display cursor"
    try:
        cursor = raw.contents
        bitmap = Image.new("RGB", (cursor.width, cursor.height))
        pixels = []
        for index in range(cursor.width * cursor.height):
            pixel = cursor.pixels[index]
            alpha = (pixel >> 24) & 255
            # XFixes supplies premultiplied ARGB. Composite over the GTK canvas.
            pixels.append(tuple(min(255, ((pixel >> shift) & 255) + round(bg * (255 - alpha) / 255))
                                for shift, bg in zip((16, 8, 0), background)))
        bitmap.putdata(pixels)
        return bitmap, cursor.xhot, cursor.yhot
    finally:
        x11.lib.XFree(raw)


def preview_checks():
    original = app.read_controls()
    values = {**original, "size": 24, "opacity": 1.0,
              "left_color": "#e11d48", "right_color": "#16a34a",
              "left_x": -50, "left_y": 20, "right_x": 80, "right_y": -35}
    app.populate(values)
    app.backend_control.set_active_id("x11")
    native = app.dots.get_window()
    native.set_cursor(Gdk.Cursor.new_from_name(app.dots.get_display(), "default"))
    _success, x, y = native.get_origin()
    scale = app.dots.get_scale_factor()
    subprocess.run(["xdotool", "mousemove", str((x + 5) * scale), str((y + 5) * scale)], check=True)
    yield lambda: True
    before = preview_snapshot("preview-x11-baseline")
    scale = app.dots.get_scale_factor()
    anchor = (app.dots.get_allocated_width() // 2 * scale,
              app.dots.get_allocated_height() // 2 * scale)
    background = before.getpixel((0, 0))

    def dot_box(side, unit=1):
        x = anchor[0] + values[f"{side}_x"] * unit
        y = anchor[1] + values[f"{side}_y"] * unit
        return (x - 3, y - 3, x + 24 * unit + 3, y + 24 * unit + 3)

    def assert_diameter(image, side, unit=1):
        crop = image.crop(dot_box(side, unit))
        bounds = ImageChops.difference(crop, Image.new("RGB", crop.size, background)).getbbox()
        assert bounds == (3, 3, 3 + 24 * unit, 3 + 24 * unit), (side, scale, unit, bounds)

    assert_diameter(before, "left")
    assert_diameter(before, "right")
    bitmap, hot_x, hot_y = actual_cursor(background)
    cursor_box = (anchor[0] - hot_x, anchor[1] - hot_y,
                  anchor[0] - hot_x + bitmap.width, anchor[1] - hot_y + bitmap.height)
    extrema = ImageChops.difference(before.crop(cursor_box), bitmap).getextrema()
    assert all(high <= 2 for _low, high in extrema), (scale, extrema)

    app.controls["left_x"].set_value(-512)
    app.controls["left_y"].set_value(512)
    yield lambda: True
    after = preview_snapshot("preview-left-moved")
    assert before.crop(cursor_box).tobytes() == after.crop(cursor_box).tobytes(), "Moving left dot shifted/resized cursor"
    assert before.crop(dot_box("right")).tobytes() == after.crop(dot_box("right")).tobytes(), "Moving left dot shifted/resized right dot"
    app.populate(values)
    app.controls["right_x"].set_value(512)
    app.controls["right_y"].set_value(512)
    yield lambda: True
    after = preview_snapshot("preview-right-moved")
    assert before.crop(cursor_box).tobytes() == after.crop(cursor_box).tobytes(), "Moving right dot shifted/resized cursor"
    assert before.crop(dot_box("left")).tobytes() == after.crop(dot_box("left")).tobytes(), "Moving right dot shifted/resized left dot"

    app.populate(values)
    app.backend_control.set_active_id("gnome")
    yield lambda: True
    shell = preview_snapshot("preview-gnome")
    assert_diameter(shell, "left", scale)
    assert_diameter(shell, "right", scale)
    assert before.crop(cursor_box).tobytes() == shell.crop(cursor_box).tobytes(), "Backend change resized cursor"
    app.populate(original)
    app.backend_control.set_active_id("x11")
    print(f"PASS: preview matches actual XFixes cursor pixels, backend dot sizes, and independent fixed positions ({bitmap.width}×{bitmap.height} cursor pixels, GTK scale {scale})")


def drag_checks():
    original = app.read_controls()
    scale = app.dots.get_scale_factor()
    values = {**original, "size": 24, "opacity": 1.0,
              "left_color": "#e11d48", "right_color": "#16a34a",
              "left_x": -60, "left_y": 20, "right_x": 80, "right_y": -35}

    def move_to(x, y):
        _success, ox, oy = app.dots.get_window().get_origin()
        subprocess.run(["xdotool", "mousemove", str(round((ox + x) * scale)),
                        str(round((oy + y) * scale))], check=True)

    def drag(side, backend, dx=32, dy=-16, name=None, pixel_check=True):
        before_values = app.read_controls()
        unit = 1 / scale if backend == "x11" else 1
        cx, cy = app.dots.get_allocated_width() // 2, app.dots.get_allocated_height() // 2
        # Grab off-center to ensure the dot does not jump under the pointer.
        x = cx + (before_values[f"{side}_x"] + 16) * unit
        y = cy + (before_values[f"{side}_y"] + 15) * unit
        before = preview_snapshot(f"drag-{backend}-{side}-before")
        move_to(x, y)
        subprocess.run(["xdotool", "mousedown", "1"], check=True)
        yield lambda: True
        assert app.read_controls() == before_values, "Dot jumped on press"
        move_to(x + dx / scale, y + dy / scale)
        yield lambda: True
        conversion = 1 if backend == "x11" else 1 / scale
        expected_x = max(-512, min(512, round(before_values[f"{side}_x"] + dx * conversion)))
        expected_y = max(-512, min(512, round(before_values[f"{side}_y"] + dy * conversion)))
        actual = app.read_controls()
        assert actual[f"{side}_x"] == expected_x, (backend, side, actual, expected_x)
        assert actual[f"{side}_y"] == expected_y, (backend, side, actual, expected_y)
        other = "right" if side == "left" else "left"
        assert actual[f"{other}_x"] == before_values[f"{other}_x"]
        assert actual[f"{other}_y"] == before_values[f"{other}_y"]
        if pixel_check:
            after = preview_snapshot(f"drag-{backend}-{side}-after")
            anchor_x, anchor_y = cx * scale, cy * scale
            cursor_box = (anchor_x - 3, anchor_y - 3, anchor_x + 48, anchor_y + 48)
            assert before.crop(cursor_box).tobytes() == after.crop(cursor_box).tobytes(), "Drag shifted cursor"
            factor = 1 if backend == "x11" else scale
            ox, oy = anchor_x + before_values[f"{other}_x"] * factor, anchor_y + before_values[f"{other}_y"] * factor
            box = (ox, oy, ox + 24 * factor, oy + 24 * factor)
            assert before.crop(box).tobytes() == after.crop(box).tobytes(), "Drag shifted other dot"
        if name:
            capture(name)
        subprocess.run(["xdotool", "mouseup", "1"], check=True)
        yield lambda: True
        assert app.dragged_dot is None, "Drag did not end on release"

    for backend in ("x11", "gnome"):
        app.backend_control.set_active_id(backend)
        for side in ("left", "right"):
            app.populate(values)
            yield lambda: True
            yield from drag(side, backend, name=f"drag-{backend}-{side}")

    # An empty-space drag changes neither dot.
    unchanged = app.read_controls()
    move_to(5, 5)
    subprocess.run(["xdotool", "mousedown", "1"], check=True)
    yield lambda: True
    move_to(20, 10)
    yield lambda: True
    subprocess.run(["xdotool", "mouseup", "1"], check=True)
    yield lambda: True
    assert app.read_controls() == unchanged

    # The visually topmost (right) dot wins an overlapping hit.
    app.backend_control.set_active_id("x11")
    app.populate({**values, "left_x": 80, "left_y": -35})
    yield lambda: True
    yield from drag("right", "x11", pixel_check=False)

    # A gesture continues outside the preview and clamps to the allowed range.
    app.populate(values)
    yield lambda: True
    yield from drag("left", "x11", dx=700, dy=700, pixel_check=False)
    assert app.controls["left_x"].get_value() == 512
    assert app.controls["left_y"].get_value() == 512
    app.populate(values)
    yield lambda: True
    yield from drag("right", "x11", name="drag-saved")
    print(f"PASS: real pointer drags update both backends, preserve independent positions, handle overlap/empty space, and clamp outside the preview (GTK scale {scale})")


def close_with_ctrl_q():
    key = "boundary" if app.notebook.get_current_page() == 0 else "left_x"
    app.controls[key].grab_focus()
    subprocess.run(["xdotool", "windowfocus", "--sync", str(app.window.get_window().get_xid())], check=True)
    subprocess.run(["xdotool", "key", "ctrl+q"], check=True)


def edit_checks():
    saved = app.read_controls()
    def assert_dirty(expected):
        assert app.action_buttons["apply"].is_sensitive() == expected, "Wrong Apply sensitivity"
        assert app.action_buttons["discard"].is_sensitive() == expected, "Wrong Discard sensitivity"
    assert_dirty(False)
    capture("edits-clean")
    app.controls["left_x"].set_value(saved["left_x"] + 1)
    assert_dirty(True)
    app.controls["left_x"].set_value(saved["left_x"])
    assert_dirty(False)
    # Text entry can differ before GtkSpinButton commits its numeric value.
    app.controls["left_x"].set_text("31")
    assert_dirty(True)
    app.controls["left_x"].set_text("-")
    assert_dirty(True)
    app.action_buttons["discard"].clicked()
    assert app.controls["left_x"].get_text() == app.saved_spin_text["left_x"]
    assert_dirty(False)
    app.backend_control.set_active_id("gnome")
    assert_dirty(True)
    app.backend_control.set_active_id("x11")
    assert_dirty(False)
    opacity = saved["opacity"] + 0.05 - 0.05
    app.controls["opacity"].set_value(opacity)
    assert_dirty(False)
    color = Gdk.RGBA()
    color.parse("#e11d48")
    app.controls["left_color"].set_rgba(color)
    app.controls["left_color"].emit("color-set")
    app.controls["bottom_right_only"].set_active(True)
    app.backend_control.set_active_id("gnome")
    assert_dirty(True)
    painted_at = time.monotonic() + 0.4
    yield lambda: time.monotonic() >= painted_at
    capture("edits-dirty")
    app.action_buttons["discard"].clicked()
    assert app.read_controls() == saved
    assert app.backend_control.get_active_id() == "x11"
    assert_dirty(False)
    app.controls["left_x"].set_value(saved["left_x"] + 2)
    close_with_ctrl_q()
    yield lambda: not app.window.get_visible()
    assert app.tray.get_status() == configurator.AppIndicator.IndicatorStatus.ACTIVE
    app.menu_items[0].activate()
    yield lambda: app.window.get_visible()
    assert app.controls["left_x"].get_value() == saved["left_x"] + 2
    assert_dirty(True)
    app.action_buttons["discard"].clicked()
    assert_dirty(False)
    print("PASS: clean/edit/revert states, uncommitted text, discard of all settings/backend, and Ctrl+Q closes only the window")


def steps():
    assert app.window.get_visible()
    yield from edit_checks()
    app.controls["boundary"].set_value(50)
    assert app.controls["boundary"].get_value() == 49.5
    app.controls["boundary"].set_value(50)
    assert app.controls["boundary"].get_value() == 50.5
    app.controls["bottom_right_only"].set_active(True)
    assert app.controls["corner_top"].get_sensitive()
    app.controls["boundary"].set_value(65)
    app.controls["corner_top"].set_value(75)
    yield lambda: True
    capture("regions")
    app.notebook.set_current_page(1)
    yield lambda: True
    capture("indicators")
    yield from preview_checks()
    yield from drag_checks()
    app.window.close()
    yield lambda: not app.window.get_visible()
    app.menu_items[0].activate()
    assert app.window.get_visible()
    app.controls["left_y"].set_text("27")
    assert app.action_buttons["apply"].get_sensitive()
    app.perform("apply")
    yield lambda: not app.busy
    assert load_settings()["boundary"] == 65, app.status.get_text()
    assert load_settings()["left_y"] == 27, "Apply did not commit typed numeric text"
    assert load_settings()["right_x"] == 112 and load_settings()["right_y"] == -51, "Apply did not save dragged offsets"
    assert not app.action_buttons["apply"].get_sensitive(), "Successful Apply stayed dirty"
    app.perform("start")
    yield lambda: not app.busy and app.child is not None
    subprocess.run(["xdotool", "key", "197"], check=True)
    yield lambda: x11.button_down(3)
    old_pid = app.child.pid
    assert not app.action_buttons["apply"].get_sensitive()
    close_with_ctrl_q()
    yield lambda: not app.window.get_visible()
    assert app.child.pid == old_pid and app.child.poll() is None and x11.button_down(3), ("Ctrl+Q stopped toggles", app.child.pid, old_pid, app.child.poll(), x11.pointer())
    app.menu_items[0].activate()
    yield lambda: app.window.get_visible()
    app.controls["right_y"].set_value(-30)
    app.perform("apply")
    yield lambda: not app.busy
    assert app.child is not None and app.child.pid != old_pid, app.status.get_text()
    assert not x11.button_down(3), "Apply left the old button held"
    assert load_settings()["right_y"] == -30
    subprocess.run(["xdotool", "key", "202"], check=True)
    yield lambda: x11.button_down(1)
    # Stopping must work even if the unsaved form contains an invalid threshold.
    app.controls["boundary"].set_value(12.3)
    app.perform("stop")
    yield lambda: not app.busy
    assert app.child is None and not x11.button_down(1)
    # A refused update must preserve both saved settings and the edited preset.
    preset = remapper.preset_path(SimpleNamespace(name="Test Touchpad"))
    saved = configurator.SETTINGS_PATH.read_bytes()
    preset.write_text('[{"unrelated": true}]\n')
    app.controls["boundary"].set_value(80)
    app.perform("apply")
    yield lambda: not app.busy
    assert "Refusing to replace" in app.status.get_text()
    assert app.action_buttons["apply"].get_sensitive(), "Failed save lost the dirty state"
    assert configurator.SETTINGS_PATH.read_bytes() == saved
    assert preset.read_text() == '[{"unrelated": true}]\n'
    app.action_buttons["discard"].clicked()
    assert app.read_controls() == load_settings()
    assert not app.action_buttons["apply"].get_sensitive()
    app.perform("reset")
    assert app.action_buttons["apply"].get_sensitive(), "Reset to different defaults must be an edit"
    app.action_buttons["discard"].clicked()
    assert app.read_controls() == load_settings()
    assert not app.action_buttons["apply"].get_sensitive()
    assert all(child.poll() is not None for child in processes)
    print("PASS: GTK previews, tray Configure, persistence, Apply restart, Stop release, and rollback")
    app.quit_safely()


iterator = steps()
condition = lambda: True


def tick():
    global condition, failed
    try:
        if time.monotonic() - started > 40:
            raise TimeoutError(f"GTK smoke timed out: {app.status.get_text()}")
        if condition():
            condition = next(iterator)
    except StopIteration:
        return False
    except Exception:
        failed = True
        subprocess.run(["xdotool", "mouseup", "1"], check=False)
        traceback.print_exc()
        app.quit_safely()
        return False
    return True


with tempfile.TemporaryDirectory() as directory, patch.object(remapper, "CONFIG_PATH", directory), patch.object(
        remapper, "find_group", return_value=SimpleNamespace(key="test", name="Test Touchpad")), patch.object(
        configurator, "subprocess", SimpleNamespace(Popen=spawn_daemon)):
    app.register(None)
    app.activate()
    GLib.timeout_add(150, tick)
    app.run([sys.argv[0]])
x11.close()
sys.exit(1 if failed else 0)
