#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
indicator="$project_dir/click-toggle-indicator"

if [[ ${XDG_SESSION_TYPE:-x11} != x11 ]]; then
    echo "click-toggle-indicator requires an X11 session (current: ${XDG_SESSION_TYPE:-unknown})." >&2
    exit 1
fi

for command in python3 flock; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "Missing required command: $command" >&2
        echo "Run ./setup.sh after installing input-remapper." >&2
        exit 1
    fi
done

settings_file=$(mktemp)
if ! /usr/bin/python3 "$project_dir/tools/settings.py" >"$settings_file"; then
    rm -f "$settings_file"
    exit 1
fi
mapfile -d '' -t appearance_args <"$settings_file"
rm -f "$settings_file"

# Every launcher shares this lock, including instances started by the tray app.
lock_dir=${XDG_RUNTIME_DIR:-/tmp/click-toggle-indicator-$UID}
mkdir -p "$lock_dir"
exec 9>"$lock_dir/click-toggle-indicator.lock"
if ! flock -n 9; then
    echo "Click toggles are already running. Stop the other launcher first." >&2
    exit 1
fi

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
        "${appearance_args[@]}" "$@" &
fi
indicator_pid=$!

echo "Clicks in the configured left/right regions hold buttons 1/3."
echo "While either button is held, a physical click anywhere releases it."
echo "Indicator colors and offsets come from saved settings or launcher options."
echo "Press Ctrl-C to stop."

set +e
wait "$indicator_pid"
status=$?
set -e
exit "$status"
