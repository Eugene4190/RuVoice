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
                "broken not-a-word\n"
                "дом д+ом\n",
                encoding="utf-8",
            )
            dictionary, conflicts = tool.parse_dictionary(path)
            self.assertEqual(dictionary["творог"], "твор+ог")
            self.assertEqual(dictionary["холеной"], "хол+ёной")
            self.assertNotIn("дом", dictionary)
            self.assertEqual(conflicts, [])

    def test_conflicting_dictionary_entry_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stress.txt"
            path.write_text("замок з+амок\nзамок зам+ок\n", encoding="utf-8")
            dictionary, conflicts = tool.parse_dictionary(path)
            self.assertNotIn("замок", dictionary)
            self.assertEqual(len(conflicts), 1)

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
        summary, counts, contexts, missing = tool.analyze(
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


if __name__ == "__main__":
    unittest.main()
