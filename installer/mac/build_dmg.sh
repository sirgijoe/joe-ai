#!/usr/bin/env bash
# Build Joe.app and Joe-<version>-macos-<arch>.dmg (run on a Mac; pbs/python must exist).
#   installer/mac/build_dmg.sh VERSION ARCH        ARCH: arm64 | x64
# Joe.app/Contents/MacOS/Joe is a small launcher script; the private Python and Joe's files
# live in Contents/Resources. Not notarized (that needs a paid Apple account): the whole app
# is ad-hoc signed so Apple Silicon will run it, and the first open goes through
# System Settings > Privacy & Security > Open Anyway (explained in "Read me first.txt").
set -euo pipefail
version="$1"; arch="$2"
app="build/mac/Joe.app"
rm -rf build/mac && mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
installer/gather.sh "$app/Contents/Resources/app" mac-app "$version"
cp -R pbs/python "$app/Contents/Resources/python"
py="$app/Contents/Resources/python/bin/python3"
"$py" -m compileall -q --invalidation-mode unchecked-hash "$app/Contents/Resources/app/joeai"

cat > "$app/Contents/MacOS/Joe" <<'SH'
#!/bin/bash
# Joe's launcher. Finder starts apps with a bare PATH; add the usual Homebrew / Ollama spots.
here="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
exec "$here/Resources/python/bin/python3" -B "$here/Resources/app/Joe.pyw" "$@"
SH
chmod +x "$app/Contents/MacOS/Joe"

# icon: 512 px PNG -> .icns
iconset="build/mac/joe.iconset"; mkdir -p "$iconset"
for s in 16 32 128 256 512; do
  sips -z $s $s installer/joe.png --out "$iconset/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2)); [ $d -le 512 ] && sips -z $d $d installer/joe.png --out "$iconset/icon_${s}x${s}@2x.png" >/dev/null
done
cp installer/joe.png "$iconset/icon_512x512@2x.png"
iconutil -c icns "$iconset" -o "$app/Contents/Resources/joe.icns"

min="11.0"
cat > "$app/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Joe</string>
  <key>CFBundleDisplayName</key><string>Joe</string>
  <key>CFBundleIdentifier</key><string>io.github.sirgijoe.joe-ai</string>
  <key>CFBundleVersion</key><string>${version}</string>
  <key>CFBundleShortVersionString</key><string>${version}</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>Joe</string>
  <key>CFBundleIconFile</key><string>joe.icns</string>
  <key>LSMinimumSystemVersion</key><string>${min}</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>Joe uses the microphone only when you talk to him (push to talk).</string>
  <key>NSHumanReadableCopyright</key><string>GPL-3.0-or-later. Joe contributors.</string>
</dict></plist>
PL

codesign --force --deep --sign - "$app"
codesign --verify --deep --strict "$app"

stage="build/mac/dmg"; mkdir -p "$stage"
cp -R "$app" "$stage/"
ln -s /Applications "$stage/Applications"
cat > "$stage/Read me first.txt" <<'TXT'
Installing Joe on a Mac

1. Drag Joe onto the Applications folder.
2. Open Joe from Applications.
3. The first time, macOS says Joe can't be checked for malicious software, because Joe isn't
   registered with Apple (that costs money every year, and Joe is free).
   Click Done (or OK), then open System Settings > Privacy & Security, scroll down and click
   "Open Anyway" next to Joe, then Open. You only do this once.

Joe is free and open source (GPL-3.0): https://github.com/sirgijoe/joe-ai
TXT
mkdir -p dist
out="dist/Joe-${version}-macos-${arch}.dmg"
rm -f "$out"
hdiutil create -volname "Joe ${version}" -srcfolder "$stage" -fs HFS+ -format UDZO -ov "$out"
echo "Built $out"
