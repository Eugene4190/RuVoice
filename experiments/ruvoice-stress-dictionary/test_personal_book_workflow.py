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

    def run_book(self, path):
        return process_book(
            path,
            private_home=self.private,
            system_dictionary=self.system,
            candidate_dictionary=self.pool,
            candidate_audit=self.audit,
            candidate_rules=self.rules,
        )

    def test_a_then_b_then_repeat_b_is_cumulative_and_idempotent(self):
        book_a = self.root / "A.txt"
        book_b = self.root / "B.txt"
        book_a.write_text("молоко", encoding="utf-8")
        book_b.write_text("творог", encoding="utf-8")

        result_a = self.run_book(book_a)
        self.assertEqual(result_a["new_entry_count"], 1)
        self.assertFalse(result_a["already_processed"])

        master = self.private / "RuVoice_Accumulated_Approved.txt"
        entries_a, conflicts_a = parse_dictionary(master)
        self.assertFalse(conflicts_a)
        self.assertEqual(entries_a, {"молоко": "мол+око"})

        result_b = self.run_book(book_b)
        self.assertEqual(result_b["new_entry_count"], 1)
        entries_b, conflicts_b = parse_dictionary(master)
        self.assertFalse(conflicts_b)
        self.assertEqual(entries_b, {"молоко": "мол+око", "творог": "твор+ог"})

        result_b_repeat = self.run_book(book_b)
        self.assertTrue(result_b_repeat["already_processed"])
        self.assertEqual(result_b_repeat["new_entry_count"], 0)
        entries_repeat, conflicts_repeat = parse_dictionary(master)
        self.assertFalse(conflicts_repeat)
        self.assertEqual(entries_repeat, entries_b)

        with zipfile.ZipFile(result_b_repeat["archive"]) as archive:
            delta = archive.read("Book_New_Stress_Delta.txt").decode("utf-8")
            snapshot = archive.read("MyBooks_Cumulative.txt").decode("utf-8")
            self.assertIn("повторная обработка", delta)
            self.assertIn("молоко мол+око", snapshot)
            self.assertIn("творог твор+ог", snapshot)
            self.assertIn("IMPORT.txt", archive.namelist())
            self.assertIn("Book_Report.json", archive.namelist())

    def test_reprocessing_a_different_book_does_not_duplicate_master_rows(self):
        book_a = self.root / "same-content-a.txt"
        book_b = self.root / "same-content-b.txt"
        book_a.write_text("молоко", encoding="utf-8")
        book_b.write_text("молоко ", encoding="utf-8")
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
