from __future__ import annotations

import argparse
import asyncio
import importlib.util
import platform
import sys
from typing import Sequence

from .check import check
from .config import UserConfig
from .platforms import create_platform
from .recognizers import resolve_engine


def _module_check(name: str, label: str) -> tuple[bool, str]:
    if importlib.util.find_spec(name) is None:
        return False, f"{label} is not installed"
    return True, f"{label} is installed"


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Check M5StopWatch STT platform requirements")
    parser.add_argument("--request-permissions", action="store_true", help="show the macOS Accessibility prompt")
    parser.add_argument("--ble", action="store_true", help="also connect to and validate the watch")
    parser.add_argument("--device-id", "--address", dest="device_id")
    args = parser.parse_args(argv)

    checks: list[tuple[bool, str]] = []
    checks.append((sys.version_info >= (3, 10), f"Python {platform.python_version()} (need 3.10+)"))
    for module, label in (("bleak", "Bleak"), ("numpy", "NumPy"), ("opencc", "OpenCC")):
        checks.append(_module_check(module, label))

    engine = resolve_engine("auto")
    if engine == "mlx":
        checks.append(_module_check("mlx_whisper", "MLX Whisper"))
    else:
        checks.append(_module_check("faster_whisper", "faster-whisper"))

    try:
        adapter = create_platform()
        checks.append(adapter.check_input_permission(args.request_permissions))
    except Exception as exc:
        adapter = None
        checks.append((False, f"platform adapter failed: {exc}"))

    cached = UserConfig().get("device_id")
    checks.append((True, f"cached device: {cached}" if cached else "no cached device; first run will scan by name"))

    for passed, message in checks:
        print(f"[{'ok' if passed else 'fail'}] {message}")
    failed = any(not passed for passed, _ in checks)

    if args.ble and adapter is not None and not failed:
        try:
            asyncio.run(check(args.device_id, adapter))
        except Exception as exc:
            print(f"[fail] BLE check failed: {exc}")
            failed = True

    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
