from __future__ import annotations

from ble_stt.commands import (
    command_payload,
    encode_command_action,
    match_command,
    read_commands,
    save_commands,
)
from ble_stt.config import UserConfig


def config_at(tmp_path):
    return UserConfig(tmp_path / "ble-stt.json")


def test_default_command_clears_input(tmp_path):
    commands = read_commands(config_at(tmp_path))
    entry = commands["entries"][0]

    assert entry["phrase"] == "清空"
    assert entry["action"] == "hid.keyboard.tap"
    assert entry["param0"] == 0x06
    assert entry["param1"] == 0x01


def test_command_match_accepts_polite_short_phrase(tmp_path):
    commands = read_commands(config_at(tmp_path))["entries"]

    result = match_command("请清空一下", commands)

    assert result.matched is True
    assert result.command is not None
    assert result.command["phrase"] == "清空"


def test_command_match_rejects_unrelated_text(tmp_path):
    commands = read_commands(config_at(tmp_path))["entries"]

    result = match_command("今天天气不错", commands)

    assert result.matched is False


def test_command_match_rejects_ambiguous_result(tmp_path):
    commands = save_commands(
        [
            {"id": "a", "phrase": "清空", "action": "none"},
            {"id": "b", "phrase": "清除", "action": "none"},
        ],
        config_at(tmp_path),
    )["entries"]

    result = match_command("清", commands)

    assert result.matched is False
    assert result.reason in {"ambiguous", "low_confidence"}


def test_command_action_packet_encodes_action_without_event(tmp_path):
    command = read_commands(config_at(tmp_path))["entries"][0]

    assert encode_command_action(command) == bytes([1, 1, 0x06, 0x01, 0, 0, 0, 0])


def test_command_payload_reuses_mapping_options(tmp_path):
    payload = command_payload(config_at(tmp_path))

    assert payload["commands"]["entries"][0]["phrase"] == "清空"
    assert any(action["id"] == "hid.keyboard.tap" for action in payload["actions"])
