import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import approve_book_entries as tool


class AppendOnlyApprovalTests(unittest.TestCase):
    def test_approved_entry_is_appended_without_losing_existing_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "Book_AutoStress_Candidates.txt"
            selected = root / "approve.txt"
            system = root / "system.txt"
            master = root / "approved.txt"
            report = root / "report.json"

            candidate.write_text("молоко мол+око\n", encoding="utf-8")
            selected.write_text("молоко\n", encoding="utf-8")
            system.write_text("корова кор+ова\n", encoding="utf-8")
            master.write_text("# keep this header\nтворог твор+ог\n", encoding="utf-8")

            args = Namespace(
                candidate_file=candidate,
                approve_words=selected,
                system_dictionary=system,
                approved_dictionary=master,
                report=report,
            )
            self.assertEqual(tool.build(args), 0)
            output = master.read_text(encoding="utf-8")
            self.assertIn("# keep this header", output)
            self.assertIn("творог твор+ог", output)
            self.assertIn("молоко мол+око", output)

    def test_conflict_aborts_without_modifying_master(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "Book_AutoStress_Candidates.txt"
            selected = root / "approve.txt"
            system = root / "system.txt"
            master = root / "approved.txt"
            before = "# do not change\nтворог твор+ог\n"

            candidate.write_text("молоко мол+око\n", encoding="utf-8")
            selected.write_text("молоко\n", encoding="utf-8")
            system.write_text("молоко молок+о\n", encoding="utf-8")
            master.write_text(before, encoding="utf-8")

            args = Namespace(
                candidate_file=candidate,
                approve_words=selected,
                system_dictionary=system,
                approved_dictionary=master,
                report=root / "report.json",
            )
            with self.assertRaises(ValueError):
                tool.build(args)
            self.assertEqual(master.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
