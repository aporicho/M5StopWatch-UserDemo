#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
DESKTOP_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
BLE_STT_ROOT="$(CDPATH= cd -- "$DESKTOP_ROOT/.." && pwd)"
APP_NAME="M5StopWatch.app"
APP_BUNDLE_ID="com.aporicho.m5stopwatch-ble-stt"
HELPER_ID="com.aporicho.m5stopwatch-ble-stt-helper"
OLD_CONTROL_APP="/Applications/M5StopWatch Control.app"
USER_APP_DIR="$HOME/Applications"
USER_APP_TARGET="$USER_APP_DIR/$APP_NAME"
SYSTEM_APP_TARGET="/Applications/$APP_NAME"
USER_OLD_CONTROL_APP="$USER_APP_DIR/M5StopWatch Control.app"
APP_SOURCE="$DESKTOP_ROOT/src-tauri/target/release/bundle/macos/$APP_NAME"
OLD_APP_SOURCE="$DESKTOP_ROOT/src-tauri/target/release/bundle/macos/M5StopWatch Control.app"
APP_TARGET="$USER_APP_TARGET"
HELPER_SOURCE_APP="$BLE_STT_ROOT/dist-macos/M5StopWatch.app"
HELPER_APP="$APP_TARGET/Contents/Resources/resources/ble-stt-helper/M5StopWatch.app"
HELPER="$HELPER_APP/Contents/MacOS/M5StopWatch"

clear_bundle_metadata() {
  local path="$1"

  /usr/bin/xattr -cr "$path" || true
  while IFS= read -r item; do
    /usr/bin/xattr -c -s "$item" 2>/dev/null || true
  done < <(/usr/bin/find "$path" \( -type l -o -type f -o -type d \))
}

sign_app_bundle() {
  local app="$1"
  local bundle_id="$2"
  local deep="${3:-}"
  local signing_identity="${CODESIGN_IDENTITY:--}"

  if [ "$signing_identity" = "-" ]; then
    if [ "$deep" = "--deep" ]; then
      /usr/bin/codesign \
        --force \
        --deep \
        --timestamp=none \
        --sign - \
        "$app"
    fi
    /usr/bin/codesign \
      --force \
      --timestamp=none \
      --sign - \
      --identifier "$bundle_id" \
      --requirements "=designated => identifier \"$bundle_id\"" \
      "$app"
  else
    if [ "$deep" = "--deep" ]; then
      /usr/bin/codesign \
        --force \
        --deep \
        --timestamp=none \
        --sign "$signing_identity" \
        "$app"
    else
      /usr/bin/codesign \
        --force \
        --timestamp=none \
        --sign "$signing_identity" \
        "$app"
    fi
  fi
  /usr/bin/codesign --verify --strict --verbose=2 "$app"
}

verify_app_bundle_identity() {
  local app="$1"
  local bundle_id="$2"
  local requirements

  /usr/bin/codesign --verify --deep --strict --verbose=2 "$app"
  requirements="$(/usr/bin/codesign --display --requirements - "$app" 2>&1)"
  case "$requirements" in
    *"identifier \"$bundle_id\""*) ;;
    *)
      printf 'Unexpected signing requirement for %s:\n%s\n' "$app" "$requirements" >&2
      exit 1
      ;;
  esac
}

move_existing_app() {
  local source="$1"
  local backup_name="$2"

  if [ -e "$source" ]; then
    /bin/mkdir -p "$BACKUP_ROOT"
    /bin/mv "$source" "$BACKUP_ROOT/$backup_name"
  fi
}

move_matching_apps() {
  local root="$1"
  local pattern="$2"

  [ -d "$root" ] || return 0
  while IFS= read -r app; do
    /bin/mkdir -p "$BACKUP_ROOT"
    /bin/mv "$app" "$BACKUP_ROOT/$(basename "$app")"
  done < <(/usr/bin/find "$root" -maxdepth 1 -name "$pattern" -print)
}

if [ -z "${CODESIGN_IDENTITY:-}" ]; then
  printf 'No CODESIGN_IDENTITY set; using stable ad-hoc development requirements.\n' >&2
fi

cd "$DESKTOP_ROOT"
if [ "${BLE_STT_SKIP_HELPER_BUILD:-0}" = "1" ]; then
  printf 'Skipping helper rebuild because BLE_STT_SKIP_HELPER_BUILD=1.\n' >&2
else
  "$BLE_STT_ROOT/macos/build-app.sh"
fi
BLE_STT_SKIP_LLAMA_RUNTIME=1 npm run build:mac:app

[ -d "$APP_SOURCE" ] || { printf 'Missing built app: %s\n' "$APP_SOURCE" >&2; exit 1; }
[ -x "$HELPER_SOURCE_APP/Contents/MacOS/M5StopWatch" ] || { printf 'Missing helper source app: %s\n' "$HELPER_SOURCE_APP" >&2; exit 1; }

/usr/bin/osascript -e 'tell application "M5StopWatch" to quit' >/dev/null 2>&1 || true
/usr/bin/osascript -e 'tell application "M5StopWatch Control" to quit' >/dev/null 2>&1 || true
/usr/bin/pkill -x m5stopwatch >/dev/null 2>&1 || true
/usr/bin/pkill -x m5stopwatch-control >/dev/null 2>&1 || true
/usr/bin/pkill -x M5StopWatch >/dev/null 2>&1 || true

BACKUP_ROOT="$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/m5stopwatch-install.XXXXXX")"
INSTALL_SUCCEEDED=0
cleanup_install_backup() {
  local status=$?
  if [ "$INSTALL_SUCCEEDED" = "1" ]; then
    /bin/rm -rf "$BACKUP_ROOT"
  else
    printf 'Installation stopped; previous app backup kept at %s\n' "$BACKUP_ROOT" >&2
  fi
  return "$status"
}
trap cleanup_install_backup EXIT
move_existing_app "$APP_TARGET" "$APP_NAME"
move_existing_app "$SYSTEM_APP_TARGET" "System $APP_NAME"
move_existing_app "$OLD_CONTROL_APP" "M5StopWatch Control.app"
move_existing_app "$USER_OLD_CONTROL_APP" "User M5StopWatch Control.app"
move_existing_app "$OLD_APP_SOURCE" "Built M5StopWatch Control.app"
move_matching_apps "$USER_APP_DIR" "M5StopWatch.app.before-*"
move_matching_apps "$USER_APP_DIR" "M5StopWatch.app.rollback-*"

/usr/bin/ditto "$APP_SOURCE" "$APP_TARGET"
clear_bundle_metadata "$APP_TARGET"

# Tauri's resource copier does not preserve PyInstaller's framework symlinks
# reliably. Replace the bundled helper app with a clean ditto copy before
# signing the outer control app.
/bin/rm -rf "$HELPER_APP"
/bin/mkdir -p "$(dirname "$HELPER_APP")"
/usr/bin/ditto --noextattr --noqtn "$HELPER_SOURCE_APP" "$HELPER_APP"
clear_bundle_metadata "$HELPER_APP"

[ -x "$HELPER" ] || { printf 'Missing helper: %s\n' "$HELPER" >&2; exit 1; }
[ -L "$HELPER_APP/Contents/Frameworks/Python.framework/Python" ] || { printf 'Helper Python.framework symlink was not preserved.\n' >&2; exit 1; }
[ -L "$HELPER_APP/Contents/Frameworks/Python.framework/Versions/Current" ] || { printf 'Helper Python.framework current-version symlink was not preserved.\n' >&2; exit 1; }
verify_app_bundle_identity "$HELPER_APP" "$HELPER_ID"
sign_app_bundle "$APP_TARGET" "$APP_BUNDLE_ID"
verify_app_bundle_identity "$APP_TARGET" "$APP_BUNDLE_ID"

APP_EXECUTABLE_NAME="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$APP_TARGET/Contents/Info.plist")"
APP_EXEC="$APP_TARGET/Contents/MacOS/$APP_EXECUTABLE_NAME"
[ -x "$APP_EXEC" ] || { printf 'Missing app executable: %s\n' "$APP_EXEC" >&2; exit 1; }

BIN_DIR="$HOME/.local/bin"
SHIM="$BIN_DIR/ble-stt"
if [ -e "$SHIM" ] && [ ! -L "$SHIM" ]; then
  printf '%s already exists and is not an M5StopWatch symlink. Move it aside and retry.\n' "$SHIM" >&2
  exit 1
fi
/bin/mkdir -p "$BIN_DIR"
/bin/ln -sfn "$APP_EXEC" "$SHIM"
[ -x "$SHIM" ] || { printf 'Command link is not executable: %s\n' "$SHIM" >&2; exit 1; }

"$APP_EXEC" status --json >/dev/null
"$APP_EXEC" service install --json
LAUNCH_AGENT="$HOME/Library/LaunchAgents/com.aporicho.m5stopwatch-ble-stt.plist"
if ! /usr/bin/grep -q "<string>$APP_EXEC</string>" "$LAUNCH_AGENT" || ! /usr/bin/grep -q "<string>service-run</string>" "$LAUNCH_AGENT"; then
  printf 'LaunchAgent was not installed through the main app service runner.\n' >&2
  exit 1
fi
/bin/sleep 1
"$APP_EXEC" service status --json

/usr/bin/open "$APP_TARGET"
INSTALL_SUCCEEDED=1
printf 'Installed %s\n' "$APP_TARGET"
