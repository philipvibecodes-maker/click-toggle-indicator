"""X11 and virtual-touchpad helpers for the live end-to-end tests."""

import ctypes
import subprocess
import time


class X11:
    BUTTON_MASKS = {1: 1 << 8, 3: 1 << 10}

    def __init__(self):
        self.lib = ctypes.CDLL("libX11.so.6")
        self.lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.lib.XOpenDisplay.restype = ctypes.c_void_p
        self.lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        self.lib.XDefaultRootWindow.restype = ctypes.c_ulong
        self.lib.XQueryPointer.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_uint),
        ]
        self.lib.XQueryPointer.restype = ctypes.c_int
        self.lib.XGrabKeyboard.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                           ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_ulong]
        self.lib.XGrabKeyboard.restype = ctypes.c_int
        self.lib.XUngrabKeyboard.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.lib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self.display = self.lib.XOpenDisplay(None)
        if not self.display:
            raise RuntimeError("cannot open the X11 display")
        self.root = self.lib.XDefaultRootWindow(self.display)
        self.grabbed = False

    def pointer(self):
        root = ctypes.c_ulong()
        child = ctypes.c_ulong()
        root_x = ctypes.c_int()
        root_y = ctypes.c_int()
        window_x = ctypes.c_int()
        window_y = ctypes.c_int()
        mask = ctypes.c_uint()
        if not self.lib.XQueryPointer(
            self.display, self.root, ctypes.byref(root), ctypes.byref(child),
            ctypes.byref(root_x), ctypes.byref(root_y),
            ctypes.byref(window_x), ctypes.byref(window_y), ctypes.byref(mask)
        ):
            raise RuntimeError("XQueryPointer failed")
        return root_x.value, root_y.value, mask.value

    def button_down(self, button):
        return bool(self.pointer()[2] & self.BUTTON_MASKS[button])

    def grab_keyboard(self, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.lib.XGrabKeyboard(self.display, self.root, 0, 1, 1, 0) == 0:
                self.lib.XSync(self.display, 0)
                self.grabbed = True
                return
            time.sleep(0.05)
        raise RuntimeError("another client still owns the keyboard grab")

    def ungrab_keyboard(self):
        if self.grabbed:
            self.lib.XUngrabKeyboard(self.display, 0)
            self.lib.XSync(self.display, 0)
            self.grabbed = False

    def close(self):
        self.ungrab_keyboard()
        self.lib.XCloseDisplay(self.display)


def click(device, x, ecodes):
    device.write(ecodes.EV_ABS, ecodes.ABS_X, x)
    device.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, 1)
    device.syn()
    time.sleep(0.08)
    device.write(ecodes.EV_KEY, ecodes.BTN_LEFT, 1)
    device.syn()
    time.sleep(0.08)
    device.write(ecodes.EV_KEY, ecodes.BTN_LEFT, 0)
    device.syn()
    device.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, 0)
    device.syn()


def wait_for_button(x11, button, down, processes, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for process in processes:
            if process.poll() is not None:
                raise RuntimeError(f"toggle daemon exited with status {process.returncode}")
        if x11.button_down(button) == down:
            return
        time.sleep(0.02)
    raise AssertionError(f"button {button} did not become {'down' if down else 'up'}")


def stop_process(process):
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
