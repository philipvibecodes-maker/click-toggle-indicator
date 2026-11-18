#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

if ! command -v input-remapper-control >/dev/null 2>&1; then
    echo "Input Remapper is not installed." >&2
    echo "Install it with: sudo apt install input-remapper" >&2
    exit 1
fi

python3 "$project_dir/tools/configure_input_remapper.py" --install "$@"

echo
echo "Preset installed. Build and run with:"
echo "  make"
echo "  ./run.sh"
