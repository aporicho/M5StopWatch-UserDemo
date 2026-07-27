from __future__ import annotations

import asyncio
import random
from collections import deque
from collections.abc import Callable

from .correction import graphemes
from .preferences import TypingPreferences
from .types import TextInjector


PUNCTUATION = frozenset("，。！？；：、,.!?;:\n")


class AnimatedTextWriter:
    def __init__(
        self,
        injector: TextInjector,
        expected_window: object | None,
        preferences: TypingPreferences,
        *,
        on_emit: Callable[[str], None] | None = None,
        sleeper: Callable[[float], asyncio.Future[None] | asyncio.Task[None] | object] | None = None,
        random_source: random.Random | None = None,
    ) -> None:
        self.injector = injector
        self.expected_window = expected_window
        self.preferences = preferences
        self.on_emit = on_emit
        self._sleeper = sleeper or asyncio.sleep
        self._random = random_source or random.Random()
        self._pending: deque[str] = deque()
        self._wake = asyncio.Event()
        self._drained = asyncio.Event()
        self._drained.set()
        self._task: asyncio.Task[None] | None = None
        self._closed = False
        self._inflight = False
        self.failed = False
        self.error: str | None = None
        self.emitted: list[str] = []

    @property
    def emitted_text(self) -> str:
        return "".join(self.emitted)

    @property
    def pending_text(self) -> str:
        return "".join(self._pending)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    def enqueue(self, text: str) -> bool:
        if not text or self._closed or self.failed:
            return not self.failed
        self.start()
        values = graphemes(text) if self.preferences.enabled else [text]
        self._pending.extend(values)
        self._drained.clear()
        self._wake.set()
        return True

    def _delay(self, value: str) -> float:
        if not self.preferences.enabled:
            return 0.0
        base_cps = float(self.preferences.characters_per_second)
        backlog_seconds = len(self._pending) / max(1.0, base_cps)
        cps = base_cps
        if self.preferences.auto_accelerate and backlog_seconds > 0.75:
            cps = min(
                float(self.preferences.max_characters_per_second),
                base_cps * (1.0 + backlog_seconds / 0.75),
            )
        delay = self._random.uniform(0.85, 1.15) / max(1.0, cps)
        if value and value[-1] in PUNCTUATION:
            delay += min(0.08, 2.5 / max(1.0, cps))
        return delay

    async def _sleep(self, delay: float) -> None:
        if delay <= 0:
            return
        result = self._sleeper(delay)
        if hasattr(result, "__await__"):
            await result  # type: ignore[misc]

    async def _run(self) -> None:
        while not self._closed:
            if not self._pending:
                self._wake.clear()
                self._drained.set()
                await self._wake.wait()
                continue
            value = self._pending.popleft()
            self._inflight = True
            try:
                if not self.injector.type_text(value, self.expected_window):
                    self.failed = True
                    self.error = "focus_changed"
                    self._pending.clear()
                    self._drained.set()
                    return
                self.emitted.append(value)
                if self.on_emit is not None:
                    self.on_emit(value)
            except Exception as exc:
                self.failed = True
                self.error = str(exc)
                self._pending.clear()
                self._drained.set()
                return
            finally:
                self._inflight = False
            await self._sleep(self._delay(value))
        self._drained.set()

    async def cancel_pending(self) -> str:
        discarded = self.pending_text
        self._pending.clear()
        while self._inflight:
            await asyncio.sleep(0)
        if not self._pending:
            self._drained.set()
        return discarded

    async def drain(self) -> bool:
        if self._task is None:
            return True
        await self._drained.wait()
        return not self.failed

    async def close(self, *, cancel: bool = False) -> None:
        if self._closed:
            return
        if cancel:
            await self.cancel_pending()
        else:
            await self.drain()
        self._closed = True
        self._wake.set()
        if self._task is not None:
            await self._task
