#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
for command in xvfb-run dbus-run-session xdotool; do
    if ! command -v "$command" >/dev/null; then
        echo "SKIP: GTK smoke test needs $command"
        exit 0
    fi
done

test_dir=$(mktemp -d)
trap 'rm -rf "$test_dir"' EXIT
# A private bus without desktop service activation avoids contacting the real
# desktop, secret store, portals, or accessibility services during the test.
cat >"$test_dir/bus.conf" <<'XML'
<busconfig>
    <type>session</type>
    <listen>unix:tmpdir=/tmp</listen>
    <auth>EXTERNAL</auth>
    <policy context="default">
        <allow send_destination="*"/>
        <allow receive_sender="*"/>
        <allow own="*"/>
    </policy>
</busconfig>
XML
mkdir -p "$test_dir/runtime"
env -u SNAP -u SNAP_NAME -u GTK_MODULES \
    XDG_RUNTIME_DIR="$test_dir/runtime" XDG_CONFIG_HOME="$test_dir/config" \
    XDG_SESSION_TYPE=x11 NO_AT_BRIDGE=1 GSETTINGS_BACKEND=memory \
    XCURSOR_THEME=Adwaita XCURSOR_SIZE=${CTI_TEST_CURSOR_SIZE:-24} \
    xvfb-run -a -s '-screen 0 1920x1800x24' dbus-run-session --config-file "$test_dir/bus.conf" -- \
    /usr/bin/python3 "$project_dir/tests/gtk-smoke.py" "${1:-$test_dir/screenshots}"
