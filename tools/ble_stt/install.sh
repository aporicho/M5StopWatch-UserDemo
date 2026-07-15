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
SERVICE_SWITCH_STARTED=0
OLD_SERVICE=""

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
    expected="$(awk '{print $1}' "$checksum_file")"
    if command -v sha256sum >/dev/null 2>&1; then
        actual="$(sha256sum "$archive" | awk '{print $1}')"
    elif command -v shasum >/dev/null 2>&1; then
        actual="$(shasum -a 256 "$archive" | awk '{print $1}')"
    else
        fail "sha256sum or shasum is required"
    fi
    [ "$actual" = "$expected" ] || fail "download checksum does not match"
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

if [ "$MODE" = "uninstall" ]; then
    say "Removing M5StopWatch BLE STT"
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

cleanup() {
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
        rm -rf "$TARGET"
    fi
}
trap cleanup EXIT HUP INT TERM

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
if [ -e "$TARGET" ]; then
    TARGET="$ROOT/versions/$VERSION-$(date +%Y%m%d%H%M%S)"
fi
mkdir -p "$TARGET"
mkdir -p "$TARGET/source"
source_copy="$WORK/source-copy.tar"
(cd "$SOURCE_DIR" && tar --exclude='.venv' --exclude='__pycache__' -cf "$source_copy" .)
tar -xf "$source_copy" -C "$TARGET/source"

say "Installing platform components"
"$PYTHON" -m venv "$TARGET/source/.venv"
VENV="$TARGET/source/.venv"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install "$TARGET/source"
if [ "$platform" = "Linux" ]; then
    cp "$TARGET/source/run-service.sh" "$VENV/bin/ble-stt-run-service"
    chmod +x "$VENV/bin/ble-stt-run-service"
fi

say "Downloading and verifying the $MODEL speech model"
"$VENV/bin/ble-stt" prepare --engine "$ENGINE" --model "$MODEL"

say "Checking input permissions"
if [ "$platform" = "Darwin" ]; then
    while ! "$VENV/bin/ble-stt" doctor --request-permissions; do
        prompt_retry "Allow Python under System Settings > Privacy & Security > Accessibility."
    done
else
    "$VENV/bin/ble-stt" doctor
fi

if [ "$MODE" = "install" ] && [ "$SKIP_TEST" != "1" ]; then
    say "Connecting and testing the watch"
    while ! "$VENV/bin/ble-stt-check"; do
        prompt_retry "Open BLE Remote on the watch and complete the computer's Bluetooth pairing prompt."
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
