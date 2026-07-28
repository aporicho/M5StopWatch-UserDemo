import tempfile
import unittest
from pathlib import Path

from ble_stt.config import UserConfig
from ble_stt.preferences import (
    DEFAULT_CORRECTION_FILE,
    DEFAULT_CORRECTION_MODEL,
    DEFAULT_CORRECTION_REPOSITORY,
    read_voice_preferences,
    save_voice_preferences,
)


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

    def test_legacy_model_selection_is_migrated_to_product_pinned_model(self):
        with tempfile.TemporaryDirectory() as directory:
            config = UserConfig(Path(directory) / "config.json")
            config.set(
                "correction",
                {
                    "repository": "Qwen/Qwen3-4B-GGUF",
                    "filename": "Qwen3-4B-Q4_K_M.gguf",
                },
            )
            preferences = read_voice_preferences(config)

        self.assertEqual(preferences.correction.repository, DEFAULT_CORRECTION_REPOSITORY)
        self.assertEqual(preferences.correction.filename, DEFAULT_CORRECTION_FILE)
        self.assertEqual(preferences.correction.model, DEFAULT_CORRECTION_MODEL)

    def test_user_can_select_balanced_correction_model(self):
        with tempfile.TemporaryDirectory() as directory:
            config = UserConfig(Path(directory) / "config.json")
            saved = save_voice_preferences(
                {"correction": {"model": "balanced"}},
                config,
            )
            loaded = read_voice_preferences(UserConfig(config.path))

        self.assertEqual(saved.correction.model, "balanced")
        self.assertEqual(loaded.correction.model, "balanced")
        self.assertEqual(
            loaded.correction.filename,
            "qwen2.5-1.5b-instruct-q3_k_m.gguf",
        )


if __name__ == "__main__":
    unittest.main()
