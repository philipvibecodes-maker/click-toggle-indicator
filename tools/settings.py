"""Shared, validated user settings; independent of GTK and Input Remapper."""

import json
import math
import os
from pathlib import Path
import re
import tempfile

SETTINGS_PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "click-toggle-indicator" / "settings.json"
DEFAULTS = {
    "boundary": 50.5,
    "bottom_right_only": False,
    "corner_top": 85.0,
    "left_color": "#3b82f6",
    "right_color": "#3b82f6",
    "left_x": -26,
    "left_y": 18,
    "right_x": 30,
    "right_y": 18,
    "size": 18,
    "opacity": 0.65,
}


def validate_settings(values):
    if not isinstance(values, dict) or values.keys() - DEFAULTS.keys():
        raise ValueError("Settings must be an object containing only known options")
    result = {**DEFAULTS, **values}
    for key in ("boundary", "corner_top"):
        value = result[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0.5 <= value <= 99.5:
            raise ValueError(f"{key} must be between 0.5 and 99.5 percent")
        if value == 50 or value * 2 != int(value * 2):
            raise ValueError(f"{key} must use half-percent steps; use 50.5 for the midpoint")
    if type(result["bottom_right_only"]) is not bool:
        raise ValueError("bottom_right_only must be true or false")
    for key in ("left_color", "right_color"):
        if not isinstance(result[key], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", result[key]):
            raise ValueError(f"{key} must be a #rrggbb color")
    for key in ("left_x", "left_y", "right_x", "right_y", "size"):
        low, high = (8, 96) if key == "size" else (-512, 512)
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise ValueError(f"{key} must be an integer between {low} and {high}")
    opacity = result["opacity"]
    if type(opacity) not in (int, float) or not math.isfinite(opacity) or not 0.05 <= opacity <= 1:
        raise ValueError("opacity must be between 0.05 and 1")
    return result


def load_settings(path=None):
    path = path or SETTINGS_PATH
    if not path.exists():
        return DEFAULTS.copy()
    return validate_settings(json.loads(path.read_text(encoding="utf-8")))


def save_settings(values, path=None):
    values = validate_settings(values)
    path = path or SETTINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".settings-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(values, stream, indent=4)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def appearance_args(values):
    values = validate_settings(values)
    options = {
        "color": "left_color", "right-color": "right_color",
        "offset-x": "left_x", "offset-y": "left_y",
        "right-offset-x": "right_x", "right-offset-y": "right_y",
        "size": "size", "opacity": "opacity",
    }
    return [item for option, key in options.items() for item in (f"--{option}", str(values[key]))]


if __name__ == "__main__":
    import sys
    try:
        # NUL-delimited arguments consumed by run.sh, never evaluated as shell code.
        sys.stdout.buffer.write(b"\0".join(arg.encode() for arg in appearance_args(load_settings())) + b"\0")
    except (OSError, ValueError) as error:
        sys.exit(f"Settings: {error}")
