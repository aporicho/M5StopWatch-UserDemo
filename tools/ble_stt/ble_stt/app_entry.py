from __future__ import annotations

import sys
from typing import Sequence


def should_open_ui(
    argv: Sequence[str] | None = None,
    *,
    frozen: bool | None = None,
    platform_name: str | None = None,
) -> bool:
    values = list(sys.argv[1:] if argv is None else argv)
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    selected_platform = platform_name or sys.platform
    return selected_platform == "darwin" and is_frozen and not values


def run_macos_ui() -> None:
    from .diagnostics import RuntimeLogging
    from .macos_ui import run_app

    with RuntimeLogging("macos-ui"):
        run_app()


def main(argv: Sequence[str] | None = None) -> None:
    values = list(sys.argv[1:] if argv is None else argv)
    if should_open_ui(values):
        run_macos_ui()
        return

    from .cli import main as cli_main

    cli_main(values)
