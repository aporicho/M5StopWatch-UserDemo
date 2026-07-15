from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def config_dir(platform_name: str | None = None) -> Path:
    platform_name = platform_name or sys.platform
    if platform_name == "darwin":
        return Path.home() / "Library" / "Application Support" / "M5StopWatch"
    if platform_name == "win32":
        root = os.environ.get("LOCALAPPDATA")
        return Path(root) / "M5StopWatch" if root else Path.home() / "AppData" / "Local" / "M5StopWatch"
    root = os.environ.get("XDG_CONFIG_HOME")
    return Path(root) / "m5stopwatch" if root else Path.home() / ".config" / "m5stopwatch"


def log_dir(platform_name: str | None = None) -> Path:
    platform_name = platform_name or sys.platform
    if platform_name == "darwin":
        return Path.home() / "Library" / "Logs" / "M5StopWatch"
    if platform_name == "win32":
        return config_dir(platform_name) / "Logs"
    root = os.environ.get("XDG_STATE_HOME")
    return Path(root) / "m5stopwatch" if root else Path.home() / ".local" / "state" / "m5stopwatch"


def install_dir(platform_name: str | None = None) -> Path:
    """Return the user-scoped root used by the one-line installer."""
    platform_name = platform_name or sys.platform
    if platform_name == "darwin":
        return Path.home() / "Library" / "Application Support" / "M5StopWatch" / "ble-stt"
    if platform_name == "win32":
        root = os.environ.get("LOCALAPPDATA")
        base = Path(root) if root else Path.home() / "AppData" / "Local"
        return base / "M5StopWatch" / "ble-stt"
    root = os.environ.get("XDG_DATA_HOME")
    base = Path(root) if root else Path.home() / ".local" / "share"
    return base / "m5stopwatch" / "ble-stt"


def model_cache_dir(platform_name: str | None = None) -> Path:
    platform_name = platform_name or sys.platform
    if platform_name == "darwin":
        return Path.home() / "Library" / "Caches" / "M5StopWatch" / "ble-stt"
    if platform_name == "win32":
        root = os.environ.get("LOCALAPPDATA")
        base = Path(root) if root else Path.home() / "AppData" / "Local"
        return base / "M5StopWatch" / "Cache" / "ble-stt"
    root = os.environ.get("XDG_CACHE_HOME")
    base = Path(root) if root else Path.home() / ".cache"
    return base / "m5stopwatch" / "ble-stt"


class UserConfig:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_dir() / "ble-stt.json"
        self._values: dict[str, Any] = {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                self._values = value
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._values[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)
