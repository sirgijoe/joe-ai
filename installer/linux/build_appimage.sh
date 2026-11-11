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

# appimagetool is pinned to one release and checked against its SHA-256 before it runs, so a
# changed download can't end up inside Joe's AppImage. To move to a newer appimagetool, change
# the tag and both sums together (compare with the digests on its GitHub release page).
AIT_TAG="1.9.0"
case "$arch" in
  x86_64)  ait_sha="46fdd785094c7f6e545b61afcfb0f3d98d8eab243f644b4b17698c01d06083d1" ;;
  aarch64) ait_sha="04f45ea45b5aa07bb2b071aed9dbf7a5185d3953b11b47358c1311f11ea94a96" ;;
  *) echo "unknown arch $arch" >&2; exit 1 ;;
esac
tool="build/appimagetool"
gh release download "$AIT_TAG" --repo AppImage/appimagetool -p "appimagetool-${arch}.AppImage" -O "$tool" --clobber
got=$(sha256sum "$tool" | cut -d' ' -f1)
if [ "$got" != "$ait_sha" ]; then
  echo "::error::appimagetool $AIT_TAG ($arch) doesn't match its pinned SHA-256 (got $got)" >&2
  rm -f "$tool"; exit 1
fi
chmod +x "$tool"
# appimagetool 1.9.0 stops without desktop-file-validate (it checks joe.desktop), and GitHub's
# Ubuntu runners don't come with it: both Linux builds of v2.1.5 failed here.
if ! command -v desktop-file-validate >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    sudo=$(command -v sudo || true)
    $sudo apt-get update -qq && $sudo apt-get install -y -qq desktop-file-utils
  else
    echo "::error::desktop-file-validate is missing: install the desktop-file-utils package first" >&2
    exit 1
  fi
fi
mkdir -p dist
out="dist/Joe-${version}-linux-${arch}.AppImage"
ARCH="$arch" APPIMAGE_EXTRACT_AND_RUN=1 "$tool" --no-appstream "$appdir" "$out"
chmod +x "$out"
echo "Built $out"
