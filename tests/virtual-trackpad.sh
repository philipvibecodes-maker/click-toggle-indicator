#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
test_dir=$(mktemp -d)
trap 'rm -rf "$test_dir"' EXIT
# Multiplexers can inherit another login identity. Resolve the effective user for
# Input Remapper in this test and its Python subprocesses, without changing HOME.
cat >"$test_dir/sitecustomize.py" <<'PY'
import os
import pwd
os.getlogin = lambda: pwd.getpwuid(os.getuid()).pw_name
PY
PYTHONPATH="$test_dir${PYTHONPATH:+:$PYTHONPATH}" \
XDG_CONFIG_HOME="$test_dir/config" \
    /usr/bin/python3 "$project_dir/tests/virtual-trackpad.py" \
    "${1:-$project_dir/artifacts/virtual-trackpad}"
