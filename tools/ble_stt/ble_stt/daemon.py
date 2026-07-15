from __future__ import annotations

import contextlib
import sys

from .config import log_dir
from .main import main as runtime_main


def main() -> None:
    """Run the helper with file logging on service managers without redirection."""
    directory = log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "ble-stt.log").open("a", encoding="utf-8", buffering=1) as stdout:
        with (directory / "ble-stt-error.log").open("a", encoding="utf-8", buffering=1) as stderr:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                runtime_main(sys.argv[1:])


if __name__ == "__main__":
    main()
