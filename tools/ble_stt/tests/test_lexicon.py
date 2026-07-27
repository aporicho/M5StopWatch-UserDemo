import unittest

from ble_stt.lexicon import merge_prompt_terms, standard_terms


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


if __name__ == "__main__":
    unittest.main()
