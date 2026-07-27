from __future__ import annotations

import atexit
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .config import log_dir
from .correction_models import CorrectionModelStatus, correction_model_status


class LlamaServerError(RuntimeError):
    pass


class LlamaServerClient:
    def __init__(self, status: CorrectionModelStatus | None = None) -> None:
        self.status = status or correction_model_status()
        self._fixed_status = status is not None
        self.process: subprocess.Popen[bytes] | None = None
        self.port: int | None = None
        self.token = secrets.token_urlsafe(24)
        self._lock = threading.RLock()
        self._log_stream: Any | None = None
        atexit.register(self.close)

    @staticmethod
    def _available_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as stream:
            stream.bind(("127.0.0.1", 0))
            return int(stream.getsockname()[1])

    def _request(
        self,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout: float,
    ) -> dict[str, Any]:
        if self.port is None:
            raise LlamaServerError("llama-server has not started")
        data = None
        headers = {"Authorization": f"Bearer {self.token}"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            headers=headers,
            method="POST" if payload is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                value = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read(256).decode("utf-8", errors="replace").strip()
            finally:
                exc.close()
            message = f"HTTP {exc.code}"
            if detail:
                message += f": {detail}"
            raise LlamaServerError(message) from exc
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise LlamaServerError(str(exc)) from exc
        if not isinstance(value, dict):
            raise LlamaServerError("llama-server returned a non-object response")
        return value

    def start(self, timeout: float = 20.0) -> None:
        with self._lock:
            if self.process is not None and self.process.poll() is None:
                return
            if not self._fixed_status:
                self.status = correction_model_status()
            if not self.status.installed:
                raise LlamaServerError(self.status.message)
            if not self.status.runtime_available or not self.status.runtime_path:
                raise LlamaServerError("llama-server runtime is unavailable")

            self.port = self._available_port()
            log_path = log_dir() / "ble-stt-correction.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_stream = log_path.open("ab", buffering=0)
            command = [
                self.status.runtime_path,
                "--model",
                self.status.path,
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--api-key",
                self.token,
                "--ctx-size",
                "2048",
                "--predict",
                "256",
                "--parallel",
                "1",
                "--jinja",
                "--no-webui",
            ]
            if sys.platform == "darwin":
                command.extend(("--n-gpu-layers", "99"))
            else:
                command.extend(("--threads", str(max(1, (os.cpu_count() or 4) // 2))))
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=self._log_stream,
                stderr=subprocess.STDOUT,
                start_new_session=sys.platform != "win32",
            )

            deadline = time.monotonic() + timeout
            last_error = "server did not become ready"
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    code = self.process.returncode
                    self.close()
                    raise LlamaServerError(f"llama-server exited during startup ({code})")
                try:
                    self._request("/health", timeout=0.5)
                    return
                except LlamaServerError as exc:
                    last_error = str(exc)
                    time.sleep(0.1)
            self.close()
            raise LlamaServerError(f"llama-server startup timed out: {last_error}")

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        timeout: float = 2.5,
        max_tokens: int = 256,
    ) -> str:
        with self._lock:
            self.start()
            try:
                response = self._request(
                    "/v1/chat/completions",
                    payload={
                        "model": self.status.filename,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "chat_template_kwargs": {"enable_thinking": False},
                        "temperature": 0,
                        "max_tokens": max(16, min(512, max_tokens)),
                        "stream": False,
                        "response_format": {
                            "type": "json_schema",
                            "schema": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                                "required": ["text"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    timeout=timeout,
                )
            except LlamaServerError:
                # llama-server keeps generating after an HTTP client timeout.
                # Stop the private process so one slow sentence cannot leave
                # the next dictation stuck behind a busy slot/HTTP 503.
                self.close()
                raise
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlamaServerError("llama-server response did not contain message content") from exc
        return str(content).strip()

    def close(self) -> None:
        with self._lock:
            process, self.process = self.process, None
            self.port = None
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            if self._log_stream is not None:
                try:
                    self._log_stream.close()
                except OSError:
                    pass
                self._log_stream = None
