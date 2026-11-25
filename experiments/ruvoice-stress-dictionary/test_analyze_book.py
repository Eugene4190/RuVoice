import tempfile
import unittest
import zipfile
from pathlib import Path

import analyze_book as tool


class BookAnalyzerTests(unittest.TestCase):
    def test_parse_ruvoice_dictionary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stress.txt"
            path.write_text(
                "# comment\n"
                "творог твор+ог\n"
                "холеной = хол+ёной # е/ё alias\n"
                "берег без_ударения\n"
                "дом д+ом\n",
                encoding="utf-8",
            )
            dictionary, conflicts = tool.parse_dictionary(path)
            self.assertEqual(dictionary["творог"], "твор+ог")
            self.assertEqual(dictionary["холеной"], "хол+ёной")
            self.assertEqual(dictionary["дом"], "д+ом")  # lookup coverage keeps valid imported rows, even if one syllable
            self.assertNotIn("берег", dictionary)
            self.assertEqual(len(conflicts), 1)
            self.assertIn("берег", conflicts[0])
            self.assertIn("ударения", conflicts[0])

    def test_parse_dictionary_accepts_hard_e_phonetic_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stress.txt"
            path.write_text("альбукерк альбук+эрк\n", encoding="utf-8")
            dictionary, conflicts = tool.parse_dictionary(path)
            self.assertEqual(dictionary["альбукерк"], "альбук+эрк")
            self.assertEqual(conflicts, [])

    def test_parse_dictionary_rejects_other_letter_substitutions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stress.txt"
            path.write_text("замок з+амак\n", encoding="utf-8")
            dictionary, conflicts = tool.parse_dictionary(path)
            self.assertNotIn("замок", dictionary)
            self.assertEqual(len(conflicts), 1)
            self.assertIn("DIFFERENT_STRESS_POSITION", conflicts[0])
            self.assertIn("замок", conflicts[0])

    def test_missing_stress_field_is_reported_as_a_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stress.txt"
            path.write_text("берег\n", encoding="utf-8")
            dictionary, conflicts = tool.parse_dictionary(path)
            self.assertNotIn("берег", dictionary)
            self.assertEqual(len(conflicts), 1)
            self.assertIn("берег", conflicts[0])

    def test_conflicting_dictionary_entry_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stress.txt"
            path.write_text("замок з+амок\nзамок зам+ок\n", encoding="utf-8")
            dictionary, conflicts = tool.parse_dictionary(path)
            self.assertNotIn("замок", dictionary)
            self.assertEqual(len(conflicts), 1)

    def test_same_stress_position_phonetic_variant_is_classified_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stress.txt"
            path.write_text(
                "модель м+одель\n"
                "модель м+одэль\n",
                encoding="utf-8",
            )
            dictionary, conflicts = tool.parse_dictionary(path)
            self.assertNotIn("модель", dictionary)
            self.assertEqual(len(conflicts), 1)
            self.assertIn("SAME_STRESS_POSITION_PHONETIC_VARIANT", conflicts[0])
            self.assertNotIn("DIFFERENT_STRESS_POSITION", conflicts[0])

    def test_extract_epub_and_ignore_navigation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.epub"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("OEBPS/chapter.xhtml",
                    '<html><head><title>hidden</title></head><body>'
                    '<nav>оглавление</nav><h1>Глава</h1>'
                    '<p>Творог лежал на столе &amp; рядом было молоко.</p>'
                    '<script>вредныйтекст</script></body></html>')
            text = tool.extract_text(path)
            self.assertIn("Творог лежал на столе & рядом было молоко", text)
            self.assertNotIn("оглавление", text)
            self.assertNotIn("hidden", text)
            self.assertNotIn("вредныйтекст", text)

    def test_coverage_counts_tokens_and_missing_contexts(self):
        summary, counts, contexts, missing, hit_contexts = tool.analyze(
            "Творог и молоко. Творог стоял рядом.",
            {"творог": "твор+ог"},
            context_radius=2,
            max_contexts=2,
        )
        self.assertEqual(summary["total_word_tokens"], 6)
        self.assertEqual(summary["matched_word_tokens"], 2)
        self.assertEqual(summary["weighted_token_coverage_percent"], 33.33)
        self.assertEqual(counts["творог"], 2)
        self.assertIn("и", missing)
        self.assertLessEqual(len(contexts["молоко"]), 2)
        self.assertEqual(len(hit_contexts["творог"]), 2)


if __name__ == "__main__":
    unittest.main()
