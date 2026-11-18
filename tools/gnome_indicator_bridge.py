#!/usr/bin/python3
"""Forward daemon state to Shell; leave cursor movement entirely inside Shell."""

import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

from gi.repository import Gio, GLib

OBJECT_PATH = "/org/gnome/Shell/Extensions/ClickToggleIndicator"
INTERFACE = "org.gnome.Shell.Extensions.ClickToggleIndicator"
RUNNING = True


def stop(_signum, _frame):
    global RUNNING
    RUNNING = False


def main():
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, stop)
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def set_state(state):
        bus.call_sync(
            "org.gnome.Shell", OBJECT_PATH, INTERFACE, "SetState",
            GLib.Variant("(u)", (state,)), None,
            Gio.DBusCallFlags.NO_AUTO_START, 500, None,
        )

    # Fail before starting input handling if the extension is unavailable.
    set_state(0)
    daemon = Path(__file__).resolve().parents[1] / "click-toggle-indicator"
    child = subprocess.Popen([
        str(daemon), "--toggle-keycode", "202", "--hold-button", "1",
        "--right-toggle-keycode", "197", "--right-hold-button", "3",
        "--state-stdout",
    ], stdout=subprocess.PIPE)
    state = 0
    pending = b""
    last_update = time.monotonic()
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            while RUNNING:
                if selector.select(timeout=0.25):
                    chunk = os.read(child.stdout.fileno(), 4096)
                    if not chunk:
                        return child.wait()
                    pending += chunk
                    while b"\n" in pending:
                        line, pending = pending.split(b"\n", 1)
                        if line not in (b"0", b"1", b"2"):
                            raise RuntimeError("Invalid daemon state")
                        state = int(line)
                        set_state(state)
                        last_update = time.monotonic()
                if time.monotonic() - last_update >= 0.5:
                    set_state(state)
                    last_update = time.monotonic()
    finally:
        # Release the XTEST button before clearing the display. Closing the read
        # pipe also makes subsequent daemon writes fail safely if we disappear.
        child.terminate()
        child.wait()
        child.stdout.close()
        try:
            set_state(0)
        except GLib.Error:
            pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (GLib.Error, OSError, RuntimeError) as error:
        print(f"GNOME indicator bridge: {error}", file=sys.stderr)
        print("Enable click-toggle-indicator@personal-utilities in GNOME Shell 46.",
              file=sys.stderr)
        sys.exit(1)
