#!/usr/bin/env bash
# Build Joe-<version>-linux-<arch>.AppImage (run on Linux; pbs/python must exist).
#   installer/linux/build_appimage.sh VERSION ARCH       ARCH: x86_64 | aarch64
# Uses appimagetool's static runtime (no libfuse2 needed). Not signed.
set -euo pipefail
version="$1"; arch="$2"
appdir="build/linux/Joe.AppDir"
rm -rf build/linux && mkdir -p "$appdir"
installer/gather.sh "$appdir/app" linux-appimage "$version"
cp -R pbs/python "$appdir/python"
"$appdir/python/bin/python3" -m compileall -q --invalidation-mode unchecked-hash "$appdir/app/joeai"

cat > "$appdir/AppRun" <<'SH'
#!/bin/sh
# Joe's launcher inside the AppImage. -B: the AppImage is read-only, so Python writes no caches.
here="$(dirname "$(readlink -f "$0")")"
exec "$here/python/bin/python3" -B "$here/app/Joe.pyw" "$@"
SH
chmod +x "$appdir/AppRun"
cp installer/joe.png "$appdir/joe.png"
cp installer/joe.png "$appdir/.DirIcon"
cat > "$appdir/joe.desktop" <<'DT'
[Desktop Entry]
Type=Application
Name=Joe
Comment=Your local AI helper
Exec=AppRun
Icon=joe
Categories=Utility;
Terminal=false
DT

tool="build/appimagetool"
if [ ! -x "$tool" ]; then
  gh release download continuous --repo AppImage/appimagetool -p "appimagetool-${arch}.AppImage" -O "$tool"
  chmod +x "$tool"
fi
mkdir -p dist
out="dist/Joe-${version}-linux-${arch}.AppImage"
ARCH="$arch" APPIMAGE_EXTRACT_AND_RUN=1 "$tool" --no-appstream "$appdir" "$out"
chmod +x "$out"
echo "Built $out"
