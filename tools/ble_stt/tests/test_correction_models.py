import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from ble_stt.config import UserConfig
from ble_stt.correction_models import (
    CORRECTION_MODEL_PRESETS,
    CORRECTION_MODEL_PRESET_MAP,
    DEFAULT_CORRECTION_FILE,
    DEFAULT_CORRECTION_PRESET,
    LLAMA_RUNTIME_ASSETS,
    MAX_CORRECTION_MODEL_BYTES,
    _remote_metadata,
    _runtime_asset_key,
    correction_model_status,
    delete_correction_model,
    install_correction_model,
    list_correction_models,
    use_correction_model,
)


class CorrectionModelManagementTests(unittest.TestCase):
    def test_runtime_asset_normalizes_platform_architecture(self):
        self.assertEqual(_runtime_asset_key("darwin", "aarch64"), "darwin-arm64")
        self.assertEqual(_runtime_asset_key("win32", "AMD64"), "win32-x64")
        self.assertIn("linux-x64", LLAMA_RUNTIME_ASSETS)

    def test_deleting_model_keeps_shared_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            model = cache / "correction" / "models" / "Qwen3-4B-Q4_K_M.gguf"
            runtime = cache / "correction" / "runtime" / "llama-server"
            model.parent.mkdir(parents=True)
            runtime.parent.mkdir(parents=True)
            model.write_bytes(b"model")
            runtime.write_bytes(b"runtime")
            runtime.chmod(0o755)
            with patch("ble_stt.correction_models.model_cache_dir", return_value=cache):
                status = delete_correction_model()

            self.assertFalse(model.exists())
            self.assertTrue(runtime.exists())
            self.assertFalse(status.installed)

    def test_status_reports_legacy_model_and_reclaimable_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            legacy = cache / "correction" / "models" / "Qwen3-4B-Q4_K_M.gguf"
            legacy.parent.mkdir(parents=True)
            legacy.write_bytes(b"legacy")
            with (
                patch("ble_stt.correction_models.model_cache_dir", return_value=cache),
                patch("ble_stt.correction_models.llama_server_path", return_value=None),
            ):
                status = correction_model_status()

            self.assertEqual(status.state, "legacy")
            self.assertFalse(status.installed)
            self.assertEqual(status.stale_disk_bytes, len(b"legacy"))
            self.assertLessEqual(status.expected_disk_bytes, MAX_CORRECTION_MODEL_BYTES)

    def test_status_rejects_unverified_same_size_model(self):
        preset = replace(DEFAULT_CORRECTION_PRESET, expected_bytes=5)
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            model = cache / "correction" / "models" / preset.filename
            model.parent.mkdir(parents=True)
            model.write_bytes(b"model")
            with (
                patch("ble_stt.correction_models.model_cache_dir", return_value=cache),
                patch("ble_stt.correction_models.llama_server_path", return_value=Path("/runtime")),
                patch.dict(CORRECTION_MODEL_PRESET_MAP, {"lite": preset}, clear=True),
            ):
                status = correction_model_status(model="lite")

            self.assertFalse(status.installed)
            self.assertEqual(status.state, "partial")

    def test_successful_install_atomically_replaces_legacy_model(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            legacy = cache / "correction" / "models" / "Qwen3-4B-Q4_K_M.gguf"
            legacy.parent.mkdir(parents=True)
            legacy.write_bytes(b"legacy")

            def fake_download(_preset, _revision, local_dir, _cache):
                destination = Path(local_dir) / DEFAULT_CORRECTION_FILE
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"model")
                return destination

            with (
                patch("ble_stt.correction_models.model_cache_dir", return_value=cache),
                patch.dict(
                    CORRECTION_MODEL_PRESET_MAP,
                    {
                        "lite": replace(
                            DEFAULT_CORRECTION_PRESET,
                            expected_bytes=5,
                            revision="rev",
                            sha256="digest",
                        )
                    },
                    clear=True,
                ),
                patch("ble_stt.correction_models._remote_metadata", return_value=("rev", "digest", 5)),
                patch("ble_stt.correction_models.install_correction_runtime"),
                patch("ble_stt.correction_models.llama_server_path", return_value=Path("/runtime")),
                patch("ble_stt.correction_models.sha256_file", return_value="digest"),
                patch("ble_stt.correction_models._download_model", side_effect=fake_download),
            ):
                status = install_correction_model()

            selected = cache / "correction" / "models" / DEFAULT_CORRECTION_FILE
            self.assertEqual(selected.read_bytes(), b"model")
            self.assertFalse(legacy.exists())
            self.assertTrue(status.installed)
            self.assertEqual(status.stale_disk_bytes, 0)

    def test_failed_install_preserves_legacy_model(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            legacy = cache / "correction" / "models" / "Qwen3-4B-Q4_K_M.gguf"
            legacy.parent.mkdir(parents=True)
            legacy.write_bytes(b"legacy")

            def fake_download(_preset, _revision, local_dir, _cache):
                destination = Path(local_dir) / DEFAULT_CORRECTION_FILE
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"model")
                return destination

            with (
                patch("ble_stt.correction_models.model_cache_dir", return_value=cache),
                patch("ble_stt.correction_models._remote_metadata", return_value=("rev", "digest", 5)),
                patch("ble_stt.correction_models.install_correction_runtime"),
                patch("ble_stt.correction_models.sha256_file", return_value="wrong"),
                patch("ble_stt.correction_models._download_model", side_effect=fake_download),
            ):
                with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                    install_correction_model()

            self.assertEqual(legacy.read_bytes(), b"legacy")
            self.assertFalse((legacy.parent / DEFAULT_CORRECTION_FILE).exists())

    def test_configured_model_cannot_exceed_one_gigabyte(self):
        oversized = replace(
            DEFAULT_CORRECTION_PRESET,
            expected_bytes=MAX_CORRECTION_MODEL_BYTES + 1,
        )
        with self.assertRaisesRegex(RuntimeError, "1 GB"):
            _remote_metadata(oversized)

    def test_lists_two_sub_gigabyte_presets(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            with (
                patch("ble_stt.correction_models.model_cache_dir", return_value=cache),
                patch("ble_stt.correction_models.llama_server_path", return_value=None),
            ):
                models = list_correction_models()

        self.assertEqual([model["id"] for model in models], ["lite", "balanced"])
        self.assertTrue(
            all(
                preset.expected_bytes <= MAX_CORRECTION_MODEL_BYTES
                for preset in CORRECTION_MODEL_PRESETS
            )
        )

    def test_user_can_switch_correction_model_without_downloading(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache"
            config = UserConfig(Path(directory) / "config.json")
            with (
                patch("ble_stt.correction_models.model_cache_dir", return_value=cache),
                patch("ble_stt.correction_models.llama_server_path", return_value=None),
            ):
                status = use_correction_model("balanced", config)

            self.assertEqual(status.model, "balanced")
            self.assertEqual(
                config.get("correction")["model"],
                "balanced",
            )

    def test_installed_presets_coexist_and_delete_only_removes_selected_model(self):
        lite = replace(CORRECTION_MODEL_PRESETS[0], expected_bytes=4)
        balanced = replace(CORRECTION_MODEL_PRESETS[1], expected_bytes=8)
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            models = cache / "correction" / "models"
            models.mkdir(parents=True)
            lite_path = models / lite.filename
            balanced_path = models / balanced.filename
            lite_path.write_bytes(b"lite")
            balanced_path.write_bytes(b"balanced")
            (cache / "correction" / "model.json").write_text(
                json.dumps(
                    {
                        "schema": 2,
                        "models": {
                            "lite": {
                                "filename": lite.filename,
                                "revision": lite.revision,
                                "sha256": lite.sha256,
                                "size": lite.expected_bytes,
                            },
                            "balanced": {
                                "filename": balanced.filename,
                                "revision": balanced.revision,
                                "sha256": balanced.sha256,
                                "size": balanced.expected_bytes,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch("ble_stt.correction_models.model_cache_dir", return_value=cache),
                patch("ble_stt.correction_models.llama_server_path", return_value=Path("/runtime")),
                patch.dict(
                    CORRECTION_MODEL_PRESET_MAP,
                    {"lite": lite, "balanced": balanced},
                    clear=True,
                ),
            ):
                self.assertTrue(correction_model_status(model="lite").installed)
                self.assertTrue(correction_model_status(model="balanced").installed)
                deleted = delete_correction_model(model="balanced")

            self.assertFalse(deleted.installed)
            self.assertTrue(lite_path.exists())
            self.assertFalse(balanced_path.exists())


if __name__ == "__main__":
    unittest.main()
