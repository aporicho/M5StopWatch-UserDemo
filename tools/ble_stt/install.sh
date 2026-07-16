#!/bin/sh
set -eu

REPOSITORY="aporicho/M5StopWatch-UserDemo"
MODEL="${BLE_STT_MODEL:-medium}"
ENGINE="${BLE_STT_ENGINE:-auto}"
MODE="install"
SKIP_TEST="${BLE_STT_SKIP_TEST:-0}"
PURGE_MODELS=0
WORK=""
TARGET=""
TARGET_READY=0
SERVICE_SWITCH_STARTED=0
OLD_SERVICE=""
LOCK_DIR=""
LOCK_ACQUIRED=0
MAC_APP="$HOME/Applications/M5StopWatch.app"
MAC_APP_STAGE=""
MAC_APP_BACKUP=""
MAC_PLIST="$HOME/Library/LaunchAgents/com.aporicho.m5stopwatch-ble-stt.plist"
MAC_PLIST_BACKUP=""
MAC_INSTALLER="$HOME/Library/Application Support/M5StopWatch/ble-stt/install.sh"
MAC_INSTALLER_BACKUP=""
MAC_INSTALLER_STAGE=""
MAC_PROFILE=""
MAC_PROFILE_BACKUP=""
MAC_HAD_APP=0
MAC_HAD_PLIST=0
MAC_HAD_INSTALLER=0
MAC_HAD_PROFILE=0
MAC_TRANSACTION_STARTED=0
MAC_OLD_APP_BACKED_UP=0
MAC_NEW_APP_ACTIVATED=0
MAC_INSTALLER_SWITCHED=0
MAC_SHIM_SWITCHED=0
MAC_PROFILE_UPDATED=0
MAC_OLD_SHIM_TARGET=""
MAC_SIGNING_CERTIFICATE_DER=""
MAC_SIGNING_PUBLIC_KEY=""
EXPECTED_MACOS_BUNDLE_ID="com.aporicho.m5stopwatch-ble-stt"
# The release workflow replaces this marker in the published installer with
# the SHA-256 fingerprint of the long-lived, public signing certificate.
EXPECTED_MACOS_SIGNING_CERT_SHA256="__MACOS_SIGNING_CERTIFICATE_SHA256__"

for option in "$@"; do
    case "$option" in
        --upgrade) MODE="upgrade" ;;
        --uninstall) MODE="uninstall" ;;
        --purge-models) PURGE_MODELS=1 ;;
        *) printf 'Unknown option: %s\n' "$option" >&2; exit 2 ;;
    esac
done
if [ "$PURGE_MODELS" = "1" ] && [ "$MODE" != "uninstall" ]; then
    printf '%s\n' '--purge-models can only be used with --uninstall' >&2
    exit 2
fi

say() {
    printf '\n==> %s\n' "$1"
}

fail() {
    printf '\nInstall failed: %s\n' "$1" >&2
    exit 1
}

download() {
    url="$1"
    destination="$2"
    if command -v curl >/dev/null 2>&1; then
        curl -fL --retry 3 --progress-bar "$url" -o "$destination"
    elif command -v wget >/dev/null 2>&1; then
        wget --tries=3 --show-progress -O "$destination" "$url"
    else
        fail "curl or wget is required"
    fi
}

verify_sha256() {
    archive="$1"
    checksum_file="$2"
    expected="$(awk 'NR == 1 {print $1}' "$checksum_file")"
    case "$expected" in
        *[!0-9A-Fa-f]*|'') fail "download checksum file is invalid" ;;
    esac
    [ "${#expected}" -eq 64 ] || fail "download checksum file is invalid"
    if command -v sha256sum >/dev/null 2>&1; then
        actual="$(sha256sum "$archive" | awk '{print $1}')"
    elif command -v shasum >/dev/null 2>&1; then
        actual="$(shasum -a 256 "$archive" | awk '{print $1}')"
    else
        fail "sha256sum or shasum is required"
    fi
    [ "$actual" = "$expected" ] || fail "download checksum does not match"
}

macos_stop_service() {
    domain="gui/$(id -u)"
    launchctl bootout "$domain" "$MAC_PLIST" >/dev/null 2>&1 || true
    launchctl bootout "$domain/com.aporicho.m5stopwatch-ble-stt" >/dev/null 2>&1 || true
}

macos_start_previous_service() {
    [ "$MAC_HAD_PLIST" = "1" ] || return 0
    launchctl bootstrap "gui/$(id -u)" "$MAC_PLIST" >/dev/null 2>&1 || true
}

macos_prepare_release_key() {
    certificate_pem="$1"
    MAC_SIGNING_CERTIFICATE_DER="$WORK/M5StopWatch-signing-certificate.der"
    MAC_SIGNING_PUBLIC_KEY="$WORK/M5StopWatch-signing-public-key.pem"

    /usr/bin/openssl x509 -in "$certificate_pem" -outform DER -out "$MAC_SIGNING_CERTIFICATE_DER" \
        || fail "the release signing certificate is invalid"
    certificate_fingerprint="$(/usr/bin/shasum -a 256 "$MAC_SIGNING_CERTIFICATE_DER" | awk '{print $1}' | tr '[:lower:]' '[:upper:]')"
    expected_fingerprint="$(printf '%s' "$EXPECTED_MACOS_SIGNING_CERT_SHA256" | tr '[:lower:]' '[:upper:]')"
    [ "$certificate_fingerprint" = "$expected_fingerprint" ] \
        || fail "the release signing certificate fingerprint does not match this installer"
    /usr/bin/openssl x509 -in "$certificate_pem" -pubkey -noout >"$MAC_SIGNING_PUBLIC_KEY" \
        || fail "could not extract the release signing public key"
    /usr/bin/openssl rsa -pubin -in "$MAC_SIGNING_PUBLIC_KEY" -noout >/dev/null 2>&1 \
        || fail "the release signing certificate does not contain the expected RSA public key"
}

macos_verify_detached_signature() {
    signed_file="$1"
    signature_file="$2"
    [ -s "$signature_file" ] || fail "release signature is missing or empty"
    [ -s "$MAC_SIGNING_PUBLIC_KEY" ] || fail "release signing public key is unavailable"
    /usr/bin/openssl dgst -sha256 -verify "$MAC_SIGNING_PUBLIC_KEY" -signature "$signature_file" "$signed_file" \
        >/dev/null 2>&1 || fail "release signature verification failed for $(basename "$signed_file")"
}

macos_validate_app() {
    app="$1"
    executable="$app/Contents/MacOS/M5StopWatch"
    info_plist="$app/Contents/Info.plist"
    cert_prefix="$WORK/signing-certificate-"

    [ -d "$app" ] || fail "macOS archive does not contain M5StopWatch.app"
    [ -f "$info_plist" ] || fail "M5StopWatch.app has no Info.plist"
    [ -x "$executable" ] || fail "M5StopWatch.app has no executable"

    bundle_id="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$info_plist" 2>/dev/null || true)"
    [ "$bundle_id" = "$EXPECTED_MACOS_BUNDLE_ID" ] || fail "unexpected macOS Bundle ID: $bundle_id"

    architectures="$(/usr/bin/lipo -archs "$executable" 2>/dev/null || true)"
    case " $architectures " in
        *" arm64 "*) ;;
        *) fail "M5StopWatch.app does not contain an arm64 executable" ;;
    esac

    rm -f "$cert_prefix"* 2>/dev/null || true
    /usr/bin/codesign --display --extract-certificates="$cert_prefix" "$app" >/dev/null 2>&1 \
        || fail "could not extract the M5StopWatch.app signing certificate"
    [ -f "${cert_prefix}0" ] || fail "M5StopWatch.app has no embedded signing certificate"
    actual_fingerprint="$(/usr/bin/shasum -a 256 "${cert_prefix}0" | awk '{print $1}' | tr '[:lower:]' '[:upper:]')"
    expected_fingerprint="$(printf '%s' "$EXPECTED_MACOS_SIGNING_CERT_SHA256" | tr '[:lower:]' '[:upper:]')"
    [ "$actual_fingerprint" = "$expected_fingerprint" ] \
        || fail "M5StopWatch.app was not signed by the expected release certificate"

}

prompt_retry() {
    message="$1"
    if [ ! -r /dev/tty ]; then
        fail "$message"
    fi
    printf '%s Press Enter to retry, or Ctrl-C to stop. ' "$message" >/dev/tty
    # The script itself may arrive on stdin through curl, so prompts must use
    # the controlling terminal explicitly.
    IFS= read -r answer </dev/tty || exit 1
}

platform="$(uname -s)"
case "$platform" in
    Darwin)
        [ "$(uname -m)" = "arm64" ] || fail "MLX Whisper requires an Apple Silicon Mac"
        ROOT="$HOME/Library/Application Support/M5StopWatch/ble-stt"
        CONFIG_ROOT="$HOME/Library/Application Support/M5StopWatch"
        MODEL_CACHE="$HOME/Library/Caches/M5StopWatch/ble-stt"
        ;;
    Linux)
        data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
        config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
        ROOT="$data_home/m5stopwatch/ble-stt"
        CONFIG_ROOT="$config_home/m5stopwatch"
        MODEL_CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/m5stopwatch/ble-stt"
        ;;
    *) fail "this installer supports macOS and Linux; use the PowerShell command on Windows" ;;
esac

BIN_DIR="$HOME/.local/bin"
SHIM="$BIN_DIR/ble-stt"

cleanup() {
    if [ "$MAC_TRANSACTION_STARTED" = "1" ] && [ "${INSTALL_COMPLETE:-0}" != "1" ]; then
        printf '\nRestoring the previous macOS installation...\n' >&2
        macos_stop_service
        if [ "$MAC_NEW_APP_ACTIVATED" = "1" ]; then
            rm -rf "$MAC_APP"
        fi
        if [ "$MAC_OLD_APP_BACKED_UP" = "1" ] && [ -d "$MAC_APP_BACKUP" ]; then
            mv "$MAC_APP_BACKUP" "$MAC_APP"
        fi
        rm -f "$MAC_PLIST"
        if [ "$MAC_HAD_PLIST" = "1" ] && [ -f "$MAC_PLIST_BACKUP" ]; then
            mkdir -p "$(dirname "$MAC_PLIST")"
            cp "$MAC_PLIST_BACKUP" "$MAC_PLIST"
        fi
        if [ "$MAC_INSTALLER_SWITCHED" = "1" ]; then
            rm -f "$MAC_INSTALLER"
            if [ "$MAC_HAD_INSTALLER" = "1" ] && [ -f "$MAC_INSTALLER_BACKUP" ]; then
                cp "$MAC_INSTALLER_BACKUP" "$MAC_INSTALLER"
                chmod +x "$MAC_INSTALLER"
            fi
        fi
        if [ "$MAC_SHIM_SWITCHED" = "1" ]; then
            rm -f "$SHIM"
            if [ -n "$MAC_OLD_SHIM_TARGET" ]; then
                ln -s "$MAC_OLD_SHIM_TARGET" "$SHIM"
            fi
        fi
        if [ "$MAC_PROFILE_UPDATED" = "1" ] && [ -n "$MAC_PROFILE" ]; then
            if [ "$MAC_HAD_PROFILE" = "1" ] && [ -f "$MAC_PROFILE_BACKUP" ]; then
                cp "$MAC_PROFILE_BACKUP" "$MAC_PROFILE"
            else
                rm -f "$MAC_PROFILE"
            fi
        fi
        macos_start_previous_service
    fi
    if [ "$platform" = "Darwin" ] && [ "${INSTALL_COMPLETE:-0}" = "1" ]; then
        if [ -n "$MAC_APP_BACKUP" ]; then
            rm -rf "$MAC_APP_BACKUP" 2>/dev/null || true
        fi
        rm -rf "$ROOT/versions" 2>/dev/null || true
        rm -f "$ROOT/current" 2>/dev/null || true
    fi
    if [ -n "$MAC_APP_STAGE" ] && [ -d "$MAC_APP_STAGE" ]; then
        rm -rf "$MAC_APP_STAGE"
    fi
    if [ -n "$MAC_INSTALLER_STAGE" ]; then
        rm -f "$MAC_INSTALLER_STAGE"
    fi
    if [ -n "$WORK" ] && [ -d "$WORK" ]; then
        rm -rf "$WORK"
    fi
    if [ -n "$TARGET" ] && [ "${INSTALL_COMPLETE:-0}" != "1" ] && [ -d "$TARGET" ]; then
        if [ "$SERVICE_SWITCH_STARTED" = "1" ]; then
            if [ -x "$OLD_SERVICE" ]; then
                printf '\nRestoring the previous login service...\n' >&2
                "$OLD_SERVICE" install -- --engine "$ENGINE" --model "$MODEL" || true
            elif [ -x "$TARGET/source/.venv/bin/ble-stt-service" ]; then
                printf '\nRemoving the incomplete login service...\n' >&2
                "$TARGET/source/.venv/bin/ble-stt-service" uninstall || true
            fi
        fi
        # Once the environment is complete, keep its exact Python path stable
        # across Ctrl-C and retries so a macOS Accessibility grant does not
        # point at an executable the installer has deleted.
        if [ "$TARGET_READY" != "1" ]; then
            rm -rf "$TARGET"
        fi
    fi
    if [ "$LOCK_ACQUIRED" = "1" ] && [ -n "$LOCK_DIR" ]; then
        rm -rf "$LOCK_DIR"
    fi
}

stop_install() {
    trap - EXIT HUP INT TERM
    cleanup
    exit 130
}

mkdir -p "$ROOT"
LOCK_DIR="$ROOT/.install.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    lock_pid="$(sed -n '1p' "$LOCK_DIR/pid" 2>/dev/null || true)"
    if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null; then
        fail "another M5StopWatch BLE STT install or upgrade is already running (PID $lock_pid); stop it before retrying"
    fi
    rm -rf "$LOCK_DIR"
    mkdir "$LOCK_DIR" 2>/dev/null || fail "could not recover the stale installer lock at $LOCK_DIR"
fi
LOCK_ACQUIRED=1
printf '%s\n' "$$" >"$LOCK_DIR/pid"
trap cleanup EXIT
trap stop_install HUP INT TERM

if [ "$MODE" = "uninstall" ]; then
    say "Removing M5StopWatch BLE STT"
    if [ "$platform" = "Darwin" ]; then
        macos_stop_service
        rm -f "$MAC_PLIST"
        rm -rf "$MAC_APP"
        if [ -L "$SHIM" ]; then
            link_target="$(readlink "$SHIM" 2>/dev/null || true)"
            case "$link_target" in
                "$HOME/Applications/M5StopWatch.app"/*|"$ROOT"/*) rm -f "$SHIM" ;;
            esac
        fi
        rm -rf "$ROOT"
        if [ "$PURGE_MODELS" = "1" ]; then
            rm -rf "$MODEL_CACHE"
            printf '[ok] App, login service, and downloaded speech models removed.\n'
        else
            printf '[ok] App and login service removed. Downloaded model caches and settings were preserved.\n'
        fi
        exit 0
    fi
    if [ -x "$ROOT/current/source/.venv/bin/ble-stt-service" ]; then
        "$ROOT/current/source/.venv/bin/ble-stt-service" uninstall || true
    fi
    if [ -L "$SHIM" ]; then
        link_target="$(readlink "$SHIM" 2>/dev/null || true)"
        case "$link_target" in "$ROOT"/*) rm -f "$SHIM" ;; esac
    fi
    rm -rf "$ROOT"
    if [ "$PURGE_MODELS" = "1" ]; then
        rm -rf "$MODEL_CACHE"
        printf '[ok] Program, login service, and downloaded speech models removed.\n'
    else
        printf '[ok] Program and login service removed. Downloaded model caches were preserved.\n'
    fi
    exit 0
fi

install_macos_app() {
    product_version="$(sw_vers -productVersion)"
    product_major="$(printf '%s' "$product_version" | awk -F. '{print $1}')"
    product_minor="$(printf '%s' "$product_version" | awk -F. '{print $2 + 0}')"
    case "$product_major" in *[!0-9]*|'') fail "could not determine the macOS version" ;; esac
    if [ "$product_major" -lt 14 ] || { [ "$product_major" -eq 14 ] && [ "$product_minor" -lt 4 ]; }; then
        fail "M5StopWatch requires macOS 14.4 or newer (this Mac is running $product_version)"
    fi

    case "$EXPECTED_MACOS_SIGNING_CERT_SHA256" in
        __*)
            fail "this source installer has no release signing fingerprint; use the documented Release one-line command"
            ;;
        *[!0-9A-Fa-f]*|'') fail "the release signing fingerprint is invalid" ;;
    esac
    [ "${#EXPECTED_MACOS_SIGNING_CERT_SHA256}" -eq 64 ] || fail "the release signing fingerprint is invalid"

    if [ -e "$SHIM" ] && [ ! -L "$SHIM" ]; then
        fail "$SHIM already exists and is not an M5StopWatch symlink; move it aside and retry"
    fi
    if [ -L "$MAC_APP" ]; then
        fail "$MAC_APP is a symlink; move it aside and retry"
    fi
    if [ -e "$MAC_APP" ] && [ ! -d "$MAC_APP" ]; then
        fail "$MAC_APP exists but is not an app directory; move it aside and retry"
    fi
    if [ -L "$SHIM" ]; then
        MAC_OLD_SHIM_TARGET="$(readlink "$SHIM" 2>/dev/null || true)"
        case "$MAC_OLD_SHIM_TARGET" in
            "$MAC_APP/Contents/MacOS/M5StopWatch"|\
            "$ROOT/current/source/.venv/bin/ble-stt"|\
            "$ROOT"/versions/*/source/.venv/bin/ble-stt) ;;
            *) fail "$SHIM does not point to an M5StopWatch installation; move it aside and retry" ;;
        esac
    fi

    WORK="$(mktemp -d "${TMPDIR:-/tmp}/ble-stt.XXXXXX")"
    release="${BLE_STT_VERSION:-latest}"
    if [ -n "${BLE_STT_ASSET_BASE:-}" ]; then
        ASSET_BASE="${BLE_STT_ASSET_BASE%/}"
    elif [ "$release" = "latest" ]; then
        ASSET_BASE="https://github.com/$REPOSITORY/releases/latest/download"
    else
        ASSET_BASE="https://github.com/$REPOSITORY/releases/download/$release"
    fi

    download "$ASSET_BASE/M5StopWatch-signing-certificate.pem" "$WORK/M5StopWatch-signing-certificate.pem"
    macos_prepare_release_key "$WORK/M5StopWatch-signing-certificate.pem"

    if [ -d "$MAC_APP" ]; then
        macos_validate_app "$MAC_APP"
        MAC_HAD_APP=1
    fi
    if [ -e "$MAC_INSTALLER" ]; then
        [ -f "$MAC_INSTALLER" ] && [ ! -L "$MAC_INSTALLER" ] \
            || fail "$MAC_INSTALLER exists but is not a regular product installer"
        MAC_HAD_INSTALLER=1
        MAC_INSTALLER_BACKUP="$WORK/previous-installer.sh"
        cp "$MAC_INSTALLER" "$MAC_INSTALLER_BACKUP"
    fi

    say "Downloading the signed M5StopWatch app"
    download "$ASSET_BASE/M5StopWatch-macos-arm64.zip" "$WORK/M5StopWatch-macos-arm64.zip"
    download "$ASSET_BASE/M5StopWatch-macos-arm64.zip.sha256" "$WORK/M5StopWatch-macos-arm64.zip.sha256"
    download "$ASSET_BASE/M5StopWatch-macos-arm64.zip.sig" "$WORK/M5StopWatch-macos-arm64.zip.sig"
    verify_sha256 "$WORK/M5StopWatch-macos-arm64.zip" "$WORK/M5StopWatch-macos-arm64.zip.sha256"
    macos_verify_detached_signature "$WORK/M5StopWatch-macos-arm64.zip" "$WORK/M5StopWatch-macos-arm64.zip.sig"
    mkdir -p "$WORK/unpacked"
    /usr/bin/ditto -x -k "$WORK/M5StopWatch-macos-arm64.zip" "$WORK/unpacked"
    macos_validate_app "$WORK/unpacked/M5StopWatch.app"

    download "$ASSET_BASE/ble-stt-install.sh" "$WORK/ble-stt-install.sh"
    download "$ASSET_BASE/ble-stt-install.sh.sha256" "$WORK/ble-stt-install.sh.sha256"
    download "$ASSET_BASE/ble-stt-install.sh.sig" "$WORK/ble-stt-install.sh.sig"
    verify_sha256 "$WORK/ble-stt-install.sh" "$WORK/ble-stt-install.sh.sha256"
    macos_verify_detached_signature "$WORK/ble-stt-install.sh" "$WORK/ble-stt-install.sh.sig"

    mkdir -p "$HOME/Applications"
    MAC_APP_STAGE="$HOME/Applications/.M5StopWatch.app.new.$$"
    MAC_APP_BACKUP="$HOME/Applications/.M5StopWatch.app.previous.$$"
    [ ! -e "$MAC_APP_STAGE" ] || fail "stale install staging path exists: $MAC_APP_STAGE"
    [ ! -e "$MAC_APP_BACKUP" ] || fail "stale install backup path exists: $MAC_APP_BACKUP"
    /usr/bin/ditto "$WORK/unpacked/M5StopWatch.app" "$MAC_APP_STAGE"
    macos_validate_app "$MAC_APP_STAGE"

    if [ -f "$MAC_PLIST" ]; then
        MAC_HAD_PLIST=1
        MAC_PLIST_BACKUP="$WORK/previous-launch-agent.plist"
        cp "$MAC_PLIST" "$MAC_PLIST_BACKUP"
    fi

    MAC_TRANSACTION_STARTED=1
    macos_stop_service
    if [ "$MAC_HAD_APP" = "1" ]; then
        MAC_OLD_APP_BACKED_UP=1
        mv "$MAC_APP" "$MAC_APP_BACKUP"
    fi
    MAC_NEW_APP_ACTIVATED=1
    mv "$MAC_APP_STAGE" "$MAC_APP"
    MAC_APP_STAGE=""
    app_executable="$MAC_APP/Contents/MacOS/M5StopWatch"

    say "Requesting macOS text input permission"
    "$app_executable" doctor --request-permissions --wait 120

    say "Downloading and verifying the $MODEL speech model"
    "$app_executable" prepare --engine "$ENGINE" --model "$MODEL"

    if [ "$SKIP_TEST" != "1" ]; then
        say "Connecting and testing the watch"
        "$app_executable" doctor --ble
        "$app_executable" test --engine "$ENGINE" --model "$MODEL"
    fi

    say "Registering the login service"
    "$app_executable" service install -- --engine "$ENGINE" --model "$MODEL"

    say "Waiting for the login service to become healthy"
    service_attempt=0
    service_consecutive_ok=0
    while [ "$service_attempt" -lt 30 ]; do
        if "$app_executable" service status >/dev/null 2>&1 \
            && launchctl print "gui/$(id -u)/com.aporicho.m5stopwatch-ble-stt" 2>/dev/null \
                | grep -F 'state = running' >/dev/null 2>&1; then
            service_consecutive_ok=$((service_consecutive_ok + 1))
            [ "$service_consecutive_ok" -ge 2 ] && break
        else
            service_consecutive_ok=0
        fi
        service_attempt=$((service_attempt + 1))
        sleep 1
    done
    [ "$service_consecutive_ok" -ge 2 ] || fail "the new login service did not stay healthy"

    mkdir -p "$BIN_DIR" "$CONFIG_ROOT"
    MAC_INSTALLER_STAGE="$ROOT/.install.sh.new.$$"
    cp "$WORK/ble-stt-install.sh" "$MAC_INSTALLER_STAGE"
    chmod +x "$MAC_INSTALLER_STAGE"
    MAC_INSTALLER_SWITCHED=1
    mv "$MAC_INSTALLER_STAGE" "$MAC_INSTALLER"
    MAC_INSTALLER_STAGE=""

    MAC_SHIM_SWITCHED=1
    ln -sfn "$app_executable" "$SHIM"

    shell_name="$(basename "${SHELL:-sh}")"
    case "$shell_name" in
        zsh) profile="$HOME/.zprofile" ;;
        *) profile="$HOME/.profile" ;;
    esac
    MAC_PROFILE="$profile"
    case ":${PATH:-}:" in
        *":$BIN_DIR:"*) ;;
        *)
            marker="# M5StopWatch BLE STT"
            if ! grep -F "$marker" "$profile" >/dev/null 2>&1; then
                if [ -f "$profile" ]; then
                    MAC_HAD_PROFILE=1
                    MAC_PROFILE_BACKUP="$WORK/previous-shell-profile"
                    cp "$profile" "$MAC_PROFILE_BACKUP"
                fi
                MAC_PROFILE_UPDATED=1
                {
                    printf '\n%s\n' "$marker"
                    printf 'export PATH="$HOME/.local/bin:$PATH"\n'
                } >>"$profile"
            fi
            ;;
    esac

    version="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$MAC_APP/Contents/Info.plist" 2>/dev/null || true)"
    [ -n "$version" ] || version="unknown"
    # All externally visible state is now committed. Ignore terminal signals
    # for the final few statements so success cannot be reported and then
    # rolled back by a signal between the message and the completion flag.
    trap '' HUP INT TERM
    INSTALL_COMPLETE=1
    printf '\n[ok] M5StopWatch BLE STT %s is installed and running.\n' "$version"
    printf '     Open a new terminal and run: ble-stt status\n'
}

if [ "$platform" = "Darwin" ]; then
    install_macos_app
    exit 0
fi

say "Checking this computer"
LINUX_MISSING=""
if [ "$platform" = "Linux" ]; then
    command -v hyprctl >/dev/null 2>&1 || fail "Linux text insertion currently requires a Hyprland session"
    for command_name in bluetoothctl wtype; do
        command -v "$command_name" >/dev/null 2>&1 || LINUX_MISSING="$LINUX_MISSING $command_name"
    done
fi

find_python() {
    for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c \
            'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

PYTHON="$(find_python || true)"
if [ "$platform" = "Linux" ] && { [ -z "$PYTHON" ] || [ -n "$LINUX_MISSING" ]; }; then
    say "Installing missing Linux system packages"
    if [ "$(id -u)" -eq 0 ]; then
        SUDO=""
    else
        command -v sudo >/dev/null 2>&1 || fail "sudo is required to install missing system packages"
        SUDO="sudo"
    fi
    if command -v apt-get >/dev/null 2>&1; then
        $SUDO apt-get update
        $SUDO apt-get install -y python3 python3-venv bluez wtype
    elif command -v dnf >/dev/null 2>&1; then
        $SUDO dnf install -y python3 bluez wtype
    elif command -v pacman >/dev/null 2>&1; then
        $SUDO pacman -S --needed --noconfirm python bluez wtype
    elif command -v zypper >/dev/null 2>&1; then
        $SUDO zypper --non-interactive install python3 bluez wtype
    else
        fail "install Python 3.10+, BlueZ, and wtype with this distribution's package manager"
    fi
    PYTHON="$(find_python || true)"
    LINUX_MISSING=""
    for command_name in bluetoothctl wtype; do
        command -v "$command_name" >/dev/null 2>&1 || LINUX_MISSING="$LINUX_MISSING $command_name"
    done
    [ -z "$LINUX_MISSING" ] || fail "system package installation did not provide:$LINUX_MISSING"
fi
if [ -z "$PYTHON" ] && [ "$platform" = "Darwin" ]; then
    command -v brew >/dev/null 2>&1 || fail "Python 3.10+ is missing. Install Homebrew, then rerun this command"
    say "Installing Python 3.12 with Homebrew"
    brew install python@3.12
    PYTHON="$(brew --prefix python@3.12)/bin/python3.12"
fi
[ -n "$PYTHON" ] || fail "Python 3.10 or newer is required"
printf '[ok] %s\n' "$($PYTHON --version 2>&1)"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/ble-stt.XXXXXX")"
SOURCE_DIR=""
SCRIPT_PATH="${0:-}"
case "$SCRIPT_PATH" in
    */*)
        candidate_dir="$(CDPATH= cd -- "$(dirname -- "$SCRIPT_PATH")" 2>/dev/null && pwd || true)"
        if [ -n "$candidate_dir" ] && [ -f "$candidate_dir/pyproject.toml" ]; then
            SOURCE_DIR="$candidate_dir"
        fi
        ;;
esac
if [ -n "${BLE_STT_SOURCE_DIR:-}" ]; then
    SOURCE_DIR="$BLE_STT_SOURCE_DIR"
fi

release="${BLE_STT_VERSION:-latest}"
if [ -z "$SOURCE_DIR" ]; then
    if [ -n "${BLE_STT_ASSET_BASE:-}" ]; then
        ASSET_BASE="${BLE_STT_ASSET_BASE%/}"
    elif [ "$release" = "latest" ]; then
        ASSET_BASE="https://github.com/$REPOSITORY/releases/latest/download"
    else
        ASSET_BASE="https://github.com/$REPOSITORY/releases/download/$release"
    fi
    say "Downloading the stable release"
    download "$ASSET_BASE/ble-stt-source.tar.gz" "$WORK/source.tar.gz"
    download "$ASSET_BASE/ble-stt-source.tar.gz.sha256" "$WORK/source.tar.gz.sha256"
    verify_sha256 "$WORK/source.tar.gz" "$WORK/source.tar.gz.sha256"
    mkdir -p "$WORK/unpacked"
    tar -xzf "$WORK/source.tar.gz" -C "$WORK/unpacked"
    SOURCE_DIR="$WORK/unpacked/ble_stt"
    [ -f "$SOURCE_DIR/pyproject.toml" ] || fail "release archive has an unexpected layout"
fi

VERSION="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$SOURCE_DIR/pyproject.toml" | head -n 1)"
[ -n "$VERSION" ] || fail "could not determine the package version"
mkdir -p "$ROOT/versions"
if [ -x "$ROOT/current/source/.venv/bin/ble-stt-service" ]; then
    OLD_SERVICE="$ROOT/current/source/.venv/bin/ble-stt-service"
fi
TARGET="$ROOT/versions/$VERSION"
REUSE_TARGET=0
if [ -f "$TARGET/.environment-ready" ] && [ -x "$TARGET/source/.venv/bin/ble-stt" ]; then
    REUSE_TARGET=1
    TARGET_READY=1
elif [ -e "$TARGET" ]; then
    TARGET="$ROOT/versions/$VERSION-$(date +%Y%m%d%H%M%S)"
fi
VENV="$TARGET/source/.venv"

if [ "$REUSE_TARGET" = "1" ]; then
    say "Reusing the prepared platform environment"
    printf '[ok] Stable permission executable: %s\n' "$VENV/bin/python"
else
    mkdir -p "$TARGET/source"
    source_copy="$WORK/source-copy.tar"
    (cd "$SOURCE_DIR" && tar --exclude='.venv' --exclude='__pycache__' -cf "$source_copy" .)
    tar -xf "$source_copy" -C "$TARGET/source"

    say "Installing platform components"
    "$PYTHON" -m venv "$VENV"
    "$VENV/bin/python" -m pip install --upgrade pip
    "$VENV/bin/python" -m pip install "$TARGET/source"
    if [ "$platform" = "Linux" ]; then
        cp "$TARGET/source/run-service.sh" "$VENV/bin/ble-stt-run-service"
        chmod +x "$VENV/bin/ble-stt-run-service"
    fi
    printf '%s\n' "$VERSION" >"$TARGET/.environment-ready"
    TARGET_READY=1
fi

say "Downloading and verifying the $MODEL speech model"
"$VENV/bin/ble-stt" prepare --engine "$ENGINE" --model "$MODEL"

say "Checking input permissions"
if [ "$platform" = "Darwin" ]; then
    while :; do
        [ -x "$VENV/bin/ble-stt" ] || fail "the prepared install environment disappeared; stop any other installer and rerun this command"
        "$VENV/bin/ble-stt" doctor --request-permissions && break
        printf '\nmacOS does not always create a Python row automatically. In Accessibility, click +,\n'
        printf 'press Shift-Command-G, paste this stable path, then add and enable it:\n  %s\n' "$VENV/bin/python"
        prompt_retry "After adding that Python executable under System Settings > Privacy & Security > Accessibility,"
    done
else
    "$VENV/bin/ble-stt" doctor
fi

if [ "$MODE" = "install" ] && [ "$SKIP_TEST" != "1" ]; then
    say "Connecting and testing the watch"
    while :; do
        [ -x "$VENV/bin/ble-stt-check" ] || fail "the prepared install environment disappeared; stop any other installer and rerun this command"
        "$VENV/bin/ble-stt-check" && break
        if [ "$platform" = "Darwin" ]; then
            prompt_retry "Keep BLE Remote open while this installer triggers automatic encrypted pairing. If another computer keeps reconnecting, triple-tap the watch screen and choose Pair new computer; to stop Linux reconnect notifications, forget M5StopWatch HID on that Linux computer."
        else
            prompt_retry "Open BLE Remote on the watch and complete the computer's Bluetooth pairing prompt."
        fi
    done
    "$VENV/bin/ble-stt" test --engine "$ENGINE" --model "$MODEL"
fi

mkdir -p "$BIN_DIR" "$CONFIG_ROOT"
if [ -n "$SOURCE_DIR" ] && [ -f "$SCRIPT_PATH" ] 2>/dev/null; then
    script_absolute="$(CDPATH= cd -- "$(dirname -- "$SCRIPT_PATH")" && pwd)/$(basename -- "$SCRIPT_PATH")"
    if [ "$script_absolute" != "$ROOT/install.sh" ]; then
        cp "$SCRIPT_PATH" "$ROOT/install.sh"
    fi
elif [ -n "${ASSET_BASE:-}" ]; then
    download "$ASSET_BASE/ble-stt-install.sh" "$ROOT/install.sh"
fi
chmod +x "$ROOT/install.sh"

shell_name="$(basename "${SHELL:-sh}")"
case "$shell_name" in
    zsh) profile="$HOME/.zprofile" ;;
    *) profile="$HOME/.profile" ;;
esac
case ":${PATH:-}:" in
    *":$BIN_DIR:"*) ;;
    *)
        marker="# M5StopWatch BLE STT"
        if ! grep -F "$marker" "$profile" >/dev/null 2>&1; then
            {
                printf '\n%s\n' "$marker"
                printf 'export PATH="$HOME/.local/bin:$PATH"\n'
            } >>"$profile"
        fi
        ;;
esac

say "Registering the login service"
SERVICE_SWITCH_STARTED=1
"$VENV/bin/ble-stt-service" install -- --engine "$ENGINE" --model "$MODEL"

# Switch the user-facing command only after every validation and service
# registration step has succeeded. The previous version remains untouched on
# any earlier failure.
ln -sfn "$TARGET" "$ROOT/current"
ln -sfn "$ROOT/current/source/.venv/bin/ble-stt" "$SHIM"

INSTALL_COMPLETE=1
printf '\n[ok] M5StopWatch BLE STT %s is installed and running.\n' "$VERSION"
printf '     Open a new terminal and run: ble-stt status\n'
