import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from analyze_book import parse_dictionary
from personal_book_workflow import process_book


class PersonalBookWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.private = self.root / "private"
        self.system = self.root / "system.txt"
        self.pool = self.root / "pool.txt"
        self.audit = self.root / "audit.tsv"
        self.rules = self.root / "rules.tsv"
        self.system.write_text("# empty system dictionary\n", encoding="utf-8")
        self.pool.write_text(
            "молоко мол+око\n"
            "творог твор+ог\n",
            encoding="utf-8",
        )
        self.audit.write_text(
            "word\tstress\tsource\n"
            "молоко\tмол+око\taot_wiktionary_silero_consensus\n"
            "творог\tтвор+ог\taot_wiktionary_silero_consensus\n",
            encoding="utf-8",
        )
        self.rules.write_text("word\taction\treason\tsource\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def make_epub(self, path, text):
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("mimetype", "application/epub+zip")
            archive.writestr(
                "OEBPS/chapter.xhtml",
                f'<html xmlns="http://www.w3.org/1999/xhtml"><body><p>{text}</p></body></html>',
            )

    def run_book(self, path, replacements=None):
        return process_book(
            path,
            private_home=self.private,
            system_dictionary=self.system,
            candidate_dictionary=self.pool,
            candidate_audit=self.audit,
            candidate_rules=self.rules,
            replacements=replacements,
        )

    def test_epub_a_then_b_then_repeat_b_keeps_cumulative_master_and_replacements(self):
        book_a = self.root / "A.epub"
        book_b = self.root / "B.epub"
        self.make_epub(book_a, "молоко")
        # B also contains A's already-approved word; it must not enter B's delta,
        # but provenance should record that the word appeared in both books.
        self.make_epub(book_b, "творог молоко")
        replacement_file = self.root / "B_replacements.txt"
        replacement_file.write_text("# Правила только для B\nшелка и = шелк+а и\n", encoding="utf-8")

        result_a = self.run_book(book_a)
        self.assertEqual(result_a["new_entry_count"], 1)
        self.assertFalse(result_a["already_processed"])

        master = self.private / "RuVoice_Accumulated_Approved.txt"
        entries_a, conflicts_a = parse_dictionary(master)
        self.assertFalse(conflicts_a)
        self.assertEqual(entries_a, {"молоко": "мол+око"})

        result_b = self.run_book(book_b, replacements=replacement_file)
        self.assertEqual(result_b["new_entry_count"], 1)
        entries_b, conflicts_b = parse_dictionary(master)
        self.assertFalse(conflicts_b)
        self.assertEqual(entries_b, {"молоко": "мол+око", "творог": "твор+ог"})

        # A repeat without re-uploading the replacement TXT must retain B's rules.
        result_b_repeat = self.run_book(book_b)
        self.assertTrue(result_b_repeat["already_processed"])
        self.assertEqual(result_b_repeat["new_entry_count"], 0)
        entries_repeat, conflicts_repeat = parse_dictionary(master)
        self.assertFalse(conflicts_repeat)
        self.assertEqual(entries_repeat, entries_b)

        with zipfile.ZipFile(result_b_repeat["archive"]) as archive:
            names = archive.namelist()
            delta = archive.read("B_New_Stress_Delta.txt").decode("utf-8")
            snapshot = archive.read("MyBooks_Cumulative.txt").decode("utf-8")
            replacements = archive.read("B_Replacements.txt").decode("utf-8")
            history = json.loads(archive.read("MyBooks_History.json"))
            report = json.loads(archive.read("Book_Report.json"))
            self.assertIn("повторная сборка", delta.lower())
            self.assertIn("творог твор+ог", delta)
            self.assertIn("молоко мол+око", delta)
            self.assertIn("молоко мол+око", snapshot)
            self.assertIn("творог твор+ог", snapshot)
            self.assertIn("шелка и = шелк+а и", replacements)
            self.assertIn("A.epub", [row["book_name"] for row in history["books"].values()])
            self.assertIn("B.epub", [row["book_name"] for row in history["books"].values()])
            b_record = history["books"][result_b["book_sha256"]]
            self.assertEqual(b_record["new_entries"][0]["source"], "aot_wiktionary_silero_consensus")
            self.assertTrue(b_record["replacements"]["has_rules"])
            milk_history = history["entries"]["молоко"]
            self.assertEqual(milk_history["first_added_in"], "A.epub")
            self.assertEqual(
                {item["book_name"] for item in milk_history["books_seen_in"]},
                {"A.epub", "B.epub"},
            )
            self.assertEqual(
                {row["word"] for row in b_record["encountered_master_entries"]},
                {"молоко", "творог"},
            )
            self.assertTrue(report["workflow"]["append_only"])
            self.assertEqual(report["workflow"]["newly_approved_count"], 0)
            self.assertEqual(report["workflow"]["book_delta_entry_count"], 1)
            self.assertFalse(report["workflow"]["book_text_included_in_package"])
            self.assertNotIn("A.epub", names)
            self.assertNotIn("B.epub", names)
            self.assertIn("IMPORT.txt", names)
            guide = archive.read("IMPORT.txt").decode("utf-8")
            self.assertIn("B_New_Stress_Delta.txt", guide)
            self.assertIn("B_Replacements.txt", guide)
            self.assertIn("не импортируйте его второй раз", guide.lower())

    def test_reviewed_phrase_rule_is_selected_only_when_exact_phrase_occurs(self):
        contains_phrase = self.root / "contains-phrase.epub"
        unrelated = self.root / "unrelated.epub"
        self.make_epub(contains_phrase, "шелка и платья")
        self.make_epub(unrelated, "платья и шарфы")

        result = self.run_book(contains_phrase)
        with zipfile.ZipFile(result["archive"]) as archive:
            replacement_name = "contains-phrase_Replacements.txt"
            replacements = archive.read(replacement_name).decode("utf-8")
            report = json.loads(archive.read("Book_Report.json"))
            review = archive.read("Book_Replacements_Review.tsv").decode("utf-8-sig")
            self.assertIn("шелка и = шелк+а и", replacements)
            self.assertEqual(report["workflow"]["auto_selected_reviewed_phrase_rules"], 1)
            self.assertIn("curated_reviewed_phrase", review)
            self.assertIn("INCLUDED", review)

        unrelated_result = self.run_book(unrelated)
        with zipfile.ZipFile(unrelated_result["archive"]) as archive:
            replacements = archive.read("unrelated_Replacements.txt").decode("utf-8")
            report = json.loads(archive.read("Book_Report.json"))
            self.assertNotIn("шелка и = шелк+а и", replacements)
            self.assertEqual(report["workflow"]["auto_selected_reviewed_phrase_rules"], 0)

    def test_different_book_with_same_word_does_not_duplicate_master_rows(self):
        book_a = self.root / "same-content-a.epub"
        book_b = self.root / "same-content-b.epub"
        self.make_epub(book_a, "молоко")
        self.make_epub(book_b, "молоко ")
        self.run_book(book_a)
        result = self.run_book(book_b)
        self.assertEqual(result["new_entry_count"], 0)
        rows = [
            line for line in (self.private / "RuVoice_Accumulated_Approved.txt")
            .read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(rows, ["молоко мол+око"])


if __name__ == "__main__":
    unittest.main()
