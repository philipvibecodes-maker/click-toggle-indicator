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

left_pid=
right_pid=
stopped=0
cleanup() {
    trap - EXIT INT TERM HUP
    [[ -z ${left_pid:-} ]] || kill "$left_pid" 2>/dev/null || true
    [[ -z ${right_pid:-} ]] || kill "$right_pid" 2>/dev/null || true
    [[ -z ${left_pid:-} ]] || wait "$left_pid" 2>/dev/null || true
    [[ -z ${right_pid:-} ]] || wait "$right_pid" 2>/dev/null || true
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

"$indicator" --toggle-keycode 202 --hold-button 1 \
    --offset-x -26 --offset-y 18 "$@" &
left_pid=$!
"$indicator" --toggle-keycode 197 --hold-button 3 \
    --offset-x 30 --offset-y 18 "$@" &
right_pid=$!

echo "Left-half click toggles button 1; right-half click toggles button 3."
echo "The left indicator appears left of the cursor; the right indicator appears right."
echo "Press Ctrl-C to stop."

set +e
wait -n "$left_pid" "$right_pid"
status=$?
set -e
exit "$status"
