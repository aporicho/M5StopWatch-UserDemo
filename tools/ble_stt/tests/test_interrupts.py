import contextlib
import io
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch

from ble_stt import check as check_module
from ble_stt import cli
from ble_stt import main as runtime


class InterruptExitTests(unittest.TestCase):
    def test_once_runtime_interrupt_exits_130(self):
        stderr = io.StringIO()
        with patch("ble_stt.main.async_main", new=AsyncMock(side_effect=KeyboardInterrupt)):
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    runtime.main(["--once"])

        self.assertEqual(raised.exception.code, 130)
        self.assertIn("Stopped", stderr.getvalue())

    def test_run_test_interrupt_restores_service_without_success_message(self):
        manager = Mock()
        manager.is_active.return_value = True
        stdout = io.StringIO()
        with patch("ble_stt.cli.ServiceManager", return_value=manager):
            with patch("ble_stt.main.main", side_effect=SystemExit(130)):
                with contextlib.redirect_stdout(stdout):
                    with self.assertRaises(SystemExit) as raised:
                        cli.run_test([])

        self.assertEqual(raised.exception.code, 130)
        manager.stop.assert_called_once_with()
        manager.start.assert_called_once_with()
        self.assertNotIn("[ok] Speech was recognized", stdout.getvalue())

    def test_run_test_interrupt_keeps_exit_130_when_service_restore_fails(self):
        manager = Mock()
        manager.is_active.return_value = True
        manager.start.side_effect = RuntimeError("restart failed")
        stderr = io.StringIO()
        with patch("ble_stt.cli.ServiceManager", return_value=manager):
            with patch("ble_stt.main.main", side_effect=SystemExit(130)):
                with contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        cli.run_test([])

        self.assertEqual(raised.exception.code, 130)
        manager.stop.assert_called_once_with()
        manager.start.assert_called_once_with()
        self.assertIn("Could not restart the background helper", stderr.getvalue())

    def test_run_test_treats_runtime_exit_zero_as_success(self):
        manager = Mock()
        manager.is_active.return_value = True
        stdout = io.StringIO()
        with patch("ble_stt.cli.ServiceManager", return_value=manager):
            with patch("ble_stt.main.main", side_effect=SystemExit(0)):
                with contextlib.redirect_stdout(stdout):
                    code = cli.run_test([])

        self.assertEqual(code, 0)
        manager.stop.assert_called_once_with()
        manager.start.assert_called_once_with()
        self.assertIn("[ok] Speech was recognized", stdout.getvalue())

    def test_run_test_success_fails_if_service_restore_fails(self):
        manager = Mock()
        manager.is_active.return_value = True
        manager.start.side_effect = RuntimeError("restart failed")
        with patch("ble_stt.cli.ServiceManager", return_value=manager):
            with patch("ble_stt.main.main", side_effect=SystemExit(0)):
                with self.assertRaisesRegex(RuntimeError, "restart failed"):
                    cli.run_test([])

    def test_ble_check_interrupt_exits_130(self):
        stderr = io.StringIO()
        with patch.object(sys, "argv", ["ble-stt-check"]):
            with patch("ble_stt.check.check", new=AsyncMock(side_effect=KeyboardInterrupt)):
                with contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        check_module.main()

        self.assertEqual(raised.exception.code, 130)
        self.assertIn("Cancelled", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
