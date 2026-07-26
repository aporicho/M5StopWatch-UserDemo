from __future__ import annotations

from unittest.mock import patch

from ble_stt.config import UserConfig
from ble_stt.mapping import (
    decode_mapping,
    encode_mapping,
    parse_user_event_packet,
    read_mapping,
    save_mapping,
)


def config_at(tmp_path):
    return UserConfig(tmp_path / "ble-stt.json")


def test_default_mapping_contains_voice_and_locked_home(tmp_path):
    mapping = read_mapping(config_at(tmp_path))
    entries = {entry["event"]: entry for entry in mapping["entries"]}

    assert entries["button.left.hold"]["action"] == "voice.command.start"
    assert entries["button.left.release_after_hold"]["action"] == "voice.command.stop"
    assert entries["button.right.hold"]["action"] == "voice.hold.start"
    assert entries["button.right.release_after_hold"]["action"] == "voice.hold.stop"
    assert entries["button.both.hold"]["action"] == "device.go_home"
    assert entries["button.both.hold"]["locked"] is True


def test_default_scroll_direction_is_inverted_on_macos(tmp_path):
    with patch("ble_stt.mapping.sys.platform", "darwin"):
        mapping = read_mapping(config_at(tmp_path))
    entries = {entry["event"]: entry for entry in mapping["entries"]}

    assert entries["touch.scroll_delta"]["action"] == "hid.mouse.wheel"
    assert entries["touch.scroll_delta"]["param1"] == 1


def test_default_scroll_direction_is_normal_off_macos(tmp_path):
    with patch("ble_stt.mapping.sys.platform", "win32"):
        mapping = read_mapping(config_at(tmp_path))
    entries = {entry["event"]: entry for entry in mapping["entries"]}

    assert entries["touch.scroll_delta"]["action"] == "hid.mouse.wheel"
    assert entries["touch.scroll_delta"]["param1"] == 0


def test_save_mapping_preserves_locked_home(tmp_path):
    mapping = save_mapping(
        [
            {
                "event": "button.both.hold",
                "action": "hid.keyboard.tap",
                "param0": 0x29,
                "param1": 0,
                "param2": 0,
            }
        ],
        config_at(tmp_path),
    )
    entries = {entry["event"]: entry for entry in mapping["entries"]}

    assert entries["button.both.hold"]["action"] == "device.go_home"
    assert entries["button.both.hold"]["locked"] is True


def test_mapping_binary_round_trip(tmp_path):
    mapping = save_mapping(
        [
            {
                "event": "touch.double_tap",
                "action": "hid.media.control",
                "param0": 0,
                "param1": 0,
                "param2": 0x00CD,
            }
        ],
        config_at(tmp_path),
    )

    decoded = decode_mapping(encode_mapping(mapping))
    entries = {entry["event"]: entry for entry in decoded["entries"]}

    assert entries["touch.double_tap"]["action"] == "hid.media.control"
    assert entries["touch.double_tap"]["param2"] == 0x00CD
    assert entries["button.both.hold"]["action"] == "device.go_home"


def test_parse_user_event_packet():
    packet = bytes([1, 15, 2, 1, 0xFF, 0x34, 0x12, 0])

    parsed = parse_user_event_packet(packet)

    assert parsed == {
        "event": "touch.scroll_delta",
        "action": "hid.mouse.wheel",
        "handled": True,
        "value": -1,
        "sequence": 0x1234,
    }


def test_parse_user_event_packet_reports_command_action():
    packet = bytes([1, 2, 13, 1, 0, 0x35, 0x12, 0])

    parsed = parse_user_event_packet(packet)

    assert parsed["event"] == "button.left.hold"
    assert parsed["action"] == "voice.command.start"
