#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
test_dir=$(mktemp -d)
trap 'rm -rf "$test_dir"' EXIT
mkdir -p "$test_dir/runtime" "$test_dir/data" "$test_dir/config"
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
env -u SNAP -u SNAP_NAME -u GTK_MODULES \
    XDG_RUNTIME_DIR="$test_dir/runtime" XDG_DATA_HOME="$test_dir/data" \
    XDG_CONFIG_HOME="$test_dir/config" XDG_DATA_DIRS=/usr/share \
    XDG_SESSION_TYPE=x11 NO_AT_BRIDGE=1 GSETTINGS_BACKEND=keyfile \
    xvfb-run -a -s '-screen 0 1024x768x24' \
    dbus-run-session --config-file "$test_dir/bus.conf" -- \
    /usr/bin/python3 "$project_dir/tests/gnome-smoke.py" \
    "${1:-$project_dir/artifacts/gnome}"
