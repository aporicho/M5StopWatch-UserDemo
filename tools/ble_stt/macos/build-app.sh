#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SOURCE_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
PYTHON="${PYTHON:-python3.12}"
BUILD_ROOT="${BLE_STT_BUILD_ROOT:-$SOURCE_ROOT/.macos-build}"
DIST_ROOT="${BLE_STT_DIST_ROOT:-$SOURCE_ROOT/dist-macos}"
VERSION="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$SOURCE_ROOT/pyproject.toml" | head -n 1)"
HELPER_BUNDLE_ID="com.aporicho.m5stopwatch-ble-stt-helper"

[ -n "$VERSION" ] || { printf 'Could not determine package version.\n' >&2; exit 1; }
"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' \
    || { printf 'Python 3.12 is required to build the macOS app.\n' >&2; exit 1; }

rm -rf "$BUILD_ROOT" "$DIST_ROOT"
mkdir -p "$BUILD_ROOT" "$DIST_ROOT"
"$PYTHON" -m venv "$BUILD_ROOT/venv"
VENV_PYTHON="$BUILD_ROOT/venv/bin/python"

"$VENV_PYTHON" -m pip install \
    'pip==26.1.2' \
    'setuptools==83.0.0' \
    'wheel==0.47.0'
"$VENV_PYTHON" -m pip install -r "$SCRIPT_DIR/requirements-build.txt"
"$VENV_PYTHON" -m pip install --no-deps 'mlx-whisper==0.4.3'
"$VENV_PYTHON" -m pip install --no-deps "$SOURCE_ROOT"

export BLE_STT_APP_VERSION="$VERSION"
export BLE_STT_HELPER_BUNDLE_ID="$HELPER_BUNDLE_ID"
# PyInstaller applies hardened-runtime signing with a trusted timestamp while
# assembling the intermediate executable. A private self-signed identity has
# no public timestamp chain, so intermediate files stay ad-hoc signed and the
# completed bundle receives the persistent identity once, below.
unset BLE_STT_CODESIGN_IDENTITY

"$BUILD_ROOT/venv/bin/pyinstaller" \
    --noconfirm \
    --clean \
    --distpath "$DIST_ROOT" \
    --workpath "$BUILD_ROOT/work" \
    "$SCRIPT_DIR/M5StopWatch.spec"

APP="$DIST_ROOT/M5StopWatch.app"
[ -x "$APP/Contents/MacOS/M5StopWatch" ] || { printf 'App build failed.\n' >&2; exit 1; }
# Finder/FileProvider metadata inherited from a build directory is not part of
# the program and makes codesign reject an otherwise valid bundle. Sign and
# verify a clean temporary copy; this also works when the repository itself is
# stored on Desktop/iCloud and FileProvider immediately restores its metadata.
SIGNING_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/m5stopwatch-codesign.XXXXXX")"
cleanup_signing_root() {
    rm -rf "$SIGNING_ROOT"
}
trap cleanup_signing_root EXIT HUP INT TERM
SIGNING_APP="$SIGNING_ROOT/M5StopWatch.app"
/usr/bin/ditto "$APP" "$SIGNING_APP"
/usr/bin/xattr -cr "$SIGNING_APP" || true
while IFS= read -r link; do
    /usr/bin/xattr -c -s "$link" 2>/dev/null || true
done < <(find "$SIGNING_APP" -type l)
FINAL_SIGNING_IDENTITY="${CODESIGN_IDENTITY:--}"
if [ "$FINAL_SIGNING_IDENTITY" = "-" ]; then
    /usr/bin/codesign \
        --force \
        --deep \
        --timestamp=none \
        --sign - \
        "$SIGNING_APP"
    /usr/bin/codesign \
        --force \
        --timestamp=none \
        --sign - \
        --identifier "$HELPER_BUNDLE_ID" \
        --requirements "=designated => identifier \"$HELPER_BUNDLE_ID\"" \
        "$SIGNING_APP"
else
    /usr/bin/codesign \
        --force \
        --deep \
        --timestamp=none \
        --sign "$FINAL_SIGNING_IDENTITY" \
        "$SIGNING_APP"
fi
/usr/bin/codesign --verify --deep --strict --verbose=2 "$SIGNING_APP"
rm -rf "$APP"
/usr/bin/ditto --noextattr --noqtn "$SIGNING_APP" "$APP"
#
# Desktop/iCloud-backed directories can immediately attach Finder/FileProvider
# metadata to the copied app. Verify an extattr-free copy of the delivered
# tree so the build check stays stable in those directories.
FINAL_VERIFY_APP="$SIGNING_ROOT/M5StopWatch.final-verify.app"
/usr/bin/ditto --noextattr --noqtn "$APP" "$FINAL_VERIFY_APP"
/usr/bin/xattr -cr "$FINAL_VERIFY_APP" || true
while IFS= read -r link; do
    /usr/bin/xattr -c -s "$link" 2>/dev/null || true
done < <(find "$FINAL_VERIFY_APP" -type l)
/usr/bin/codesign --verify --deep --strict --verbose=2 "$FINAL_VERIFY_APP"
"$SIGNING_APP/Contents/MacOS/M5StopWatch" --version
printf 'Built %s\n' "$APP"
