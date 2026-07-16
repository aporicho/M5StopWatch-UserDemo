#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SOURCE_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
PYTHON="${PYTHON:-python3.12}"
BUILD_ROOT="${BLE_STT_BUILD_ROOT:-$SOURCE_ROOT/.macos-build}"
DIST_ROOT="${BLE_STT_DIST_ROOT:-$SOURCE_ROOT/dist-macos}"
VERSION="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$SOURCE_ROOT/pyproject.toml" | head -n 1)"

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
# the program and makes codesign reject an otherwise valid bundle. PyInstaller
# signs first, but clearing metadata and signing once more makes the final
# artifact deterministic on both developer Macs and hosted runners.
/usr/bin/xattr -crs "$APP" || true
FINAL_SIGNING_IDENTITY="${CODESIGN_IDENTITY:--}"
/usr/bin/codesign \
    --force \
    --deep \
    --timestamp=none \
    --sign "$FINAL_SIGNING_IDENTITY" \
    "$APP"
/usr/bin/codesign --verify --deep --strict --verbose=2 "$APP"
"$APP/Contents/MacOS/M5StopWatch" --version
printf 'Built %s\n' "$APP"
