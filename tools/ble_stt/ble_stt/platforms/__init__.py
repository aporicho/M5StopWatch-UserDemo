from __future__ import annotations

import sys

from ..config import UserConfig
from .base import PlatformAdapter


def create_platform(platform_name: str | None = None, config: UserConfig | None = None) -> PlatformAdapter:
    platform_name = platform_name or sys.platform
    if platform_name == "linux":
        from .linux import LinuxPlatform

        return LinuxPlatform(config)
    if platform_name == "darwin":
        from .macos import MacOSPlatform

        return MacOSPlatform(config)
    if platform_name == "win32":
        from .windows import WindowsPlatform

        return WindowsPlatform(config)
    raise RuntimeError(f"unsupported platform: {platform_name}")


__all__ = ["PlatformAdapter", "create_platform"]
