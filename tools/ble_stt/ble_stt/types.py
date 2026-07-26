from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class RecognitionContext:
    mode: str = "dictation"
    command_phrases: tuple[str, ...] = ()


class Recognizer(Protocol):
    def transcribe(self, pcm: list[int], context: RecognitionContext | None = None) -> list[TranscriptSegment]: ...


class TextInjector(Protocol):
    def active_window(self) -> object | None: ...

    def type_text(self, text: str, expected_window: object | None) -> bool: ...
