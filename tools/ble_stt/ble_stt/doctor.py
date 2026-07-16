from __future__ import annotations

import argparse
import asyncio
import importlib
import math
import platform
import sys
import time
from typing import Sequence

from .check import check
from .config import UserConfig
from .platforms import create_platform
from .recognizers import resolve_engine


DEFAULT_PERMISSION_WAIT_SECONDS = 120.0
PERMISSION_POLL_INTERVAL_SECONDS = 1.0


def _module_check(name: str, label: str) -> tuple[bool, str]:
    try:
        importlib.import_module(name)
    except Exception as exc:
        return False, f"{label} could not be loaded: {exc}"
    return True, f"{label} is installed"


def _nonnegative_seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number of seconds") from exc
    if seconds < 0 or not math.isfinite(seconds):
        raise argparse.ArgumentTypeError("must be a finite number that is zero or greater")
    return seconds


def _format_seconds(seconds: float) -> str:
    return str(int(seconds)) if seconds.is_integer() else f"{seconds:g}"


def _wait_for_input_permission(
    adapter: object,
    prompt: bool,
    wait_seconds: float | None,
) -> tuple[bool, str]:
    check_permission = getattr(adapter, "check_input_permission")
    passed, message = check_permission(prompt)
    if passed or wait_seconds == 0:
        return bool(passed), str(message)

    open_settings = getattr(adapter, "open_input_permission_settings", None)
    if prompt and callable(open_settings):
        try:
            open_settings()
        except Exception as exc:
            print(f"[warn] could not open Accessibility settings: {exc}")

    if wait_seconds is None:
        print(
            "[wait] Enable M5StopWatch under Privacy & Security > Accessibility "
            "(press Ctrl-C to cancel)",
            flush=True,
        )
    else:
        formatted_wait = _format_seconds(wait_seconds)
        print(
            f"[wait] Enable M5StopWatch under Privacy & Security > Accessibility "
            f"(waiting up to {formatted_wait}s; press Ctrl-C to cancel)",
            flush=True,
        )
    remaining = wait_seconds
    while remaining is None or remaining > 0:
        delay = (
            PERMISSION_POLL_INTERVAL_SECONDS
            if remaining is None
            else min(PERMISSION_POLL_INTERVAL_SECONDS, remaining)
        )
        time.sleep(delay)
        if remaining is not None:
            remaining -= delay
        passed, message = check_permission(False)
        if passed:
            return True, str(message)
    assert wait_seconds is not None
    formatted_wait = _format_seconds(wait_seconds)
    return False, f"{message}; timed out after {formatted_wait}s"


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check M5StopWatch STT platform requirements")
    parser.add_argument("--request-permissions", action="store_true", help="show the macOS Accessibility prompt")
    wait_group = parser.add_mutually_exclusive_group()
    wait_group.add_argument(
        "--wait",
        type=_nonnegative_seconds,
        metavar="SECONDS",
        help=(
            "wait for Accessibility approval (defaults to 120 seconds with "
            "--request-permissions)"
        ),
    )
    wait_group.add_argument(
        "--wait-forever",
        action="store_true",
        help="wait until Accessibility approval or Ctrl-C",
    )
    parser.add_argument("--ble", action="store_true", help="also connect to and validate the watch")
    parser.add_argument("--device-id", "--address", dest="device_id")
    args = parser.parse_args(argv)

    checks: list[tuple[bool, str]] = []
    if getattr(sys, "frozen", False):
        # A frozen App is validated as one product. Importing every ML module
        # here is both noisy and can initialize Metal before it is needed.
        checks.append((True, "M5StopWatch app runtime is ready"))
    else:
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
        if args.wait_forever:
            wait_seconds = None
        else:
            wait_seconds = args.wait
        if wait_seconds is None and not args.wait_forever:
            wait_seconds = DEFAULT_PERMISSION_WAIT_SECONDS if args.request_permissions else 0.0
        checks.append(
            _wait_for_input_permission(
                adapter,
                prompt=args.request_permissions,
                wait_seconds=wait_seconds,
            )
        )
    except Exception as exc:
        adapter = None
        checks.append((False, f"platform adapter failed: {exc}"))

    cached = UserConfig().get("device_id")
    checks.append((True, f"cached device: {cached}" if cached else "no cached device; first run will scan by name"))

    for passed, message in checks:
        print(f"[{'ok' if passed else 'fail'}] {message}")
    failed = any(not passed for passed, _ in checks)

    if args.ble and adapter is not None:
        try:
            asyncio.run(check(args.device_id, adapter))
        except Exception as exc:
            print(f"[fail] BLE check failed: {exc}")
            failed = True

    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> None:
    try:
        code = run(argv)
    except KeyboardInterrupt:
        print("\nCancelled", file=sys.stderr)
        code = 130
    raise SystemExit(code)


if __name__ == "__main__":
    main()
