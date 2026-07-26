import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ble_stt.config import UserConfig
from ble_stt.models import (
    DEFAULT_MODEL,
    bundled_cache_path,
    list_models,
    model_status,
    runtime_model_name,
    selected_model,
    use_model,
)


class ModelManagementTests(unittest.TestCase):
    def test_default_selection_is_small(self):
        with tempfile.TemporaryDirectory() as directory:
            config = UserConfig(Path(directory) / "ble-stt.json")

            with patch("ble_stt.models.model_cache_dir", return_value=Path(directory) / "cache"):
                engine, model = selected_model(config)

        self.assertEqual(engine, "auto")
        self.assertEqual(model, DEFAULT_MODEL)

    def test_use_model_persists_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config = UserConfig(Path(directory) / "ble-stt.json")

            status = use_model("medium", "faster-whisper", config)

            self.assertEqual(config.get("engine"), "faster-whisper")
            self.assertEqual(config.get("model"), "medium")
            self.assertEqual(status.selected, "medium")

    def test_prepared_model_is_reported_ready_when_snapshot_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            snapshot = cache / "hub" / "models--Systran--faster-whisper-medium" / "snapshots" / "revision"
            snapshot.mkdir(parents=True)
            (snapshot / "model.bin").write_text("weights", encoding="utf-8")
            config = UserConfig(Path(directory) / "ble-stt.json")
            config.set("engine", "faster-whisper")
            config.set("model", "medium")
            config.set("prepared_model", "medium")

            with patch("ble_stt.models.model_cache_dir", return_value=cache):
                status = model_status(config)

        self.assertTrue(status.installed)
        self.assertEqual(status.source, "downloaded")
        self.assertEqual(status.state, "ready")

    def test_bundled_small_can_be_registered_as_runtime_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundled = root / "bundled" / "faster-whisper" / "small"
            cache = root / "cache"
            bundled.mkdir(parents=True)
            (bundled / "model.bin").write_text("starter", encoding="utf-8")
            config = UserConfig(root / "ble-stt.json")
            config.set("engine", "faster-whisper")
            config.set("model", "small")

            with patch.dict("os.environ", {"BLE_STT_BUNDLED_MODELS": str(root / "bundled")}):
                with patch("ble_stt.models.model_cache_dir", return_value=cache):
                    status = model_status(config)
                    runtime = runtime_model_name("faster-whisper", "small", config)
                    expected_runtime = bundled_cache_path("faster-whisper", "small")

                    self.assertTrue(status.installed)
                    self.assertEqual(status.source, "bundled")
                    self.assertTrue((Path(runtime) / "model.bin").exists())
                    self.assertEqual(Path(runtime), expected_runtime)

    def test_list_models_reports_four_primary_presets(self):
        with tempfile.TemporaryDirectory() as directory:
            config = UserConfig(Path(directory) / "ble-stt.json")

            with patch("ble_stt.models.model_cache_dir", return_value=Path(directory) / "cache"):
                values = list_models(config)

        self.assertEqual([value["id"] for value in values], ["small", "medium", "large", "turbo"])

    def test_legacy_cache_is_used_when_config_has_no_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            snapshot = (
                cache
                / "hub"
                / "models--mlx-community--whisper-medium-mlx"
                / "snapshots"
                / "revision"
            )
            snapshot.mkdir(parents=True)
            (snapshot / "weights.npz").write_text("weights", encoding="utf-8")
            config = UserConfig(root / "ble-stt.json")

            with patch("ble_stt.models.model_cache_dir", return_value=cache):
                engine, model = selected_model(config)
                status = model_status(config)

        self.assertEqual(engine, "auto")
        self.assertEqual(model, "medium")
        self.assertTrue(status.installed)
        self.assertEqual(status.source, "downloaded")

    def test_partial_hf_cache_is_not_reported_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            repo = cache / "hub" / "models--mlx-community--whisper-small-mlx"
            snapshot = repo / "snapshots" / "revision"
            snapshot.mkdir(parents=True)
            (snapshot / "config.json").write_text("{}", encoding="utf-8")
            (repo / "blobs").mkdir()
            (repo / "blobs" / "weights.incomplete").write_text("partial", encoding="utf-8")
            config = UserConfig(root / "ble-stt.json")
            config.set("engine", "auto")
            config.set("model", "small")

            with patch("ble_stt.models.model_cache_dir", return_value=cache):
                status = model_status(config)

        self.assertFalse(status.installed)
        self.assertEqual(status.state, "partial")
        self.assertIn("incomplete", status.message)

    def test_runtime_uses_local_snapshot_for_downloaded_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            snapshot = (
                cache
                / "hub"
                / "models--mlx-community--whisper-small-mlx"
                / "snapshots"
                / "revision"
            )
            snapshot.mkdir(parents=True)
            (snapshot / "weights.npz").write_text("weights", encoding="utf-8")
            config = UserConfig(root / "ble-stt.json")
            config.set("engine", "auto")
            config.set("model", "small")

            with patch("ble_stt.models.model_cache_dir", return_value=cache):
                runtime = runtime_model_name("auto", "small", config)

        self.assertEqual(Path(runtime), snapshot)

    def test_root_level_hf_cache_layout_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            snapshot = (
                cache
                / "models--mlx-community--whisper-small-mlx"
                / "snapshots"
                / "revision"
            )
            snapshot.mkdir(parents=True)
            (snapshot / "weights.npz").write_text("weights", encoding="utf-8")
            config = UserConfig(root / "ble-stt.json")
            config.set("engine", "auto")
            config.set("model", "small")

            with patch("ble_stt.models.model_cache_dir", return_value=cache):
                status = model_status(config)
                runtime = runtime_model_name("auto", "small", config)

        self.assertTrue(status.installed)
        self.assertEqual(Path(runtime), snapshot)

    def test_stale_custom_metadata_for_preset_is_normalized_to_downloaded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            snapshot = (
                cache
                / "models--mlx-community--whisper-small-mlx"
                / "snapshots"
                / "revision"
            )
            snapshot.mkdir(parents=True)
            (snapshot / "weights.npz").write_text("weights", encoding="utf-8")
            config = UserConfig(root / "ble-stt.json")
            config.set("engine", "auto")
            config.set("model", "small")
            metadata_path = root / "ble-stt-models.json"
            metadata_path.write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "models": {
                            "mlx:small": {
                                "engine": "mlx",
                                "model": "small",
                                "resolved": "mlx-community/whisper-small-mlx",
                                "source": "custom",
                                "installed": True,
                                "cache_path": str(snapshot),
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            with patch("ble_stt.models.model_cache_dir", return_value=cache):
                status = model_status(config)
                runtime = runtime_model_name("auto", "small", config)
                saved = json.loads(metadata_path.read_text(encoding="utf-8"))

        self.assertTrue(status.installed)
        self.assertEqual(status.source, "downloaded")
        self.assertEqual(Path(runtime), snapshot)
        self.assertEqual(saved["models"]["mlx:small"]["source"], "downloaded")


if __name__ == "__main__":
    unittest.main()
