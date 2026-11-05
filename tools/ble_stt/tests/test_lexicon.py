import unittest

from ble_stt.lexicon import (
    conservative_lexicon_correction,
    contextual_prompt_terms,
    merge_prompt_terms,
    standard_terms,
)


class LexiconTests(unittest.TestCase):
    def test_standard_terms_load_selected_packs(self):
        values = standard_terms(("computing",))

        self.assertIn("Bluetooth", values)
        self.assertIn("固件", values)
        self.assertNotIn("M5StopWatch", values)

    def test_personal_terms_are_prioritized_and_deduplicated(self):
        values = merge_prompt_terms(("自定义词", "bluetooth"), ("computing",), limit=3)

        self.assertEqual(values[0], "自定义词")
        self.assertEqual(values[1], "bluetooth")
        self.assertEqual(len(values), 3)

    def test_standard_terms_cover_common_correction_targets(self):
        values = standard_terms(("general", "computing"))

        for term in ("桌面", "窗口", "仓库", "驱动", "连接", "校验", "终端"):
            with self.subTest(term=term):
                self.assertIn(term, values)

    def test_contextual_terms_surface_matching_product_phrase(self):
        values = contextual_prompt_terms(
            "代码已经推送到远端花园。",
            ("远端仓库", "蓝牙广播", "缓存目录"),
        )

        self.assertEqual(values, ("远端仓库",))

    def test_contextual_terms_do_not_force_superstring_into_clean_text(self):
        values = contextual_prompt_terms(
            "这家餐厅的服务和味道都不错。",
            ("服务", "后台服务", "重启服务", "安装"),
        )

        self.assertEqual(values, ("服务",))

    def test_conservative_phrase_correction_repairs_one_character_error(self):
        value = conservative_lexicon_correction(
            "npm run build 执形失败。",
            ("npm run build 执行失败", "桌面应用"),
        )

        self.assertEqual(value, "npm run build 执行失败。")

    def test_conservative_phrase_correction_removes_anchored_repetition(self):
        value = conservative_lexicon_correction(
            "请在 GitHub 上创建一个仓库库。",
            ("GitHub 上创建一个仓库",),
        )

        self.assertEqual(value, "请在 GitHub 上创建一个仓库。")

    def test_conservative_phrase_correction_leaves_unrelated_clean_text_alone(self):
        value = conservative_lexicon_correction(
            "我刚才把钥匙放在桌子上了。",
            ("桌面", "当前桌面应用"),
        )

        self.assertEqual(value, "我刚才把钥匙放在桌子上了。")


if __name__ == "__main__":
    unittest.main()
