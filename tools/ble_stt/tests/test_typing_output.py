import asyncio
import unittest

from ble_stt.preferences import TypingPreferences
from ble_stt.typing_output import AnimatedTextWriter


class FakeInjector:
    def __init__(self):
        self.values = []

    def active_window(self):
        return "window"

    def type_text(self, text, expected_window):
        if expected_window != "window":
            return False
        self.values.append(text)
        return True

    def tap_key(self, key_code, modifiers, expected_window):
        return True


async def no_sleep(_delay):
    return None


class AnimatedTextWriterTests(unittest.IsolatedAsyncioTestCase):
    async def test_writes_graphemes_in_order(self):
        injector = FakeInjector()
        writer = AnimatedTextWriter(
            injector,
            "window",
            TypingPreferences(characters_per_second=40),
            sleeper=no_sleep,
        )
        writer.enqueue("你e\u0301好")
        self.assertTrue(await writer.drain())
        await writer.close()

        self.assertEqual(injector.values, ["你", "e\u0301", "好"])
        self.assertEqual(writer.emitted_text, "你e\u0301好")

    async def test_cancel_returns_text_that_was_not_emitted(self):
        blocker = asyncio.Event()

        async def blocked_sleep(_delay):
            await blocker.wait()

        injector = FakeInjector()
        writer = AnimatedTextWriter(
            injector,
            "window",
            TypingPreferences(characters_per_second=10),
            sleeper=blocked_sleep,
        )
        writer.enqueue("你好世界")
        await asyncio.sleep(0)
        discarded = await writer.cancel_pending()
        blocker.set()
        await writer.close(cancel=True)

        self.assertEqual(writer.emitted_text, "你")
        self.assertEqual(discarded, "好世界")


if __name__ == "__main__":
    unittest.main()
