from __future__ import annotations

import os
import subprocess


def common_prefix(left: str, right: str) -> str:
    length = min(len(left), len(right))
    index = 0
    while index < length and left[index] == right[index]:
        index += 1
    return left[:index]


def stable_extension(previous: str, current: str, committed: str) -> tuple[str, str]:
    agreed = common_prefix(previous, current)
    if not agreed.startswith(committed):
        return "", committed

    # Do not commit the last unfinished ASCII word. CJK characters do not need
    # a whitespace boundary and can be committed individually.
    safe = agreed
    if safe and safe[-1].isascii() and safe[-1].isalnum():
        boundary = len(safe)
        while boundary > len(committed) and safe[boundary - 1].isascii() and (
            safe[boundary - 1].isalnum() or safe[boundary - 1] in "_-.'"
        ):
            boundary -= 1
        safe = safe[:boundary]
    if len(safe) <= len(committed):
        return "", committed
    return safe[len(committed):], safe


class TextInjector:
    def __init__(self) -> None:
        self._warned_no_focus = False

    @staticmethod
    def active_window() -> str | None:
        try:
            result = subprocess.run(
                ["hyprctl", "activewindow", "-j"], check=True, capture_output=True, text=True, timeout=2
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            return None
        import json

        try:
            value = json.loads(result.stdout).get("address")
        except (json.JSONDecodeError, AttributeError):
            return None
        return str(value) if value else None

    def type_text(self, text: str, expected_window: str | None) -> bool:
        if not text:
            return True
        current = self.active_window()
        if expected_window and current != expected_window:
            print("[focus] active window changed; suppressing text injection")
            return False
        if expected_window is None and not self._warned_no_focus:
            print("[focus] unable to read Hyprland active window; typing into the current focus")
            self._warned_no_focus = True
        try:
            subprocess.run(["wtype", "--", text], check=True, env=os.environ.copy())
        except FileNotFoundError:
            raise RuntimeError("wtype is not installed") from None
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"wtype failed with exit code {exc.returncode}") from exc
        return True
