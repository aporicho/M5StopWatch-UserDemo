import contextlib
import io
import unittest
from unittest.mock import Mock, patch

from ble_stt import doctor


class FakePermissionAdapter:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []
        self.opened = 0

    def check_input_permission(self, prompt=False):
        self.calls.append(prompt)
        return next(self.results)

    def open_input_permission_settings(self):
        self.opened += 1


class PermissionWaitTests(unittest.TestCase):
    def test_wait_rejects_non_finite_values(self):
        for value in ("nan", "inf", "-inf"):
            with self.subTest(value=value):
                with self.assertRaises(Exception):
                    doctor._nonnegative_seconds(value)

    def test_module_check_imports_the_module(self):
        with patch("ble_stt.doctor.importlib.import_module", side_effect=RuntimeError("broken dependency")):
            passed, message = doctor._module_check("example", "Example")

        self.assertFalse(passed)
        self.assertIn("broken dependency", message)

    def test_prompts_once_then_polls_without_prompt(self):
        adapter = FakePermissionAdapter(
            [
                (False, "not granted"),
                (False, "not granted"),
                (True, "granted"),
            ]
        )
        with patch("ble_stt.doctor.time.sleep") as sleep:
            passed, message = doctor._wait_for_input_permission(adapter, True, 3.0)

        self.assertTrue(passed)
        self.assertEqual(message, "granted")
        self.assertEqual(adapter.calls, [True, False, False])
        self.assertEqual(adapter.opened, 1)
        self.assertEqual(sleep.call_count, 2)

    def test_zero_wait_only_checks_once(self):
        adapter = FakePermissionAdapter([(False, "not granted")])
        passed, message = doctor._wait_for_input_permission(adapter, True, 0.0)

        self.assertFalse(passed)
        self.assertEqual(message, "not granted")
        self.assertEqual(adapter.calls, [True])
        self.assertEqual(adapter.opened, 0)

    def test_wait_timeout_is_reported(self):
        adapter = FakePermissionAdapter(
            [(False, "not granted"), (False, "still not granted"), (False, "still not granted")]
        )
        with patch("ble_stt.doctor.time.sleep"):
            passed, message = doctor._wait_for_input_permission(adapter, True, 2.0)

        self.assertFalse(passed)
        self.assertIn("timed out after 2s", message)
        self.assertEqual(adapter.calls, [True, False, False])

    def test_keyboard_interrupt_propagates_from_wait(self):
        adapter = FakePermissionAdapter([(False, "not granted")])
        with patch("ble_stt.doctor.time.sleep", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                doctor._wait_for_input_permission(adapter, True, 120.0)

    def test_main_turns_keyboard_interrupt_into_exit_130(self):
        stderr = io.StringIO()
        with patch("ble_stt.doctor.run", side_effect=KeyboardInterrupt):
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    doctor.main([])

        self.assertEqual(raised.exception.code, 130)
        self.assertIn("Cancelled", stderr.getvalue())

    @patch("ble_stt.doctor.UserConfig")
    @patch("ble_stt.doctor._wait_for_input_permission", return_value=(True, "granted"))
    @patch("ble_stt.doctor.create_platform", return_value=Mock())
    @patch("ble_stt.doctor._module_check", return_value=(True, "installed"))
    def test_request_permissions_defaults_to_120_second_wait(
        self,
        module_check,
        create_platform,
        wait_for_permission,
        user_config,
    ):
        user_config.return_value.get.return_value = None
        with contextlib.redirect_stdout(io.StringIO()):
            code = doctor.run(["--request-permissions"])

        self.assertEqual(code, 0)
        self.assertEqual(wait_for_permission.call_args.kwargs["wait_seconds"], 120.0)
        self.assertTrue(wait_for_permission.call_args.kwargs["prompt"])


if __name__ == "__main__":
    unittest.main()
