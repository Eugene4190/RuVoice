import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import build_book_dictionary as tool


class AccumulatedMasterConflictTests(unittest.TestCase):
    def test_new_source_disagreement_is_held_and_master_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book, system = root / "book.txt", root / "system.txt"
            master, pool = root / "master.txt", root / "pool.txt"
            audit, rules, out = root / "audit.tsv", root / "rules.tsv", root / "out"
            book.write_text("молоко", encoding="utf-8")
            system.write_text("# empty\n", encoding="utf-8")
            before = "# approved in an earlier book\nмолоко мол+око\n"
            master.write_text(before, encoding="utf-8")
            pool.write_text("молоко молок+о\n", encoding="utf-8")
            audit.write_text(
                "word\tstress\tsource\n"
                "молоко\tмолок+о\taot_wiktionary_silero_consensus\n",
                encoding="utf-8",
            )
            rules.write_text("word\taction\treason\tsource\n", encoding="utf-8")
            args = Namespace(
                book=book, system_dictionary=system, approved_dictionary=master,
                candidate_dictionary=pool, candidate_audit=audit,
                candidate_rules=rules, output_dir=out,
            )
            self.assertEqual(tool.build(args), 0)
            self.assertEqual(master.read_text(encoding="utf-8"), before)
            review = (out / "Book_AutoStress_Review.tsv").read_text(encoding="utf-8-sig")
            self.assertIn("ACCUMULATED_MASTER_CONFLICT", review)
            self.assertIn("старое ударение сохранено", review)


if __name__ == "__main__":
    unittest.main()
