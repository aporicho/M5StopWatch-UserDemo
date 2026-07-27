import asyncio
import unittest

from ble_stt.correction import CorrectionResult
from ble_stt.main import SpeechController, SpeechSession
from ble_stt.preferences import CorrectionPreferences, TypingPreferences, VoicePreferences
from ble_stt.types import TextReplacementResult, TranscriptSegment
from ble_stt.typing_output import AnimatedTextWriter


class FakeRecognizer:
    def __init__(self, texts):
        self.texts = iter(texts)

    def transcribe(self, pcm, context=None):
        text = next(self.texts)
        return [TranscriptSegment(0.0, len(pcm) / 16000.0, text)] if text else []


class FakeCorrector:
    def __init__(self, corrected):
        self.corrected = corrected

    def correct(self, text, preferences):
        return CorrectionResult(
            raw_text=text,
            text=self.corrected,
            state="corrected" if text != self.corrected else "unchanged",
            changed=text != self.corrected,
            reason="accepted",
            latency_ms=2,
        )


class FakeInjector:
    def __init__(self, replacement="replaced"):
        self.value = ""
        self.replacement = replacement

    def active_window(self):
        return "window"

    def type_text(self, text, expected_window):
        self.value += text
        return expected_window == "window"

    def replace_verified_suffix(self, expected_suffix, replacement, expected_window):
        if self.replacement != "replaced":
            return TextReplacementResult(False, self.replacement)
        if expected_window != "window" or not self.value.endswith(expected_suffix):
            return TextReplacementResult(False, "text_mismatch")
        self.value = self.value[: -len(expected_suffix)] + replacement
        return TextReplacementResult(True, "replaced")


def preferences():
    return VoicePreferences(
        correction=CorrectionPreferences(enabled=True),
        typing=TypingPreferences(enabled=False),
    )


class SpeechRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def make_session(self, injector, emitted):
        prefs = preferences()
        writer = AnimatedTextWriter(injector, "window", prefs.typing)
        writer.enqueue(emitted)
        await writer.drain()
        return SpeechSession(
            7,
            "window",
            audio=[1] * 32000,
            audio_cursor=16000,
            has_output=bool(emitted),
            preferences=prefs,
            output_writer=writer,
        )

    async def run_finalize(self, recognizer, corrector, injector, session):
        controller = SpeechController(recognizer, injector, 1.0, 0.5, corrector=corrector)
        controller._publish_telemetry = lambda **kwargs: None
        await controller._finalize(session)
        return controller

    async def test_appends_corrected_remainder_with_writer(self):
        injector = FakeInjector()
        session = await self.make_session(injector, "我想去北")

        controller = await self.run_finalize(
            FakeRecognizer(["我想去北京"]), FakeCorrector("我想去北京"), injector, session
        )

        self.assertEqual(injector.value, "我想去北京")
        self.assertEqual(controller._last_text["text"], "我想去北京")

    async def test_replaces_only_the_verified_changed_suffix(self):
        injector = FakeInjector()
        session = await self.make_session(injector, "明天去上海")

        controller = await self.run_finalize(
            FakeRecognizer(["明天去北京"]), FakeCorrector("明天去北京"), injector, session
        )

        self.assertEqual(injector.value, "明天去北京")
        self.assertEqual(controller._last_text["replacement"], "replaced")

    async def test_mismatch_keeps_existing_text_and_appends_uncommitted_tail(self):
        injector = FakeInjector(replacement="unsupported")
        session = await self.make_session(injector, "你好世")

        controller = await self.run_finalize(
            FakeRecognizer(["你好啊", "界"]), FakeCorrector("你好啊"), injector, session
        )

        self.assertEqual(injector.value, "你好世界")
        self.assertEqual(controller._last_text["replacement"], "unsupported")

    async def test_focus_failure_never_sends_fallback_keystrokes(self):
        injector = FakeInjector(replacement="focus_changed")
        session = await self.make_session(injector, "你好世")

        controller = await self.run_finalize(
            FakeRecognizer(["你好啊"]), FakeCorrector("你好啊"), injector, session
        )

        self.assertEqual(injector.value, "你好世")
        self.assertEqual(controller._last_text["replacement"], "focus_changed")


if __name__ == "__main__":
    unittest.main()
