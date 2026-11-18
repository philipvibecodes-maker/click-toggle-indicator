"""Live X11 end-to-end tests for the virtual touchpad and toggle daemons."""

import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest

from e2e_support import X11, click, stop_process, wait_for_button

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tools"))


def xdotool(*args):
    return subprocess.run(["xdotool", *map(str, args)], check=True,
                          capture_output=True, text=True).stdout.strip()


def window_geometry(window):
    info = subprocess.run(["xwininfo", "-id", str(window)],
                          check=True, capture_output=True, text=True).stdout
    tree = subprocess.run(["xwininfo", "-id", str(window), "-tree"],
                          check=True, capture_output=True, text=True).stdout
    x = re.search(r"Absolute upper-left X:\s+(-?\d+)", info)
    y = re.search(r"Absolute upper-left Y:\s+(-?\d+)", info)
    parent = re.search(r"Parent window id:\s+(0x[0-9a-fA-F]+)", tree)
    if not (x and y and parent):
        raise RuntimeError(f"could not inspect X11 window {window}")
    return int(x.group(1)), int(y.group(1)), int(parent.group(1), 16)


def private_terminal_servers(marker):
    app_id = f"com.canonical.Terminal.{marker}"
    for cmdline in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            args = [part.decode() for part in cmdline.read_bytes().split(b"\0") if part]
        except (OSError, UnicodeDecodeError):
            continue
        options = dict(zip(args[1::2], args[2::2]))
        if (args and args[0] == "/usr/libexec/gnome-terminal-server" and
            options.get("--app-id") == app_id and options.get("--class") == marker):
            yield int(cmdline.parent.name)


class TouchpadEndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get("DISPLAY") or not os.access("/dev/uinput", os.W_OK):
            raise unittest.SkipTest("live X11 DISPLAY and writable /dev/uinput required")
        missing = [command for command in ("gnome-terminal", "xdotool", "xwininfo", "xprop")
                   if not shutil.which(command)]
        if missing:
            raise RuntimeError(f"missing end-to-end test tools: {', '.join(missing)}")
        try:
            from evdev import AbsInfo, UInput, ecodes
            from inputremapper.configs.paths import CONFIG_PATH
            from inputremapper.daemon import Daemon
            from configure_input_remapper import PRESET, PRESET_NAME, preset_path
        except ImportError as error:
            raise unittest.SkipTest(f"Input Remapper and evdev required: {error}") from error

        cls.ecodes = ecodes
        cls.x11 = X11()
        cls.device = None
        cls.daemon = None
        cls.injecting = False
        cls.processes = []
        cls.preset = None
        cls.created_preset = False
        cls.created_config = None
        cls.name = f"CTI E2E Touchpad {os.getpid()}"
        cls.addClassCleanup(cls.cleanup_resources)

        if cls.x11.button_down(1) or cls.x11.button_down(3):
            raise RuntimeError("release mouse buttons before running the live test")
        cls.daemon = Daemon.connect()
        if cls.daemon is None:
            raise unittest.SkipTest("Input Remapper service is unavailable")
        cls.daemon.set_config_dir(CONFIG_PATH)

        capabilities = {
            ecodes.EV_KEY: [ecodes.BTN_LEFT, ecodes.BTN_TOUCH],
            ecodes.EV_ABS: [
                (ecodes.ABS_X, AbsInfo(100, 0, 1000, 0, 0, 10)),
                (ecodes.ABS_Y, AbsInfo(500, 0, 1000, 0, 0, 10)),
            ],
        }
        cls.device = UInput(capabilities, name=cls.name,
                            input_props=[ecodes.INPUT_PROP_POINTER,
                                         ecodes.INPUT_PROP_BUTTONPAD])
        cls.preset = preset_path(SimpleNamespace(name=cls.name))
        if cls.preset.exists():
            raise RuntimeError(f"test preset already exists: {cls.preset}")
        cls.preset.parent.mkdir(parents=True, exist_ok=True)
        cls.preset.write_text(json.dumps(PRESET, indent=4) + "\n", encoding="utf-8")
        cls.created_preset = True
        config = Path(CONFIG_PATH) / "config.json"
        if not config.exists():
            config.write_text("{}\n", encoding="utf-8")
            cls.created_config = config

        time.sleep(0.5)
        if not cls.daemon.start_injecting(cls.name, PRESET_NAME):
            raise RuntimeError("Input Remapper could not start the virtual touchpad preset")
        cls.injecting = True
        cls.processes.append(subprocess.Popen(
            [str(PROJECT / "click-toggle-indicator"), "--toggle-keycode", "202",
             "--hold-button", "1", "--right-toggle-keycode", "197",
             "--right-hold-button", "3", "--offset-x", "-26",
             "--right-offset-x", "30", "--offset-y", "18"],
            stdout=subprocess.DEVNULL,
        ))
        time.sleep(0.2)
        for process in cls.processes:
            if process.poll() is not None:
                raise RuntimeError(f"toggle daemon exited with status {process.returncode}")

    @classmethod
    def cleanup_resources(cls):
        cls.x11.ungrab_keyboard()
        if cls.device is not None and cls.injecting:
            for button, position in ((1, 100), (3, 900)):
                if cls.x11.button_down(button):
                    click(cls.device, position, cls.ecodes)
                    time.sleep(0.1)
        for process in cls.processes:
            stop_process(process)
        if cls.injecting:
            cls.daemon.stop_injecting(cls.name)
        if cls.device is not None:
            cls.device.close()
        cls.x11.close()
        if cls.created_preset:
            cls.preset.unlink()
            cls.preset.parent.rmdir()
        if cls.created_config is not None:
            cls.created_config.unlink()

    def setUp(self):
        self.assertFalse(self.x11.button_down(1))
        self.assertFalse(self.x11.button_down(3))

    def tearDown(self):
        self.x11.ungrab_keyboard()
        for button, position in ((1, 100), (3, 900)):
            if self.x11.button_down(button):
                click(self.device, position, self.ecodes)
                wait_for_button(self.x11, button, False, self.processes)

    def toggle(self, position, button, down):
        click(self.device, position, self.ecodes)
        wait_for_button(self.x11, button, down, self.processes)
        other_button = 3 if button == 1 else 1
        self.assertFalse(self.x11.button_down(other_button),
                         f"button {other_button} was toggled unexpectedly")

    def test_left_click_toggle(self):
        self.toggle(100, 1, True)
        self.toggle(100, 1, False)

    def test_right_click_toggle(self):
        self.toggle(900, 3, True)
        self.toggle(900, 3, False)

    def test_crossing_midpoint_during_click(self):
        for start, finish, button, other in ((100, 900, 1, 3),
                                             (900, 100, 3, 1)):
            self.device.write(self.ecodes.EV_ABS, self.ecodes.ABS_X, start)
            self.device.write(self.ecodes.EV_KEY, self.ecodes.BTN_TOUCH, 1)
            self.device.syn()
            time.sleep(0.08)
            self.device.write(self.ecodes.EV_KEY, self.ecodes.BTN_LEFT, 1)
            self.device.syn()
            time.sleep(0.08)
            self.device.write(self.ecodes.EV_ABS, self.ecodes.ABS_X, finish)
            self.device.syn()
            time.sleep(0.08)
            self.device.write(self.ecodes.EV_KEY, self.ecodes.BTN_LEFT, 0)
            self.device.write(self.ecodes.EV_KEY, self.ecodes.BTN_TOUCH, 0)
            self.device.syn()
            wait_for_button(self.x11, button, True, self.processes)
            self.assertFalse(self.x11.button_down(other))
            click(self.device, start, self.ecodes)
            wait_for_button(self.x11, button, False, self.processes)

    def test_left_click_during_keyboard_grab(self):
        self.x11.grab_keyboard()
        self.toggle(100, 1, True)
        self.toggle(100, 1, False)

    def test_terminal_titlebar_drag(self):
        marker = f"CTIE2E{os.getpid()}"
        title = f"CTI E2E Terminal {os.getpid()}"
        old_x, old_y, _ = self.x11.pointer()
        window = None
        terminal = subprocess.Popen(
            ["gnome-terminal", "--disable-factory", "--class", marker,
             "--window", f"--title={title}", "--", "bash", "-c", "sleep 30"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                result = subprocess.run(["xdotool", "search", "--class",
                                         f"^{marker}$"],
                                        capture_output=True, text=True)
                if result.returncode == 0 and result.stdout.strip():
                    for candidate in result.stdout.splitlines():
                        if xdotool("getwindowname", candidate) == title:
                            window = candidate
                            break
                    if window is not None:
                        break
                time.sleep(0.05)
            self.assertIsNotNone(window, "test terminal did not open")
            identity = subprocess.run(["xprop", "-id", window, "_NET_WM_PID", "WM_CLASS"],
                                      check=True, capture_output=True, text=True).stdout
            server_pid = re.search(r"_NET_WM_PID\(CARDINAL\) = (\d+)", identity)
            self.assertIsNotNone(server_pid, "terminal window has no server PID")
            self.assertIn(int(server_pid.group(1)), list(private_terminal_servers(marker)),
                          "terminal window does not belong to the private server")
            self.assertIn(f'"{marker}"', identity)
            xdotool("windowmove", window, 120, 120)
            xdotool("windowactivate", "--sync", window)
            time.sleep(0.3)
            before_x, before_y, _ = window_geometry(window)

            # GNOME Terminal's header bar lies inside its window after the shadow.
            xdotool("mousemove", before_x + 150, before_y + 75)
            pointer_x, pointer_y, _ = self.x11.pointer()
            location = dict(line.split("=", 1) for line in
                            xdotool("getmouselocation", "--shell").splitlines())
            self.assertEqual(int(location["WINDOW"]), int(window),
                          "pointer did not land on the dedicated terminal")
            self.toggle(100, 1, True)
            time.sleep(0.15)
            for step in range(1, 6):
                xdotool("mousemove", "--sync", pointer_x + 44 * step,
                        pointer_y + 20 * step)
                time.sleep(0.04)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                moved_x, moved_y, _ = window_geometry(window)
                if abs(moved_x - before_x) > 30 or abs(moved_y - before_y) > 30:
                    break
                time.sleep(0.05)
            else:
                self.fail("terminal did not move while synthetic button 1 was held")

            self.toggle(100, 1, False)
            released = window_geometry(window)[:2]
            pointer_x, pointer_y, _ = self.x11.pointer()
            xdotool("mousemove", "--sync", pointer_x + 80, pointer_y + 50)
            time.sleep(0.2)
            self.assertEqual(window_geometry(window)[:2], released,
                             "terminal continued dragging after the second touchpad click")
        finally:
            stop_process(terminal)
            for server_pid in private_terminal_servers(marker):
                try:
                    os.kill(server_pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            xdotool("mousemove", old_x, old_y)
