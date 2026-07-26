from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Any

from .config import UserConfig
from .protocol import PROTOCOL_VERSION, ProtocolError

CONFIG_KEY = "event_mapping"
WIRE_MAGIC = b"M5"
WIRE_VERSION = 1
WIRE_HEADER_SIZE = 4
WIRE_RECORD_SIZE = 8
MAX_RECORDS = 24


@dataclass(frozen=True)
class EventDefinition:
    id: str
    code: int
    label: str
    locked: bool = False


@dataclass(frozen=True)
class ActionDefinition:
    id: str
    code: int
    label: str


EVENTS = (
    EventDefinition("button.left.tap", 1, "Left tap"),
    EventDefinition("button.left.hold", 2, "Left hold"),
    EventDefinition("button.left.release_after_hold", 3, "Left hold release"),
    EventDefinition("button.right.tap", 4, "Right tap"),
    EventDefinition("button.right.hold", 5, "Right hold"),
    EventDefinition("button.right.release_after_hold", 6, "Right hold release"),
    EventDefinition("touch.tap", 7, "Touch tap"),
    EventDefinition("touch.double_tap", 8, "Touch double tap"),
    EventDefinition("touch.triple_tap", 9, "Touch triple tap"),
    EventDefinition("touch.hold", 10, "Touch hold"),
    EventDefinition("touch.swipe_up", 11, "Swipe up"),
    EventDefinition("touch.swipe_down", 12, "Swipe down"),
    EventDefinition("touch.swipe_left", 13, "Swipe left"),
    EventDefinition("touch.swipe_right", 14, "Swipe right"),
    EventDefinition("touch.scroll_delta", 15, "Touch scroll"),
    EventDefinition("button.both.hold", 16, "Both buttons hold", locked=True),
)

ACTIONS = (
    ActionDefinition("none", 0, "None"),
    ActionDefinition("hid.keyboard.tap", 1, "Key / shortcut"),
    ActionDefinition("hid.mouse.wheel", 2, "Mouse wheel"),
    ActionDefinition("hid.mouse.click", 3, "Mouse click"),
    ActionDefinition("hid.media.control", 4, "Media key"),
    ActionDefinition("voice.hold.start", 5, "Voice start"),
    ActionDefinition("voice.hold.stop", 6, "Voice stop"),
    ActionDefinition("voice.toggle", 7, "Voice toggle"),
    ActionDefinition("device.pair_new_computer", 8, "Pair new computer"),
    ActionDefinition("device.show_controls", 9, "Show controls"),
    ActionDefinition("device.hide_controls", 10, "Hide controls"),
    ActionDefinition("device.toggle_controls", 11, "Toggle controls"),
    ActionDefinition("device.go_home", 12, "Go home"),
    ActionDefinition("voice.command.start", 13, "Command start"),
    ActionDefinition("voice.command.stop", 14, "Command stop"),
)

KEY_OPTIONS = (
    ("Escape", 0x29),
    ("Enter", 0x28),
    ("Tab", 0x2B),
    ("Space", 0x2C),
    ("Backspace", 0x2A),
    ("Delete", 0x4C),
    ("Arrow right", 0x4F),
    ("Arrow left", 0x50),
    ("Arrow down", 0x51),
    ("Arrow up", 0x52),
    ("Home", 0x4A),
    ("End", 0x4D),
    ("Page up", 0x4B),
    ("Page down", 0x4E),
    ("F1", 0x3A),
    ("F2", 0x3B),
    ("F3", 0x3C),
    ("F4", 0x3D),
    ("F5", 0x3E),
    ("F6", 0x3F),
    ("F7", 0x40),
    ("F8", 0x41),
    ("F9", 0x42),
    ("F10", 0x43),
    ("F11", 0x44),
    ("F12", 0x45),
    ("A", 0x04),
    ("B", 0x05),
    ("C", 0x06),
    ("D", 0x07),
    ("E", 0x08),
    ("F", 0x09),
    ("G", 0x0A),
    ("H", 0x0B),
    ("I", 0x0C),
    ("J", 0x0D),
    ("K", 0x0E),
    ("L", 0x0F),
    ("M", 0x10),
    ("N", 0x11),
    ("O", 0x12),
    ("P", 0x13),
    ("Q", 0x14),
    ("R", 0x15),
    ("S", 0x16),
    ("T", 0x17),
    ("U", 0x18),
    ("V", 0x19),
    ("W", 0x1A),
    ("X", 0x1B),
    ("Y", 0x1C),
    ("Z", 0x1D),
)

MODIFIER_OPTIONS = (
    ("None", 0x00),
    ("Ctrl", 0x01),
    ("Shift", 0x02),
    ("Alt", 0x04),
    ("Cmd / Win", 0x08),
    ("Ctrl+Shift", 0x03),
    ("Ctrl+Alt", 0x05),
    ("Cmd+Shift", 0x0A),
    ("Cmd+Alt", 0x0C),
)

MOUSE_BUTTONS = (
    ("Left click", 0x01),
    ("Right click", 0x02),
    ("Middle click", 0x04),
)

MEDIA_CONTROLS = (
    ("Play / pause", 0x00CD),
    ("Next track", 0x00B5),
    ("Previous track", 0x00B6),
    ("Stop", 0x00B7),
    ("Mute", 0x00E2),
    ("Volume up", 0x00E9),
    ("Volume down", 0x00EA),
)

EVENT_BY_ID = {item.id: item for item in EVENTS}
EVENT_BY_CODE = {item.code: item for item in EVENTS}
ACTION_BY_ID = {item.id: item for item in ACTIONS}
ACTION_BY_CODE = {item.code: item for item in ACTIONS}


def default_scroll_direction() -> int:
    return 1 if sys.platform == "darwin" else 0


def default_entries() -> list[dict[str, Any]]:
    return [
        {"event": "button.left.tap", "action": "hid.keyboard.tap", "param0": 0x29, "param1": 0, "param2": 0},
        {"event": "button.left.hold", "action": "voice.command.start", "param0": 0, "param1": 0, "param2": 0},
        {"event": "button.left.release_after_hold", "action": "voice.command.stop", "param0": 0, "param1": 0, "param2": 0},
        {"event": "button.right.tap", "action": "hid.keyboard.tap", "param0": 0x28, "param1": 0, "param2": 0},
        {"event": "button.right.hold", "action": "voice.hold.start", "param0": 0, "param1": 0, "param2": 0},
        {"event": "button.right.release_after_hold", "action": "voice.hold.stop", "param0": 0, "param1": 0, "param2": 0},
        {
            "event": "touch.scroll_delta",
            "action": "hid.mouse.wheel",
            "param0": 1,
            "param1": default_scroll_direction(),
            "param2": 0,
        },
        {"event": "touch.triple_tap", "action": "device.toggle_controls", "param0": 0, "param1": 0, "param2": 0},
        {"event": "button.both.hold", "action": "device.go_home", "param0": 0, "param1": 0, "param2": 0, "locked": True},
    ]


def _clean_entry(value: dict[str, Any]) -> dict[str, Any]:
    event = str(value.get("event", ""))
    action = str(value.get("action", "none"))
    if event not in EVENT_BY_ID:
        raise ValueError(f"unsupported event: {event}")
    if action not in ACTION_BY_ID:
        raise ValueError(f"unsupported action: {action}")
    event_def = EVENT_BY_ID[event]
    if event_def.locked:
        action = "device.go_home"
    param0 = int(value.get("param0", 0))
    param1 = int(value.get("param1", 0))
    param2 = int(value.get("param2", 0))
    flags = int(value.get("flags", 0))
    if not 0 <= param0 <= 255 or not 0 <= param1 <= 255:
        raise ValueError(f"mapping parameters out of byte range for {event}")
    if not -32768 <= param2 <= 32767 or not 0 <= flags <= 0xFFFF:
        raise ValueError(f"mapping parameters out of range for {event}")
    if action == "hid.mouse.wheel" and param0 == 0:
        param0 = 1
    return {
        "event": event,
        "action": action,
        "param0": param0,
        "param1": param1,
        "param2": param2,
        "flags": flags,
        "locked": event_def.locked,
    }


def normalize_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned: dict[str, dict[str, Any]] = {}
    for entry in entries:
        item = _clean_entry(entry)
        cleaned[item["event"]] = item
    cleaned["button.both.hold"] = _clean_entry({"event": "button.both.hold", "action": "device.go_home"})
    return [cleaned[event.id] for event in EVENTS if event.id in cleaned]


def read_mapping(config: UserConfig | None = None) -> dict[str, Any]:
    config = config or UserConfig()
    raw = config.get(CONFIG_KEY)
    if isinstance(raw, dict) and isinstance(raw.get("entries"), list):
        try:
            entries = normalize_entries(raw["entries"])
            revision = int(raw.get("revision", 1))
        except (TypeError, ValueError):
            entries = default_entries()
            revision = 1
    else:
        entries = default_entries()
        revision = 1
    return {
        "schema": PROTOCOL_VERSION,
        "revision": revision,
        "updated_at": raw.get("updated_at") if isinstance(raw, dict) else None,
        "entries": entries,
    }


def save_mapping(entries: list[dict[str, Any]], config: UserConfig | None = None) -> dict[str, Any]:
    config = config or UserConfig()
    current = read_mapping(config)
    mapping = {
        "schema": PROTOCOL_VERSION,
        "revision": int(current.get("revision", 1)) + 1,
        "updated_at": time.time(),
        "entries": normalize_entries(entries),
    }
    config.set(CONFIG_KEY, mapping)
    return mapping


def reset_mapping(config: UserConfig | None = None) -> dict[str, Any]:
    return save_mapping(default_entries(), config)


def encode_mapping(mapping: dict[str, Any]) -> bytes:
    entries = normalize_entries(list(mapping.get("entries", [])))
    if len(entries) > MAX_RECORDS:
        raise ProtocolError(f"mapping has {len(entries)} records, max {MAX_RECORDS}")
    output = bytearray(WIRE_MAGIC + bytes((WIRE_VERSION, len(entries))))
    for entry in entries:
        event = EVENT_BY_ID[entry["event"]].code
        action = ACTION_BY_ID[entry["action"]].code
        param0 = int(entry.get("param0", 0))
        param1 = int(entry.get("param1", 0))
        param2 = int(entry.get("param2", 0))
        flags = int(entry.get("flags", 0))
        output.extend(
            (
                event,
                action,
                param0 & 0xFF,
                param1 & 0xFF,
                param2 & 0xFF,
                (param2 >> 8) & 0xFF,
                flags & 0xFF,
                (flags >> 8) & 0xFF,
            )
        )
    return bytes(output)


def encode_action_packet(entry: dict[str, Any]) -> bytes:
    cleaned = _clean_entry({"event": "button.left.tap", **entry})
    param2 = int(cleaned.get("param2", 0))
    flags = int(cleaned.get("flags", 0))
    return bytes(
        (
            WIRE_VERSION,
            ACTION_BY_ID[cleaned["action"]].code,
            int(cleaned.get("param0", 0)) & 0xFF,
            int(cleaned.get("param1", 0)) & 0xFF,
            param2 & 0xFF,
            (param2 >> 8) & 0xFF,
            flags & 0xFF,
            (flags >> 8) & 0xFF,
        )
    )


def decode_mapping(data: bytes) -> dict[str, Any]:
    if len(data) < WIRE_HEADER_SIZE or data[:2] != WIRE_MAGIC or data[2] != WIRE_VERSION:
        raise ProtocolError("invalid mapping packet header")
    count = data[3]
    expected = WIRE_HEADER_SIZE + count * WIRE_RECORD_SIZE
    if len(data) != expected or count > MAX_RECORDS:
        raise ProtocolError(f"mapping packet has {len(data)} bytes, expected {expected}")
    entries: list[dict[str, Any]] = []
    for index in range(count):
        offset = WIRE_HEADER_SIZE + index * WIRE_RECORD_SIZE
        event_code = data[offset]
        action_code = data[offset + 1]
        event = EVENT_BY_CODE.get(event_code)
        action = ACTION_BY_CODE.get(action_code)
        if event is None or action is None:
            raise ProtocolError(f"unknown mapping event/action {event_code}/{action_code}")
        param2 = int.from_bytes(data[offset + 4 : offset + 6], "little", signed=True)
        flags = int.from_bytes(data[offset + 6 : offset + 8], "little", signed=False)
        entries.append(
            _clean_entry(
                {
                    "event": event.id,
                    "action": action.id,
                    "param0": data[offset + 2],
                    "param1": data[offset + 3],
                    "param2": param2,
                    "flags": flags,
                }
            )
        )
    return {"schema": PROTOCOL_VERSION, "entries": normalize_entries(entries)}


def parse_user_event_packet(data: bytes) -> dict[str, Any]:
    if len(data) != 8 or data[0] != WIRE_VERSION:
        raise ProtocolError(f"user event packet has invalid shape: {len(data)} bytes")
    event = EVENT_BY_CODE.get(data[1])
    action = ACTION_BY_CODE.get(data[2])
    value = int.from_bytes(data[4:5], "little", signed=True)
    sequence = int.from_bytes(data[5:7], "little", signed=False)
    return {
        "event": event.id if event else f"unknown:{data[1]}",
        "action": action.id if action else f"unknown:{data[2]}",
        "handled": data[3] != 0,
        "value": value,
        "sequence": sequence,
    }


def mapping_payload(config: UserConfig | None = None) -> dict[str, Any]:
    mapping = read_mapping(config)
    return {
        "schema": PROTOCOL_VERSION,
        "mapping": mapping,
        "events": [definition.__dict__ for definition in EVENTS],
        "actions": [definition.__dict__ for definition in ACTIONS],
        "keyOptions": [{"label": label, "value": value} for label, value in KEY_OPTIONS],
        "modifierOptions": [{"label": label, "value": value} for label, value in MODIFIER_OPTIONS],
        "mouseButtons": [{"label": label, "value": value} for label, value in MOUSE_BUTTONS],
        "mediaControls": [{"label": label, "value": value} for label, value in MEDIA_CONTROLS],
    }
