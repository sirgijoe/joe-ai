#!/usr/bin/env bash
# Copy Joe's own files (no Python) into DEST and write joeai/_install.json.
#   installer/gather.sh DEST KIND VERSION      KIND: mac-app | linux-appimage
# Old __pycache__ folders are removed here; build_dmg.sh / build_appimage.sh compile fresh
# .pyc files afterwards, because the installed copy is read-only (AppImage) or signed (Mac app).
set -euo pipefail
dest="$1"; kind="$2"; version="$3"
mkdir -p "$dest"
cp -R joeai docs Joe.pyw README.md LICENSE THIRD_PARTY.md "$dest"/
find "$dest/joeai" -name "__pycache__" -prune -exec rm -rf {} +
rm -f "$dest/joeai/_install.json"
printf '{"kind": "%s", "version": "%s"}\n' "$kind" "$version" > "$dest/joeai/_install.json"
