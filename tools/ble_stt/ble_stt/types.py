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
    prompt_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class TextReplacementResult:
    replaced: bool
    reason: str


class Recognizer(Protocol):
    def transcribe(self, pcm: list[int], context: RecognitionContext | None = None) -> list[TranscriptSegment]: ...


class TextInjector(Protocol):
    def active_window(self) -> object | None: ...

    def type_text(self, text: str, expected_window: object | None) -> bool: ...

    def tap_key(self, key_code: int, modifiers: int, expected_window: object | None) -> bool: ...

    def replace_verified_suffix(
        self,
        expected_suffix: str,
        replacement: str,
        expected_window: object | None,
    ) -> TextReplacementResult: ...
