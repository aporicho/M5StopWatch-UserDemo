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
USER_OLD_CONTROL_APP="$USER_APP_DIR/M5StopWatch Control.app"
APP_SOURCE="$DESKTOP_ROOT/src-tauri/target/release/bundle/macos/$APP_NAME"
OLD_APP_SOURCE="$DESKTOP_ROOT/src-tauri/target/release/bundle/macos/M5StopWatch Control.app"
APP_TARGET="/Applications/$APP_NAME"
HELPER_SOURCE_APP="$BLE_STT_ROOT/dist-macos/M5StopWatch.app"
HELPER_APP="$APP_TARGET/Contents/Resources/resources/ble-stt-helper/M5StopWatch.app"
HELPER="$HELPER_APP/Contents/MacOS/M5StopWatch"
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"

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

clean_launchpad_cache() {
  local launchpad_db
  local first_page_id
  local user_dir

  "$LSREGISTER" -u "$OLD_CONTROL_APP" >/dev/null 2>&1 || true
  "$LSREGISTER" -u "$USER_OLD_CONTROL_APP" >/dev/null 2>&1 || true
  "$LSREGISTER" -u "$OLD_APP_SOURCE" >/dev/null 2>&1 || true
  "$LSREGISTER" -kill -r -domain local -domain system -domain user >/dev/null 2>&1 || true
  "$LSREGISTER" -f -R -trusted "$APP_TARGET" >/dev/null 2>&1 || true

  user_dir="$(/usr/bin/getconf DARWIN_USER_DIR 2>/dev/null || true)"
  launchpad_db="${user_dir%/}/com.apple.dock.launchpad/db/db"
  if [ -f "$launchpad_db" ] && command -v sqlite3 >/dev/null 2>&1; then
    /bin/cp "$launchpad_db" "$launchpad_db.before-m5stopwatch-clean" >/dev/null 2>&1 || true
    /usr/bin/sqlite3 "$launchpad_db" "delete from items where rowid in (select item_id from apps where title = 'M5StopWatch Control' and bundleid = '$APP_BUNDLE_ID');" >/dev/null 2>&1 || true
    first_page_id="$(/usr/bin/sqlite3 "$launchpad_db" "select rowid from items where parent_id = (select value from dbinfo where key = 'launchpad_root') and type = 3 and uuid not like 'HOLDINGPAGE%' order by ordering limit 1;" 2>/dev/null || true)"
    if [ -n "$first_page_id" ]; then
      /usr/bin/sqlite3 "$launchpad_db" "
        begin;
        update dbinfo set value = 1 where key = 'ignore_items_update_triggers';
        update items
          set ordering = ordering + 1
          where parent_id = $first_page_id
            and rowid not in (select item_id from apps where title = 'M5StopWatch' and bundleid = '$APP_BUNDLE_ID');
        update items
          set parent_id = $first_page_id,
              ordering = 0
          where rowid in (select item_id from apps where title = 'M5StopWatch' and bundleid = '$APP_BUNDLE_ID');
        update dbinfo set value = 0 where key = 'ignore_items_update_triggers';
        commit;
      " >/dev/null 2>&1 || true
    fi
  fi

  /usr/bin/defaults write com.apple.dock ResetLaunchPad -bool true >/dev/null 2>&1 || true
  /usr/bin/killall Dock >/dev/null 2>&1 || true
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
npm run build:mac:app

[ -d "$APP_SOURCE" ] || { printf 'Missing built app: %s\n' "$APP_SOURCE" >&2; exit 1; }
[ -x "$HELPER_SOURCE_APP/Contents/MacOS/M5StopWatch" ] || { printf 'Missing helper source app: %s\n' "$HELPER_SOURCE_APP" >&2; exit 1; }

/usr/bin/osascript -e 'tell application "M5StopWatch" to quit' >/dev/null 2>&1 || true
/usr/bin/osascript -e 'tell application "M5StopWatch Control" to quit' >/dev/null 2>&1 || true
/usr/bin/pkill -x m5stopwatch >/dev/null 2>&1 || true
/usr/bin/pkill -x m5stopwatch-control >/dev/null 2>&1 || true
/usr/bin/pkill -x M5StopWatch >/dev/null 2>&1 || true

BACKUP_ROOT="$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/m5stopwatch-install.XXXXXX")"
move_existing_app "$APP_TARGET" "$APP_NAME"
move_existing_app "$OLD_CONTROL_APP" "M5StopWatch Control.app"
move_existing_app "$USER_APP_TARGET" "User M5StopWatch.app"
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

/usr/bin/tccutil reset Bluetooth com.aporicho.m5stopwatch-control >/dev/null 2>&1 || true
/usr/bin/tccutil reset Accessibility com.aporicho.m5stopwatch-control >/dev/null 2>&1 || true
/usr/bin/tccutil reset Bluetooth "$HELPER_ID" >/dev/null 2>&1 || true
"$APP_EXEC" status --json >/dev/null
"$APP_EXEC" service install --json
LAUNCH_AGENT="$HOME/Library/LaunchAgents/com.aporicho.m5stopwatch-ble-stt.plist"
if ! /usr/bin/grep -q "<string>$APP_EXEC</string>" "$LAUNCH_AGENT" || ! /usr/bin/grep -q "<string>service-run</string>" "$LAUNCH_AGENT"; then
  printf 'LaunchAgent was not installed through the main app service runner.\n' >&2
  exit 1
fi
/bin/sleep 1
"$APP_EXEC" service status --json

clean_launchpad_cache
/usr/bin/open "$APP_TARGET"
printf 'Installed %s\n' "$APP_TARGET"
