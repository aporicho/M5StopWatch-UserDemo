import json
import unittest
from unittest.mock import Mock, patch

from ble_stt.correction import (
    ConservativeCorrector,
    graphemes,
    parse_model_candidate,
    restore_terminal_punctuation,
    validate_preferred_term_changes,
    validate_conservative_candidate,
)
from ble_stt.correction_models import CorrectionModelStatus
from ble_stt.llama_runtime import LlamaServerClient, LlamaServerError
from ble_stt.preferences import CorrectionPreferences


READY_MODEL = CorrectionModelStatus(
    model="lite",
    repository="ggml-org/Qwen3.5-0.8B-GGUF",
    filename="Qwen3.5-0.8B-Q4_0.gguf",
    display_name="Qwen3.5-0.8B Q4",
    state="ready",
    installed=True,
    disk_bytes=1,
    expected_disk_bytes=1,
    stale_disk_bytes=0,
    path="/tmp/model.gguf",
    revision="abc",
    sha256="123",
    runtime_available=True,
    runtime_path="/tmp/llama-server",
    message="ready",
)


class ConservativeCorrectionTests(unittest.TestCase):
    def test_graphemes_keep_combining_character_together(self):
        self.assertEqual(graphemes("e\u0301中"), ["e\u0301", "中"])

    def test_candidate_must_preserve_numbers_english_and_glossary(self):
        raw = "用 M5StopWatch 跑 GPT 4，准确率 12.5%"
        accepted, reason = validate_conservative_candidate(
            raw,
            "用 M5StopWatch 跑 GPT 5，准确率 12.5%",
            ("M5StopWatch",),
        )
        self.assertFalse(accepted)
        self.assertEqual(reason, "protected_tokens")

    def test_small_chinese_correction_is_allowed(self):
        accepted, reason = validate_conservative_candidate("今天天汽很好", "今天天气很好")
        self.assertTrue(accepted)
        self.assertEqual(reason, "accepted")

    def test_terminal_punctuation_is_preserved(self):
        self.assertEqual(
            restore_terminal_punctuation("我把文件保存好了。", "我把文件保存好了"),
            "我把文件保存好了。",
        )

    def test_model_cannot_remove_an_exact_preferred_term(self):
        accepted, reason = validate_preferred_term_changes(
            "点击刷新可以重新扫描设备。",
            "点击刷新可以重新连接设备。",
            ("扫描设备", "重新连接"),
        )

        self.assertFalse(accepted)
        self.assertEqual(reason, "removed_preferred_term")

    def test_model_cannot_expand_an_existing_term_without_replacing_text(self):
        accepted, reason = validate_preferred_term_changes(
            "手表会继续广播。",
            "手表会继续蓝牙广播。",
            ("广播", "蓝牙广播"),
        )

        self.assertFalse(accepted)
        self.assertEqual(reason, "expanded_preferred_term")

    def test_large_rewrite_is_rejected(self):
        accepted, reason = validate_conservative_candidate("今天开会讨论版本", "明天取消会议并重新安排所有工作")
        self.assertFalse(accepted)
        self.assertEqual(reason, "edit_distance")

    def test_new_script_is_rejected(self):
        accepted, reason = validate_conservative_candidate("今天开会", "今天ミーティング")
        self.assertFalse(accepted)
        self.assertEqual(reason, "unexpected_script")

    def test_corrector_accepts_json_and_reports_change(self):
        client = Mock()
        client.complete.return_value = json.dumps({"text": "今天天气很好"}, ensure_ascii=False)
        preferences = CorrectionPreferences(enabled=True)
        with patch("ble_stt.correction.correction_model_status", return_value=READY_MODEL):
            result = ConservativeCorrector(client).correct("今天天汽很好", preferences)

        self.assertEqual(result.state, "corrected")
        self.assertEqual(result.text, "今天天气很好")
        self.assertTrue(result.changed)

    def test_invalid_model_output_falls_back_to_raw(self):
        client = Mock()
        client.complete.return_value = "not-json"
        with patch("ble_stt.correction.correction_model_status", return_value=READY_MODEL):
            result = ConservativeCorrector(client).correct("原始文本", CorrectionPreferences(enabled=True))

        self.assertEqual(result.state, "fallback")
        self.assertEqual(result.text, "原始文本")

    def test_markdown_fenced_model_json_is_accepted(self):
        self.assertEqual(
            parse_model_candidate('```json\n{"text":"纠正结果"}\n```'),
            "纠正结果",
        )

    def test_model_response_prose_is_not_treated_as_corrected_text(self):
        with self.assertRaises(json.JSONDecodeError):
            parse_model_candidate("纠正结果")

    def test_llama_request_disables_thinking_and_constrains_json(self):
        client = LlamaServerClient(READY_MODEL)
        response = {"choices": [{"message": {"content": '{"text":"结果"}'}}]}
        with patch.object(client, "start"):
            with patch.object(client, "_request", return_value=response) as request:
                value = client.complete("system", "user")
        client.close()

        payload = request.call_args.kwargs["payload"]
        self.assertEqual(value, '{"text":"结果"}')
        self.assertEqual(payload["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(payload["response_format"]["type"], "json_schema")

    def test_llama_request_failure_resets_private_server(self):
        client = LlamaServerClient(READY_MODEL)
        with patch.object(client, "start"):
            with patch.object(client, "_request", side_effect=LlamaServerError("HTTP 503")):
                with patch.object(client, "close") as close:
                    with self.assertRaises(LlamaServerError):
                        client.complete("system", "user")

        close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
