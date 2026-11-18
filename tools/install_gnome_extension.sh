#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
extension_dir=${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions/click-toggle-indicator@personal-utilities

mkdir -p -- "$extension_dir"
install -m 644 "$project_dir/gnome-extension/metadata.json" "$extension_dir/metadata.json"
install -m 644 "$project_dir/gnome-extension/extension.js" "$extension_dir/extension.js"
echo "Installed extension in $extension_dir"
echo "Log out and back in to discover/reload it, then run:"
echo "gnome-extensions enable click-toggle-indicator@personal-utilities"
