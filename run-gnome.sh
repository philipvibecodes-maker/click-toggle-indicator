#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ ${XDG_SESSION_TYPE:-x11} != x11 ]]; then
    echo "The prototype display uses GNOME Shell; its input backend still requires X11." >&2
    exit 1
fi
if (( $# != 0 )); then
    echo "Usage: ./run-gnome.sh (appearance constants are in gnome-extension/extension.js)" >&2
    exit 1
fi

# Reuse the launcher's Input Remapper lifecycle and its signal cleanup.
export CLICK_TOGGLE_GNOME=1
exec "$project_dir/run.sh"
