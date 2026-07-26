from __future__ import annotations

import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from .config import UserConfig
from .mapping import ACTION_BY_ID, PROTOCOL_VERSION, encode_action_packet, mapping_payload

CONFIG_KEY = "command_mapping"
MAX_COMMANDS = 24
MATCH_THRESHOLD = 0.82
MATCH_MARGIN = 0.08


@dataclass(frozen=True)
class CommandMatch:
    transcript: str
    normalized: str
    matched: bool
    score: float
    command: dict[str, Any] | None = None
    reason: str = "no_match"


FILLER_RE = re.compile(r"(请|帮我|帮忙|一下|一下子|那个|就是|吧|嘛|呢|啊|呀|嗯|呃)")
PUNCT_RE = re.compile(r"[\s\.,!?;:'\"`~，。！？；：、（）()\[\]【】<>《》]+")


def default_commands() -> list[dict[str, Any]]:
    return [
        {
            "id": "clear-input",
            "phrase": "清空",
            "aliases": ["清除", "清空输入", "清除输入"],
            "enabled": True,
            "action": "hid.keyboard.tap",
            "param0": 0x06,
            "param1": 0x01,
            "param2": 0,
            "flags": 0,
        }
    ]


def normalize_command_text(value: str) -> str:
    text = FILLER_RE.sub("", str(value).lower())
    return PUNCT_RE.sub("", text)


def _clean_aliases(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    aliases: list[str] = []
    seen: set[str] = set()
    for item in value:
        alias = str(item).strip()
        key = normalize_command_text(alias)
        if alias and key and key not in seen:
            aliases.append(alias)
            seen.add(key)
    return aliases[:8]


def clean_command(value: dict[str, Any], index: int = 0) -> dict[str, Any]:
    phrase = str(value.get("phrase", "")).strip()
    if not phrase:
        raise ValueError("command phrase is required")
    action = str(value.get("action", "none"))
    if action not in ACTION_BY_ID:
        raise ValueError(f"unsupported command action: {action}")
    param0 = int(value.get("param0", 0))
    param1 = int(value.get("param1", 0))
    param2 = int(value.get("param2", 0))
    flags = int(value.get("flags", 0))
    if not 0 <= param0 <= 255 or not 0 <= param1 <= 255:
        raise ValueError(f"command parameters out of byte range for {phrase}")
    if not -32768 <= param2 <= 32767 or not 0 <= flags <= 0xFFFF:
        raise ValueError(f"command parameters out of range for {phrase}")
    return {
        "id": str(value.get("id") or f"command-{index + 1}"),
        "phrase": phrase,
        "aliases": _clean_aliases(value.get("aliases")),
        "enabled": bool(value.get("enabled", True)),
        "action": action,
        "param0": param0,
        "param1": param1,
        "param2": param2,
        "flags": flags,
    }


def normalize_commands(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries[:MAX_COMMANDS]):
        item = clean_command(entry, index)
        key = normalize_command_text(item["phrase"])
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(item)
    if not cleaned:
        return [clean_command(default_commands()[0])]
    return cleaned


def read_commands(config: UserConfig | None = None) -> dict[str, Any]:
    config = config or UserConfig()
    raw = config.get(CONFIG_KEY)
    if isinstance(raw, dict) and isinstance(raw.get("entries"), list):
        try:
            entries = normalize_commands(raw["entries"])
            revision = int(raw.get("revision", 1))
        except (TypeError, ValueError):
            entries = default_commands()
            revision = 1
    else:
        entries = default_commands()
        revision = 1
    return {
        "schema": PROTOCOL_VERSION,
        "revision": revision,
        "updated_at": raw.get("updated_at") if isinstance(raw, dict) else None,
        "entries": entries,
    }


def save_commands(entries: list[dict[str, Any]], config: UserConfig | None = None) -> dict[str, Any]:
    config = config or UserConfig()
    current = read_commands(config)
    value = {
        "schema": PROTOCOL_VERSION,
        "revision": int(current.get("revision", 1)) + 1,
        "updated_at": time.time(),
        "entries": normalize_commands(entries),
    }
    config.set(CONFIG_KEY, value)
    return value


def reset_commands(config: UserConfig | None = None) -> dict[str, Any]:
    return save_commands(default_commands(), config)


def command_payload(config: UserConfig | None = None) -> dict[str, Any]:
    payload = mapping_payload(config)
    return {
        "schema": PROTOCOL_VERSION,
        "commands": read_commands(config),
        "actions": payload["actions"],
        "keyOptions": payload["keyOptions"],
        "modifierOptions": payload["modifierOptions"],
        "mouseButtons": payload["mouseButtons"],
        "mediaControls": payload["mediaControls"],
    }


def _candidate_phrases(command: dict[str, Any]) -> list[str]:
    return [str(command.get("phrase", "")), *[str(value) for value in command.get("aliases", [])]]


def match_command(transcript: str, commands: list[dict[str, Any]]) -> CommandMatch:
    normalized = normalize_command_text(transcript)
    if not normalized:
        return CommandMatch(transcript, normalized, False, 0.0, reason="empty")

    scored: list[tuple[float, dict[str, Any]]] = []
    for command in commands:
        if not command.get("enabled", True):
            continue
        best = 0.0
        for phrase in _candidate_phrases(command):
            candidate = normalize_command_text(phrase)
            if not candidate:
                continue
            if normalized == candidate:
                best = 1.0
                break
            if candidate in normalized and len(normalized) <= len(candidate) + 4:
                best = max(best, 0.94)
                continue
            best = max(best, SequenceMatcher(None, normalized, candidate).ratio())
        if best > 0:
            scored.append((best, command))

    if not scored:
        return CommandMatch(transcript, normalized, False, 0.0)
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_command = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if best_score >= MATCH_THRESHOLD and best_score - runner_up >= MATCH_MARGIN:
        return CommandMatch(transcript, normalized, True, round(best_score, 4), best_command, "matched")
    reason = "ambiguous" if runner_up else "low_confidence"
    return CommandMatch(transcript, normalized, False, round(best_score, 4), best_command, reason)


def encode_command_action(command: dict[str, Any]) -> bytes:
    return encode_action_packet(command)
