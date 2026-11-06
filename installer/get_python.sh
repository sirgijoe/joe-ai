#!/usr/bin/env bash
# Download the private Python 3.12 for one platform from python-build-standalone, check it
# against that release's SHA256SUMS, and unpack it to ./pbs/python.
#   installer/get_python.sh aarch64-apple-darwin | x86_64-apple-darwin |
#                           x86_64-unknown-linux-gnu | aarch64-unknown-linux-gnu
# Needs gh (GH_TOKEN set) and jq. Used by .github/workflows/release.yml.
set -euo pipefail
triple="$1"
rel=$(gh release view --repo astral-sh/python-build-standalone --json tagName,assets)
name=$(echo "$rel" | jq -r '.assets[].name' \
  | grep -E "^cpython-3\.12\.[0-9]+\+[0-9]+-${triple}-install_only\.tar\.gz\$" | head -1)
[ -n "$name" ] || { echo "::error::no Python build found for $triple"; exit 1; }
tag=$(echo "$rel" | jq -r .tagName)
rm -rf pbs && mkdir -p pbs && cd pbs
gh release download "$tag" --repo astral-sh/python-build-standalone -p "$name" -p SHA256SUMS
want=$(grep " $name\$" SHA256SUMS | cut -d' ' -f1)
if command -v sha256sum >/dev/null; then got=$(sha256sum "$name" | cut -d' ' -f1)
else got=$(shasum -a 256 "$name" | cut -d' ' -f1); fi
[ -n "$want" ] && [ "$want" = "$got" ] || { echo "::error::checksum mismatch for $name"; exit 1; }
tar -xzf "$name"
rm -f "$name" SHA256SUMS
echo "Using $name"
