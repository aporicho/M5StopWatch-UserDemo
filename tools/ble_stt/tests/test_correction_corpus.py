import json
import os
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from ble_stt.correction import (
    SYSTEM_PROMPT,
    ConservativeCorrector,
    normalize_transcript,
    protected_tokens,
    validate_conservative_candidate,
)
from ble_stt.correction_models import CorrectionModelStatus
from ble_stt.preferences import CorrectionPreferences


CORPUS_PATH = Path(__file__).parent / "fixtures" / "correction_cases.jsonl"
EXPECTED_CATEGORY_COUNTS = {
    "semantic_outlier": 50,
    "homophone_or_near_sound": 35,
    "omitted_character": 30,
    "repeated_character": 25,
    "mixed_english": 25,
    "protected_values": 30,
    "clean_unchanged": 40,
    "punctuation_and_spacing": 15,
    "prompt_injection": 10,
    "glossary_protection": 10,
}
READY_MODEL = CorrectionModelStatus(
    repository="Qwen/Qwen3-4B-GGUF",
    filename="Qwen3-4B-Q4_K_M.gguf",
    state="ready",
    installed=True,
    disk_bytes=1,
    path="/tmp/model.gguf",
    revision="test",
    sha256="test",
    runtime_available=True,
    runtime_path="/tmp/llama-server",
    message="ready",
)


def load_cases():
    with CORPUS_PATH.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


class ExpectedAnswerClient:
    def __init__(self, expected_by_input):
        self.expected_by_input = expected_by_input

    def complete(self, _system_prompt, user_prompt, **_kwargs):
        transcript = json.loads(user_prompt)["transcript"]
        return json.dumps({"text": self.expected_by_input[transcript]}, ensure_ascii=False)


class CorrectionCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = load_cases()

    def test_corpus_contains_270_unique_cases_across_required_categories(self):
        self.assertEqual(len(self.cases), 270)
        self.assertEqual(len({case["id"] for case in self.cases}), len(self.cases))
        self.assertEqual(Counter(case["category"] for case in self.cases), EXPECTED_CATEGORY_COUNTS)

    def test_every_case_has_a_valid_explicit_expected_answer(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                self.assertIsInstance(case["input"], str)
                self.assertTrue(case["input"])
                self.assertIsInstance(case["expected"], str)
                self.assertTrue(case["expected"])
                glossary = tuple(case.get("glossary", ()))
                accepted, reason = validate_conservative_candidate(
                    case["input"], case["expected"], glossary
                )
                self.assertTrue(accepted, reason)
                self.assertEqual(
                    protected_tokens(case["input"], glossary),
                    protected_tokens(case["expected"], glossary),
                )

    def test_all_270_expected_answers_pass_the_complete_correction_pipeline(self):
        expected_by_input = {
            normalize_transcript(case["input"]): normalize_transcript(case["expected"])
            for case in self.cases
        }
        self.assertEqual(len(expected_by_input), len(self.cases))
        corrector = ConservativeCorrector(ExpectedAnswerClient(expected_by_input))
        with patch("ble_stt.correction.correction_model_status", return_value=READY_MODEL):
            for case in self.cases:
                with self.subTest(case=case["id"]):
                    result = corrector.correct(
                        case["input"],
                        CorrectionPreferences(
                            enabled=True,
                            glossary=tuple(case.get("glossary", ())),
                        ),
                    )
                    self.assertEqual(result.text, normalize_transcript(case["expected"]))
                    self.assertNotEqual(result.state, "fallback")

    def test_prompt_explicitly_covers_non_phonetic_semantic_outliers(self):
        self.assertIn("发音与含义都完全无关", SYSTEM_PROMPT)
        self.assertIn("保存到桌布", SYSTEM_PROMPT)
        self.assertIn("语义离群词", SYSTEM_PROMPT)
        self.assertIn("无法唯一确定时逐字保持原文", SYSTEM_PROMPT)

    @unittest.skipUnless(
        os.environ.get("BLE_STT_RUN_CORRECTION_EVAL") == "1",
        "set BLE_STT_RUN_CORRECTION_EVAL=1 to run the optional 270-case model evaluation",
    )
    def test_installed_model_meets_quality_floor(self):
        corrector = ConservativeCorrector()
        passed = 0
        preserved_passed = 0
        preserved_total = 0
        try:
            for case in self.cases:
                expected = normalize_transcript(case["expected"])
                raw = normalize_transcript(case["input"])
                result = corrector.correct(
                    raw,
                    CorrectionPreferences(
                        enabled=True,
                        glossary=tuple(case.get("glossary", ())),
                        timeout_seconds=10.0,
                    ),
                )
                passed += result.text == expected
                if expected == raw:
                    preserved_total += 1
                    preserved_passed += result.text == expected
        finally:
            if corrector.client is not None:
                corrector.client.close()
        self.assertGreaterEqual(passed / len(self.cases), 0.75)
        self.assertGreaterEqual(preserved_passed / preserved_total, 0.95)


if __name__ == "__main__":
    unittest.main()
