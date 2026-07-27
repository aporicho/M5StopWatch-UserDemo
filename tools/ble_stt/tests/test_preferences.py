import tempfile
import unittest
from pathlib import Path

from ble_stt.config import UserConfig
from ble_stt.preferences import read_voice_preferences, save_voice_preferences


class VoicePreferencesTests(unittest.TestCase):
    def test_defaults_are_safe_and_do_not_download_a_model(self):
        with tempfile.TemporaryDirectory() as directory:
            config = UserConfig(Path(directory) / "config.json")
            preferences = read_voice_preferences(config)

        self.assertFalse(preferences.correction.enabled)
        self.assertEqual(preferences.correction.languages, ("zh-CN", "en"))
        self.assertTrue(preferences.typing.enabled)
        self.assertEqual(preferences.typing.characters_per_second, 40)

    def test_save_normalizes_glossary_and_typing_speed(self):
        with tempfile.TemporaryDirectory() as directory:
            config = UserConfig(Path(directory) / "config.json")
            saved = save_voice_preferences(
                {
                    "correction": {"enabled": True, "glossary": ["M5StopWatch", " M5StopWatch ", "Qwen"]},
                    "typing": {"characters_per_second": 999, "auto_accelerate": False},
                },
                config,
            )
            loaded = read_voice_preferences(UserConfig(config.path))

        self.assertTrue(saved.correction.enabled)
        self.assertEqual(saved.correction.glossary, ("M5StopWatch", "Qwen"))
        self.assertEqual(saved.typing.characters_per_second, 100)
        self.assertFalse(loaded.typing.auto_accelerate)


if __name__ == "__main__":
    unittest.main()
