from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .config import UserConfig


CORRECTION_CONFIG_KEY = "correction"
TYPING_CONFIG_KEY = "typing"
DEFAULT_CORRECTION_MODEL = "lite"
DEFAULT_CORRECTION_REPOSITORY = "ggml-org/Qwen3.5-0.8B-GGUF"
DEFAULT_CORRECTION_FILE = "Qwen3.5-0.8B-Q4_0.gguf"
CORRECTION_MODEL_FILES = {
    "lite": (DEFAULT_CORRECTION_REPOSITORY, DEFAULT_CORRECTION_FILE),
    "balanced": (
        "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        "qwen2.5-1.5b-instruct-q3_k_m.gguf",
    ),
}
MAX_GLOSSARY_TERMS = 128
MAX_GLOSSARY_TERM_LENGTH = 80


@dataclass(frozen=True)
class CorrectionPreferences:
    enabled: bool = False
    mode: str = "conservative"
    languages: tuple[str, ...] = ("zh-CN", "en")
    model: str = DEFAULT_CORRECTION_MODEL
    repository: str = DEFAULT_CORRECTION_REPOSITORY
    filename: str = DEFAULT_CORRECTION_FILE
    glossary: tuple[str, ...] = ()
    standard_lexicon_enabled: bool = True
    lexicon_packs: tuple[str, ...] = ("general", "computing", "product")
    timeout_seconds: float = 2.5


@dataclass(frozen=True)
class TypingPreferences:
    enabled: bool = True
    characters_per_second: int = 40
    auto_accelerate: bool = True
    max_characters_per_second: int = 120


@dataclass(frozen=True)
class VoicePreferences:
    correction: CorrectionPreferences
    typing: TypingPreferences

    def to_dict(self) -> dict[str, Any]:
        correction = asdict(self.correction)
        correction["languages"] = list(self.correction.languages)
        correction["glossary"] = list(self.correction.glossary)
        correction["lexicon_packs"] = list(self.correction.lexicon_packs)
        return {
            "correction": correction,
            "typing": asdict(self.typing),
        }


def _dictionary(config: UserConfig, key: str) -> dict[str, Any]:
    value = config.get(key, {})
    return dict(value) if isinstance(value, dict) else {}


def _glossary(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        values = value.replace("\r", "\n").split("\n")
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        values = ()
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        term = str(raw).strip()
        if not term or len(term) > MAX_GLOSSARY_TERM_LENGTH or term.casefold() in seen:
            continue
        seen.add(term.casefold())
        result.append(term)
        if len(result) >= MAX_GLOSSARY_TERMS:
            break
    return tuple(result)


def _correction_model(value: Any, repository: Any = None, filename: Any = None) -> str:
    model = str(value or "").strip()
    if model in CORRECTION_MODEL_FILES:
        return model
    pair = (str(repository or "").strip(), str(filename or "").strip())
    for model_id, configured_pair in CORRECTION_MODEL_FILES.items():
        if pair == configured_pair:
            return model_id
    return DEFAULT_CORRECTION_MODEL


def read_voice_preferences(config: UserConfig | None = None) -> VoicePreferences:
    config = config or UserConfig()
    correction = _dictionary(config, CORRECTION_CONFIG_KEY)
    typing = _dictionary(config, TYPING_CONFIG_KEY)

    raw_languages = correction.get("languages", ("zh-CN", "en"))
    if not isinstance(raw_languages, (list, tuple)):
        raw_languages = ("zh-CN", "en")
    languages = tuple(value for value in (str(item).strip() for item in raw_languages) if value)
    if not languages:
        languages = ("zh-CN", "en")

    raw_packs = correction.get("lexicon_packs", ("general", "computing", "product"))
    if not isinstance(raw_packs, (list, tuple)):
        raw_packs = ("general", "computing", "product")
    allowed_packs = {"general", "computing", "product"}
    lexicon_packs = tuple(
        value for value in (str(item).strip() for item in raw_packs) if value in allowed_packs
    )

    mode = str(correction.get("mode", "conservative"))
    if mode != "conservative":
        mode = "conservative"
    timeout = float(correction.get("timeout_seconds", 2.5))
    timeout = max(0.5, min(10.0, timeout))
    correction_model = _correction_model(
        correction.get("model"),
        correction.get("repository"),
        correction.get("filename"),
    )
    repository, filename = CORRECTION_MODEL_FILES[correction_model]

    cps = int(typing.get("characters_per_second", 40))
    cps = max(10, min(100, cps))
    max_cps = int(typing.get("max_characters_per_second", 120))
    max_cps = max(cps, min(240, max_cps))

    return VoicePreferences(
        correction=CorrectionPreferences(
            enabled=bool(correction.get("enabled", False)),
            mode=mode,
            languages=languages,
            model=correction_model,
            repository=repository,
            filename=filename,
            glossary=_glossary(correction.get("glossary", ())),
            standard_lexicon_enabled=bool(correction.get("standard_lexicon_enabled", True)),
            lexicon_packs=lexicon_packs,
            timeout_seconds=timeout,
        ),
        typing=TypingPreferences(
            enabled=bool(typing.get("enabled", True)),
            characters_per_second=cps,
            auto_accelerate=bool(typing.get("auto_accelerate", True)),
            max_characters_per_second=max_cps,
        ),
    )


def save_voice_preferences(payload: dict[str, Any], config: UserConfig | None = None) -> VoicePreferences:
    config = config or UserConfig()
    if not isinstance(payload, dict):
        raise ValueError("settings payload must be an object")

    current = read_voice_preferences(config).to_dict()
    correction_update = payload.get("correction")
    typing_update = payload.get("typing")
    if correction_update is not None:
        if not isinstance(correction_update, dict):
            raise ValueError("correction settings must be an object")
        current["correction"].update(correction_update)
    if typing_update is not None:
        if not isinstance(typing_update, dict):
            raise ValueError("typing settings must be an object")
        current["typing"].update(typing_update)

    correction_model = _correction_model(
        current["correction"].get("model"),
        current["correction"].get("repository"),
        current["correction"].get("filename"),
    )
    repository, filename = CORRECTION_MODEL_FILES[correction_model]
    normalized = VoicePreferences(
        correction=CorrectionPreferences(
            enabled=bool(current["correction"].get("enabled", False)),
            mode="conservative",
            languages=("zh-CN", "en"),
            model=correction_model,
            repository=repository,
            filename=filename,
            glossary=_glossary(current["correction"].get("glossary", ())),
            standard_lexicon_enabled=bool(
                current["correction"].get("standard_lexicon_enabled", True)
            ),
            lexicon_packs=tuple(
                value
                for value in current["correction"].get(
                    "lexicon_packs", ("general", "computing", "product")
                )
                if value in {"general", "computing", "product"}
            ),
            timeout_seconds=max(
                0.5,
                min(10.0, float(current["correction"].get("timeout_seconds", 2.5))),
            ),
        ),
        typing=TypingPreferences(
            enabled=bool(current["typing"].get("enabled", True)),
            characters_per_second=max(
                10,
                min(100, int(current["typing"].get("characters_per_second", 40))),
            ),
            auto_accelerate=bool(current["typing"].get("auto_accelerate", True)),
            max_characters_per_second=max(
                max(10, min(100, int(current["typing"].get("characters_per_second", 40)))),
                min(240, int(current["typing"].get("max_characters_per_second", 120))),
            ),
        ),
    )
    config.set(CORRECTION_CONFIG_KEY, normalized.to_dict()["correction"])
    config.set(TYPING_CONFIG_KEY, normalized.to_dict()["typing"])
    return read_voice_preferences(config)
