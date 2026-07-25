from __future__ import annotations

import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
import platform
import sys
import threading
from pathlib import Path
from types import TracebackType
from typing import Any, TextIO

from .config import config_dir, log_dir, model_cache_dir


EVENT_LOG_NAME = "ble-stt-events.log"
MAX_EVENT_LOG_BYTES = 2 * 1024 * 1024
EVENT_LOG_BACKUPS = 5


class _LineLoggingStream:
    def __init__(self, wrapped: TextIO, logger: logging.Logger, level: int, source: str) -> None:
        self._wrapped = wrapped
        self._logger = logger
        self._level = level
        self._source = source
        self._pending = ""

    def write(self, value: str) -> int:
        written = self._wrapped.write(value)
        self._pending += value
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            self._log_line(line.rstrip("\r"))
        return written

    def flush(self) -> None:
        self._wrapped.flush()

    def flush_pending_log_line(self) -> None:
        if self._pending:
            self._log_line(self._pending.rstrip("\r"))
            self._pending = ""

    def _log_line(self, line: str) -> None:
        if line:
            self._logger.log(self._level, "%s: %s", self._source, line)

    def isatty(self) -> bool:
        return self._wrapped.isatty()

    def fileno(self) -> int:
        return self._wrapped.fileno()

    @property
    def encoding(self) -> str | None:
        return self._wrapped.encoding

    @property
    def errors(self) -> str | None:
        return self._wrapped.errors

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)


class RuntimeLogging:
    def __init__(self, component: str, args: Any | None = None) -> None:
        self.component = component
        self.args = args
        self.logger = logging.getLogger("ble_stt")
        self._handler: RotatingFileHandler | None = None
        self._stdout: TextIO | None = None
        self._stderr: TextIO | None = None
        self._excepthook = sys.excepthook
        self._threading_excepthook = getattr(threading, "excepthook", None)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_exception_handler = None

    def __enter__(self) -> logging.Logger:
        directory = log_dir()
        directory.mkdir(parents=True, exist_ok=True)

        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        self._handler = RotatingFileHandler(
            directory / EVENT_LOG_NAME,
            maxBytes=MAX_EVENT_LOG_BYTES,
            backupCount=EVENT_LOG_BACKUPS,
            encoding="utf-8",
        )
        self._handler.setFormatter(
            logging.Formatter(
                "%(asctime)s.%(msecs)03d %(levelname)s [%(process)d:%(threadName)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        self.logger.addHandler(self._handler)

        self._stdout = sys.stdout
        self._stderr = sys.stderr
        sys.stdout = _LineLoggingStream(  # type: ignore[assignment]
            sys.stdout, self.logger, logging.INFO, "stdout"
        )
        sys.stderr = _LineLoggingStream(  # type: ignore[assignment]
            sys.stderr, self.logger, logging.ERROR, "stderr"
        )
        self._install_exception_hooks()
        self._install_asyncio_hook()
        self._log_startup()
        return self.logger

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            self.logger.error("runtime exiting with exception", exc_info=(exc_type, exc, traceback))
        self.logger.info("shutdown component=%s", self.component)
        self._restore()

    def _restore(self) -> None:
        for stream in (sys.stdout, sys.stderr):
            if isinstance(stream, _LineLoggingStream):
                stream.flush_pending_log_line()
        if self._stdout is not None:
            sys.stdout = self._stdout
        if self._stderr is not None:
            sys.stderr = self._stderr
        sys.excepthook = self._excepthook
        if self._threading_excepthook is not None:
            threading.excepthook = self._threading_excepthook
        if self._loop is not None:
            self._loop.set_exception_handler(self._loop_exception_handler)
        if self._handler is not None:
            self.logger.removeHandler(self._handler)
            self._handler.close()
            self._handler = None

    def _install_exception_hooks(self) -> None:
        def excepthook(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
            self.logger.critical("unhandled exception", exc_info=(exc_type, exc, tb))
            self._excepthook(exc_type, exc, tb)

        sys.excepthook = excepthook

        if self._threading_excepthook is not None:

            def threading_hook(args: threading.ExceptHookArgs) -> None:
                thread_name = args.thread.name if args.thread is not None else "unknown"
                self.logger.critical(
                    "unhandled thread exception thread=%s",
                    thread_name,
                    exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
                )
                self._threading_excepthook(args)

            threading.excepthook = threading_hook

    def _install_asyncio_hook(self) -> None:
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._loop_exception_handler = self._loop.get_exception_handler()

        def handler(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
            message = context.get("message", "asyncio exception")
            exception = context.get("exception")
            if exception is not None:
                self.logger.error("asyncio exception: %s", message, exc_info=exception)
            else:
                self.logger.error("asyncio exception: %s context=%r", message, context)
            if self._loop_exception_handler is not None:
                self._loop_exception_handler(loop, context)
            else:
                loop.default_exception_handler(context)

        self._loop.set_exception_handler(handler)

    def _log_startup(self) -> None:
        try:
            from . import __version__
        except Exception:
            __version__ = "unknown"
        selected_env = {
            key: value
            for key, value in os.environ.items()
            if key
            in {
                "BLE_STT_ENGINE",
                "BLE_STT_MODEL",
                "BLE_STT_VERSION",
                "HF_HOME",
                "PATH",
                "PYTHONPATH",
            }
        }
        self.logger.info(
            "startup component=%s version=%s pid=%s platform=%s machine=%s "
            "python=%s executable=%s frozen=%s cwd=%s",
            self.component,
            __version__,
            os.getpid(),
            sys.platform,
            platform.machine(),
            platform.python_version(),
            sys.executable,
            bool(getattr(sys, "frozen", False)),
            os.getcwd(),
        )
        self.logger.info(
            "paths config=%s logs=%s model_cache=%s",
            config_dir(),
            log_dir(),
            model_cache_dir(),
        )
        self.logger.info("args=%r", self.args)
        self.logger.info("env=%r", selected_env)


def runtime_logging(component: str, args: Any | None = None) -> RuntimeLogging:
    return RuntimeLogging(component, args)


def event_log_paths(platform_name: str | None = None) -> tuple[Path, ...]:
    directory = log_dir(platform_name)
    return (directory / EVENT_LOG_NAME, directory / "ble-stt.log", directory / "ble-stt-error.log")
