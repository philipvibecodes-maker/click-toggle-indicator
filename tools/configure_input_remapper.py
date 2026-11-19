#!/usr/bin/env python3
"""Find the physical touchpad and install the Input Remapper bridge preset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from settings import SETTINGS_PATH, load_settings, validate_settings

from evdev import ecodes
from inputremapper.configs.paths import CONFIG_PATH, sanitize_path_component
from inputremapper.groups import groups

PRESET_NAME = "click-toggle-indicator"
SELECTION_PATH = SETTINGS_PATH.with_name("device.json")
LEGACY_PRESET = [
    {
        "input_combination": [{"type": ecodes.EV_KEY, "code": ecodes.BTN_LEFT}],
        "target_uinput": "mouse",
        "output_symbol": "BTN_SIDE",
    }
]
BOTTOM_RIGHT_PRESET = [
    {
        "input_combination": [
            {"type": ecodes.EV_ABS, "code": ecodes.ABS_X, "analog_threshold": 1},
            {"type": ecodes.EV_ABS, "code": ecodes.ABS_Y, "analog_threshold": 70},
            {"type": ecodes.EV_KEY, "code": ecodes.BTN_LEFT},
        ],
        "target_uinput": "keyboard",
        "output_symbol": "KEY_F19",
    },
    {
        "input_combination": [{"type": ecodes.EV_KEY, "code": ecodes.BTN_LEFT}],
        "target_uinput": "keyboard",
        "output_symbol": "KEY_F24",
    }
]
PRESET = [
    {
        "input_combination": [
            {"type": ecodes.EV_ABS, "code": ecodes.ABS_X, "analog_threshold": 1},
            {"type": ecodes.EV_KEY, "code": ecodes.BTN_LEFT},
        ],
        "target_uinput": "keyboard",
        "output_symbol": "KEY_F19",
    },
    BOTTOM_RIGHT_PRESET[1],
]


def build_preset(settings):
    """Describe a right-side rectangle using the remapper's signed half axes.

    Positive thresholds select ABOVE the midpoint, negative ones select BELOW.
    Below-midpoint boundaries therefore describe exclusions. More-specific
    combinations override less-specific mappings, just like the original preset.
    """
    settings = validate_settings(settings)
    inside, outside = [], []
    axes = [(ecodes.ABS_X, settings["boundary"])]
    if settings["bottom_right_only"]:
        axes.append((ecodes.ABS_Y, settings["corner_top"]))
    for code, percent in axes:
        threshold = int(percent * 2 - 100)
        event = {"type": ecodes.EV_ABS, "code": code, "analog_threshold": threshold}
        (inside if threshold > 0 else outside).append(event)
    click = {"type": ecodes.EV_KEY, "code": ecodes.BTN_LEFT}

    def mapping(conditions, symbol):
        return {"input_combination": [*conditions, click],
                "target_uinput": "keyboard", "output_symbol": symbol}

    return [mapping([*inside, exclusion], "KEY_F24") for exclusion in outside] + [
        mapping(inside, "KEY_F19")
    ] + ([mapping([], "KEY_F24")] if inside else [])


def preset_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def is_saved_preset(group, value):
    try:
        selection = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
        return (selection.get("key") == group.key and selection.get("name") == group.name
                and selection.get("preset_digest") == preset_digest(value))
    except (OSError, ValueError, AttributeError):
        return False


def is_project_legacy_preset(value) -> bool:
    """Recognize older generated presets even after the GUI adds metadata."""
    if not isinstance(value, list) or not value:
        return False
    known = {
        (ecodes.BTN_LEFT, "mouse", "BTN_SIDE"),
        (ecodes.BTN_LEFT, "keyboard", "KEY_F24"),
        (ecodes.BTN_RIGHT, "keyboard", "KEY_F19"),
    }
    identities = set()
    for mapping in value:
        if not isinstance(mapping, dict):
            return False
        combination = mapping.get("input_combination")
        if not isinstance(combination, list) or len(combination) != 1:
            return False
        event = combination[0]
        identity = (
            event.get("code"),
            mapping.get("target_uinput"),
            mapping.get("output_symbol"),
        )
        if event.get("type") != ecodes.EV_KEY or identity not in known:
            return False
        identities.add(identity)
    return (ecodes.BTN_LEFT, "keyboard", "KEY_F24") in identities or (
        ecodes.BTN_LEFT,
        "mouse",
        "BTN_SIDE",
    ) in identities


def is_physical_touchpad(group) -> bool:
    """Check capabilities across every event node in the device group."""
    has_left = False
    has_touch = False
    for device in group.get_devices():
        keys = device.capabilities(absinfo=False).get(ecodes.EV_KEY, [])
        has_left = has_left or ecodes.BTN_LEFT in keys
        has_touch = has_touch or ecodes.BTN_TOUCH in keys
    return has_left and has_touch


def looks_like_touchpad(group) -> bool:
    """Fallback when the unprivileged process cannot inspect raw capabilities."""
    names = " ".join([group.key, group.name, *group.names])
    return re.search(r"touch[ -]?pad|track[ -]?pad|click[ -]?pad", names, re.I) is not None


def saved_group():
    if not SELECTION_PATH.exists():
        return None
    try:
        selection = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
        return SimpleNamespace(
            key=selection["key"], name=selection["name"], names=[selection["name"]]
        )
    except (KeyError, OSError, json.JSONDecodeError, TypeError):
        return None


def xinput_groups():
    """Use X11 device names when raw evdev enumeration is not permitted."""
    try:
        result = subprocess.run(
            ["xinput", "list", "--name-only"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []
    names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    names = [
        name
        for name in names
        if re.search(r"touch[ -]?pad|track[ -]?pad|click[ -]?pad", name, re.I)
    ]
    return [SimpleNamespace(key=name, name=name, names=[name]) for name in names]


def privileged_groups():
    """Ask Input Remapper's root-side scanner for exact group keys and names."""
    probe = """import json
from evdev import ecodes
from inputremapper.groups import groups
data = []
for group in groups.filter():
    keys = set()
    for device in group.get_devices():
        keys.update(device.capabilities(absinfo=False).get(ecodes.EV_KEY, []))
    data.append({
        'key': group.key,
        'name': group.name,
        'names': group.names,
        'physical_touchpad': ecodes.BTN_LEFT in keys and ecodes.BTN_TOUCH in keys,
    })
print('CTI_GROUPS=' + json.dumps(data))
"""
    try:
        result = subprocess.run(
            ["pkexec", "/usr/bin/python3", "-c", probe],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []
    for line in reversed(result.stdout.splitlines()):
        if line.startswith("CTI_GROUPS="):
            try:
                raw_groups = json.loads(line.removeprefix("CTI_GROUPS="))
                return [SimpleNamespace(**group) for group in raw_groups]
            except (json.JSONDecodeError, TypeError):
                return []
    return []


def find_group(use_saved: bool = True):
    requested = os.environ.get("INPUT_REMAPPER_DEVICE")
    if requested:
        group = groups.find(key=requested)
        if group is not None:
            return group
        privileged = privileged_groups()
        root_group = next((group for group in privileged if group.key == requested), None)
        if root_group is None:
            choices = ", ".join(repr(group.key) for group in privileged) or "none"
            raise RuntimeError(
                f"{requested!r} is not an Input Remapper device key. Root-visible "
                f"keys: {choices}. Use one of those exact values."
            )
        return root_group

    if use_saved:
        saved = saved_group()
        if saved is not None:
            return saved

    available = groups.filter()
    matches = [group for group in available if is_physical_touchpad(group)]
    if not matches:
        matches = [group for group in available if looks_like_touchpad(group)]
    if not matches:
        privileged = privileged_groups()
        matches = [
            group
            for group in privileged
            if looks_like_touchpad(group)
            or getattr(group, "physical_touchpad", False)
        ]
    if not matches:
        matches = xinput_groups()
    if not matches:
        keys = ", ".join(repr(group.key) for group in available) or "none"
        raise RuntimeError(
            "No touchpad could be detected through evdev or XInput. Available Input "
            f"Remapper device keys: {keys}. Set INPUT_REMAPPER_DEVICE to the exact "
            "device name shown in the Input Remapper GUI."
        )
    if len(matches) > 1:
        names = ", ".join(repr(group.key) for group in matches)
        raise RuntimeError(
            f"Multiple touchpads were found: {names}. Set INPUT_REMAPPER_DEVICE."
        )
    return matches[0]


def preset_path(group) -> Path:
    device_dir = sanitize_path_component(group.name)
    return Path(CONFIG_PATH) / "presets" / device_dir / f"{PRESET_NAME}.json"


def install(group, force: bool, settings=None) -> Path:
    preset = build_preset(load_settings() if settings is None else settings)
    path = preset_path(group)
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Cannot read existing preset {path}: {error}") from error
        if (existing not in (PRESET, BOTTOM_RIGHT_PRESET, LEGACY_PRESET)
                and not is_project_legacy_preset(existing)
                and not is_saved_preset(group, existing) and not force):
            raise RuntimeError(
                f"Refusing to replace the existing preset {path}. "
                "Re-run ./setup.sh --force to replace it."
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(preset, indent=4) + "\n", encoding="utf-8")

    config_path = Path(CONFIG_PATH) / "config.json"
    if not config_path.exists():
        config_path.write_text("{}\n", encoding="utf-8")

    SELECTION_PATH.parent.mkdir(parents=True, exist_ok=True)
    SELECTION_PATH.write_text(
        json.dumps({"key": group.key, "name": group.name,
                    "preset_digest": preset_digest(preset)}, indent=4) + "\n",
        encoding="utf-8",
    )
    return path


def daemon_action(group, start: bool) -> None:
    """Bypass the CLI's unprivileged evdev scan and call its root daemon."""
    from inputremapper.daemon import Daemon

    daemon = Daemon.connect()
    if daemon is None:
        raise RuntimeError("Could not connect to the Input Remapper service.")
    daemon.set_config_dir(CONFIG_PATH)
    if start:
        if not daemon.start_injecting(group.key, PRESET_NAME):
            raise RuntimeError(
                f"Input Remapper could not start preset {PRESET_NAME!r} for "
                f"{group.key!r}. Set INPUT_REMAPPER_DEVICE to the exact name shown "
                "in the Input Remapper GUI and run ./setup.sh again."
            )
    else:
        daemon.stop_injecting(group.key)
    # D-Bus acknowledges the request before the injector has grabbed/released its
    # device. In particular, restarting immediately can race the previous grab.
    deadline = time.monotonic() + 5
    stopped_states = {"STOPPED", "UNKNOWN", "FAILED", "NO_GRAB", "UPGRADE_EVDEV"}
    while time.monotonic() < deadline:
        state = daemon.get_state(group.key)
        if (start and state == "RUNNING") or (not start and state in stopped_states):
            return
        if start and state in stopped_states - {"UNKNOWN"}:
            raise RuntimeError(f"Input Remapper injector did not start: {state}")
        time.sleep(0.05)
    raise RuntimeError("Timed out waiting for Input Remapper to " + ("start" if start else "stop"))


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--find-key", action="store_true")
    action.add_argument("--install", action="store_true")
    action.add_argument("--start", action="store_true")
    action.add_argument("--stop", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    try:
        group = find_group(use_saved=not args.install)
        if args.find_key:
            print(group.key)
        elif args.install:
            path = install(group, args.force)
            print(f"Installed {path}")
            print("Input:  EV_KEY/BTN_LEFT (1:272), the physical switch")
            print("Output: EV_KEY/KEY_F24 (1:194), X11 keycode 202")
            print("Input:  configured click region + BTN_LEFT combination")
            print("Output: EV_KEY/KEY_F19 (1:189), X11 keycode 197")
            print("BTN_TOUCH (330), used by tap-to-click, is not mapped.")
            print(f"Saved device selection: {group.key}")
        elif args.start:
            daemon_action(group, start=True)
        else:
            daemon_action(group, start=False)
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
