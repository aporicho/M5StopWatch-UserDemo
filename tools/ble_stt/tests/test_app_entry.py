import sys
import types
import unittest
from unittest.mock import Mock, patch

from ble_stt import app_entry


class AppEntryTests(unittest.TestCase):
    def test_frozen_macos_app_without_args_opens_ui(self):
        self.assertTrue(app_entry.should_open_ui([], frozen=True, platform_name="darwin"))

    def test_cli_args_keep_using_cli_even_when_frozen(self):
        self.assertFalse(app_entry.should_open_ui(["run"], frozen=True, platform_name="darwin"))
        self.assertFalse(app_entry.should_open_ui(["status"], frozen=True, platform_name="darwin"))

    def test_source_tree_and_other_platforms_keep_using_cli(self):
        self.assertFalse(app_entry.should_open_ui([], frozen=False, platform_name="darwin"))
        self.assertFalse(app_entry.should_open_ui([], frozen=True, platform_name="linux"))

    def test_ui_route_calls_ui_runner(self):
        with patch.object(app_entry, "should_open_ui", return_value=True):
            with patch.object(app_entry, "run_macos_ui") as run_macos_ui:
                app_entry.main([])
        run_macos_ui.assert_called_once_with()

    def test_cli_route_forwards_arguments(self):
        fake_cli = types.SimpleNamespace(main=Mock())
        with patch.object(app_entry, "should_open_ui", return_value=False):
            with patch.dict(sys.modules, {"ble_stt.cli": fake_cli}):
                app_entry.main(["status"])
        fake_cli.main.assert_called_once_with(["status"])


if __name__ == "__main__":
    unittest.main()
