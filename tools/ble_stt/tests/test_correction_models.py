import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ble_stt.correction_models import (
    LLAMA_RUNTIME_ASSETS,
    _runtime_asset_key,
    delete_correction_model,
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


if __name__ == "__main__":
    unittest.main()
