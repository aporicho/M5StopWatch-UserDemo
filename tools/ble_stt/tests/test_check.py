import unittest

from ble_stt.check import HID_SERVICE_UUID, error_detail, missing_required_services
from ble_stt.protocol import SERVICE_UUID


class CheckDiagnosticTests(unittest.TestCase):
    def test_missing_required_services_requires_hid_and_speech(self):
        self.assertEqual(
            missing_required_services(set()),
            ["HID service 0x1812", "Speech GATT service"],
        )
        self.assertEqual(
            missing_required_services({HID_SERVICE_UUID, SERVICE_UUID}),
            [],
        )

    def test_error_detail_falls_back_to_exception_type(self):
        self.assertEqual(error_detail(TimeoutError()), "TimeoutError")
        self.assertEqual(error_detail(RuntimeError("broken")), "broken")


if __name__ == "__main__":
    unittest.main()
