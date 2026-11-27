import tempfile
import unittest
from pathlib import Path

import build_dictionary as tool


class StressDictionaryTests(unittest.TestCase):
    def test_valid_stress_and_yo_alias(self):
        self.assertIsNone(tool.validate_entry("творог", "твор+ог"))
        self.assertIsNone(tool.validate_entry("холеной", "хол+ёной"))

    def test_rejects_invalid_or_unneeded_rows(self):
        for word, marked in [
            ("два слова", "два сл+ова"),
            ("замок", "з+амок+"),
            ("замок", "зам+ик"),
            ("дом", "д+ом"),
            ("слово", "сл+ово extra"),
        ]:
            self.assertIsNotNone(tool.validate_entry(word, marked))

    def test_consensus_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "stress_candidates.txt"
            source.write_text(
                "# candidate list\n"
                "творог = твор+ог  # 5, v5: тв+орог\n"
                "молоко = мол+око  # 2, v5: молок+о\n"
                "корова = кор+ова  # no count\n",
                encoding="utf-8",
            )
            rows, rejected = tool.read_consensus_candidates(source, 3)
            self.assertEqual([row.word for row in rows], ["творог"])
            self.assertEqual(len(rejected), 2)

    def test_malformed_source_rows_are_reported_instead_of_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.txt"
            source.write_text(
                "# header\n"
                "замок = з+амок\n"
                "строка без разделителя\n"
                "молоко = мол+око лишний_текст\n",
                encoding="utf-8",
            )
            accepted, rejected = tool.read_source_list(source, "test-source")
            self.assertEqual([row.word for row in accepted], ["замок"])
            self.assertEqual(len(rejected), 2)
            self.assertIn("строка 3", rejected[0].reason)
            self.assertIn("строка 4", rejected[1].reason)
            self.assertIn("лишний_текст", rejected[1].note)

    def test_malformed_candidate_rows_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "stress_candidates.txt"
            source.write_text(
                "творог = твор+ог  # 5, v5: тв+орог\n"
                "битая строка\n",
                encoding="utf-8",
            )
            accepted, rejected = tool.read_consensus_candidates(source, 3)
            self.assertEqual([row.word for row in accepted], ["творог"])
            self.assertEqual(len(rejected), 1)
            self.assertEqual(rejected[0].source, "stress_candidates")
            self.assertIn("строка 2", rejected[0].reason)

    def test_first_source_wins_over_later_source(self):
        first = [tool.Entry("замок", "з+амок", "stage4.9")]
        later = [tool.Entry("замок", "зам+ок", "upstream")]
        result, rejected = tool.merge_entries([first, later], [])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].marked, "з+амок")
        self.assertEqual(len(rejected), 1)

    def test_conflict_inside_one_source_is_withheld(self):
        rows = [
            tool.Entry("замок", "з+амок", "same-source"),
            tool.Entry("замок", "зам+ок", "same-source"),
        ]
        result, rejected = tool.merge_entries([rows], [])
        self.assertEqual(result, [])
        self.assertEqual(len(rejected), 1)

    def test_auto_candidate_cannot_override_source(self):
        trusted = [tool.Entry("замок", "з+амок", "known")]
        candidate = [tool.Entry("замок", "зам+ок", "stress_candidates", observations=8)]
        result, rejected = tool.merge_entries([trusted], candidate)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].marked, "з+амок")
        self.assertEqual(len(rejected), 1)

    def test_candidate_conflict_is_withheld(self):
        candidates = [
            tool.Entry("замок", "з+амок", "stress_candidates", observations=8),
            tool.Entry("замок", "зам+ок", "stress_candidates", observations=9),
        ]
        result, rejected = tool.merge_entries([], candidates)
        self.assertEqual(result, [])
        self.assertEqual(len(rejected), 1)

    def test_review_only_entries_never_enter_auto_dictionary(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "stress_fixes_new.txt"
            source.write_text("творог = твор+ог  # example\n", encoding="utf-8")
            rows, rejected = tool.read_review_only(source)
            self.assertEqual(rows, [])
            self.assertEqual(len(rejected), 1)
            self.assertIn("требующую просмотра", rejected[0].reason)

    def test_dictionary_output_matches_ruvoice_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out" / "stress.txt"
            tool.write_dictionary(output, [tool.Entry("творог", "твор+ог", "test")])
            text = output.read_text(encoding="utf-8")
            self.assertIn("творог твор+ог\n", text)
            self.assertNotIn("творог =", text)


if __name__ == "__main__":
    unittest.main()
