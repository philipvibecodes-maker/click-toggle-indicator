#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
indicator="$project_dir/click-toggle-indicator"

if [[ ${XDG_SESSION_TYPE:-x11} != x11 ]]; then
    echo "click-toggle-indicator requires an X11 session (current: ${XDG_SESSION_TYPE:-unknown})." >&2
    exit 1
fi

for command in python3; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "Missing required command: $command" >&2
        echo "Run ./setup.sh after installing input-remapper." >&2
        exit 1
    fi
done

indicator_pid=
stopped=0
cleanup() {
    trap - EXIT INT TERM HUP
    [[ -z ${indicator_pid:-} ]] || kill "$indicator_pid" 2>/dev/null || true
    [[ -z ${indicator_pid:-} ]] || wait "$indicator_pid" 2>/dev/null || true
    if (( stopped == 0 )); then
        stopped=1
        python3 "$project_dir/tools/configure_input_remapper.py" --stop >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT INT TERM HUP

if ! python3 "$project_dir/tools/configure_input_remapper.py" --start; then
    echo "Could not start the Input Remapper preset. Re-run ./setup.sh to probe the" >&2
    echo "root-visible device keys, then retry." >&2
    exit 1
fi

if [[ ${CLICK_TOGGLE_GNOME:-0} == 1 ]]; then
    /usr/bin/python3 "$project_dir/tools/gnome_indicator_bridge.py" &
else
    "$indicator" --toggle-keycode 202 --hold-button 1 \
        --right-toggle-keycode 197 --right-hold-button 3 \
        --offset-x -26 --right-offset-x 30 --offset-y 18 "$@" &
fi
indicator_pid=$!

echo "Left-half click holds button 1; right-half click holds button 3."
echo "While either button is held, a physical click anywhere releases it."
echo "The left indicator appears left of the cursor; the right indicator appears right."
echo "Press Ctrl-C to stop."

set +e
wait "$indicator_pid"
status=$?
set -e
exit "$status"
