import csv
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import build_book_dictionary as tool


class BookDictionaryTests(unittest.TestCase):
    def test_only_book_specific_consensus_candidates_are_exported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = root / "book.txt"
            system = root / "system.txt"
            approved = root / "approved.txt"
            pool = root / "pool.txt"
            audit = root / "audit.tsv"
            out = root / "out"

            book.write_text("молоко молоко корова творог старое неизвестное", encoding="utf-8")
            system.write_text("корова кор+ова\n", encoding="utf-8")
            approved.write_text("творог твор+ог\n", encoding="utf-8")
            pool.write_text(
                "молоко мол+око\n"
                "корова кор+ова\n"
                "старое стар+ое\n"
                "вне_книги вне_кни+ги\n",
                encoding="utf-8",
            )
            audit.write_text(
                "# provenance\nword\tstress\tsource\n"
                "молоко\tмол+око\taot_wiktionary_silero_consensus\n"
                "корова\tкор+ова\taot_wiktionary_silero_consensus\n"
                "старое\tстар+ое\tstage49_existing\n",
                encoding="utf-8",
            )

            args = Namespace(
                book=book,
                system_dictionary=system,
                approved_dictionary=approved,
                candidate_dictionary=pool,
                candidate_audit=audit,
                output_dir=out,
            )
            self.assertEqual(tool.build(args), 0)

            candidate_text = (out / "Book_AutoStress_Candidates.txt").read_text(encoding="utf-8")
            self.assertIn("молоко мол+око", candidate_text)
            candidate_review = (out / "Book_AutoStress_Candidate_Review.tsv").read_text(encoding="utf-8-sig")
            self.assertIn("UNREVIEWED", candidate_review)
            self.assertNotIn("корова", candidate_text)
            self.assertNotIn("творог", candidate_text)
            self.assertNotIn("старое", candidate_text)
            self.assertNotIn("вне_книги", candidate_text)

            report = __import__("json").loads((out / "Book_Report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["new_candidate_forms"], 1)
            self.assertEqual(report["new_candidate_tokens"], 2)
            self.assertEqual(report["already_in_system_tokens"], 1)
            self.assertEqual(report["already_in_approved_supplement_tokens"], 1)
            self.assertEqual(report["unresolved_forms"], 2)
            book_approved = (out / "Book_Approved_Additions.txt").read_text(encoding="utf-8")
            self.assertIn("творог твор+ог", book_approved)  # Export only book-used approved additions absent from system.
            cumulative = (out / "RuVoice_Accumulated_Approved.txt").read_text(encoding="utf-8")
            self.assertIn("творог твор+ог", cumulative)

    def test_system_dictionary_conflict_is_not_auto_overridden(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = root / "book.txt"
            system = root / "system.txt"
            approved = root / "approved.txt"
            pool = root / "pool.txt"
            audit = root / "audit.tsv"
            out = root / "out"

            book.write_text("трёхгорке", encoding="utf-8")
            system.write_text(
                "трёхгорке тр+ёхгорке\n"
                "трёхгорке трёхг+орке\n",
                encoding="utf-8",
            )
            approved.write_text("# empty\n", encoding="utf-8")
            pool.write_text("трёхгорке трёхг+орке\n", encoding="utf-8")
            audit.write_text(
                "word\tstress\tsource\n"
                "трёхгорке\tтрёхг+орке\tcurated_manual_reviewed\n",
                encoding="utf-8",
            )

            args = Namespace(
                book=book,
                system_dictionary=system,
                approved_dictionary=approved,
                candidate_dictionary=pool,
                candidate_audit=audit,
                output_dir=out,
            )
            self.assertEqual(tool.build(args), 0)
            candidate_text = (out / "Book_AutoStress_Candidates.txt").read_text(encoding="utf-8")
            self.assertNotIn("трёхгорке трёхг+орке", candidate_text)
            review_text = (out / "Book_AutoStress_Review.tsv").read_text(encoding="utf-8-sig")
            self.assertIn("CONFLICT", review_text)


    def test_context_rule_holds_unstressed_preposition_out_of_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = root / "book.txt"
            system = root / "system.txt"
            approved = root / "approved.txt"
            pool = root / "pool.txt"
            audit = root / "audit.tsv"
            rules = root / "rules.tsv"
            out = root / "out"

            book.write_text("обо", encoding="utf-8")
            system.write_text("# empty\n", encoding="utf-8")
            approved.write_text("# empty\n", encoding="utf-8")
            pool.write_text("обо об+о\n", encoding="utf-8")
            audit.write_text(
                "word\tstress\tsource\n"
                "обо\tоб+о\taot_wiktionary_silero_consensus\n",
                encoding="utf-8",
            )
            rules.write_text(
                "word\taction\treason\tsource\n"
                "обо\tWITHHOLD_UNSTRESSED\tслужебный предлог\thttps://gramota.ru\n",
                encoding="utf-8",
            )

            args = Namespace(
                book=book,
                system_dictionary=system,
                approved_dictionary=approved,
                candidate_dictionary=pool,
                candidate_audit=audit,
                candidate_rules=rules,
                output_dir=out,
            )
            self.assertEqual(tool.build(args), 0)
            candidate_text = (out / "Book_AutoStress_Candidates.txt").read_text(encoding="utf-8")
            self.assertNotIn("обо", candidate_text)
            review_text = (out / "Book_AutoStress_Review.tsv").read_text(encoding="utf-8-sig")
            self.assertIn("WITHHOLD_UNSTRESSED", review_text)


    def test_provenance_keeps_e_and_yo_spellings_as_distinct_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit = Path(tmp) / "audit.tsv"
            audit.write_text(
                "word\\tstress\\tsource\\n"
                "берёг\\tбер+ёг\\taot_wiktionary_silero_consensus\\n"
                "берег\\tб+ерег\\tstage49_existing\\n",
                encoding="utf-8",
            )
            self.assertEqual(
                tool.load_provenance(audit),
                {"берёг": "aot_wiktionary_silero_consensus"},
            )

    def test_e_yo_alias_without_exact_spelling_is_held_for_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = root / "book.txt"
            system = root / "system.txt"
            approved = root / "approved.txt"
            pool = root / "pool.txt"
            audit = root / "audit.tsv"
            out = root / "out"

            book.write_text("берег", encoding="utf-8")
            system.write_text("# empty\\n", encoding="utf-8")
            approved.write_text("# empty\\n", encoding="utf-8")
            pool.write_text("берёг бер+ёг\\n", encoding="utf-8")
            audit.write_text(
                "word\\tstress\\tsource\\n"
                "берёг\\tбер+ёг\\taot_wiktionary_silero_consensus\\n"
                "берег\\tб+ерег\\tstage49_existing\\n",
                encoding="utf-8",
            )

            args = Namespace(
                book=book,
                system_dictionary=system,
                approved_dictionary=approved,
                candidate_dictionary=pool,
                candidate_audit=audit,
                output_dir=out,
            )
            self.assertEqual(tool.build(args), 0)

            candidate_text = (out / "Book_AutoStress_Candidates.txt").read_text(encoding="utf-8")
            self.assertNotIn("берег ", candidate_text)
            review_text = (out / "Book_AutoStress_Review.tsv").read_text(encoding="utf-8-sig")
            self.assertIn("ORTHOGRAPHY_ALIAS_REVIEW", review_text)
            self.assertIn("берёг", review_text)
            report = __import__("json").loads((out / "Book_Report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["new_candidate_forms"], 0)
            self.assertEqual(report["conflict_forms"], 1)

    def test_e_yo_alias_with_different_stress_is_held_even_with_exact_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = root / "book.txt"
            system = root / "system.txt"
            approved = root / "approved.txt"
            pool = root / "pool.txt"
            audit = root / "audit.tsv"
            out = root / "out"

            book.write_text("берег", encoding="utf-8")
            system.write_text("# empty\\n", encoding="utf-8")
            approved.write_text("# empty\\n", encoding="utf-8")
            pool.write_text(
                "берег б+ерег\\n"
                "берёг бер+ёг\\n",
                encoding="utf-8",
            )
            audit.write_text(
                "word\\tstress\\tsource\\n"
                "берег\\tб+ерег\\taot_wiktionary_silero_consensus\\n"
                "берёг\\tбер+ёг\\tstage49_existing\\n",
                encoding="utf-8",
            )

            args = Namespace(
                book=book,
                system_dictionary=system,
                approved_dictionary=approved,
                candidate_dictionary=pool,
                candidate_audit=audit,
                output_dir=out,
            )
            self.assertEqual(tool.build(args), 0)

            candidate_text = (out / "Book_AutoStress_Candidates.txt").read_text(encoding="utf-8")
            self.assertNotIn("берег ", candidate_text)
            review_text = (out / "Book_AutoStress_Review.tsv").read_text(encoding="utf-8-sig")
            self.assertIn("ORTHOGRAPHY_ALIAS_REVIEW", review_text)
            self.assertIn("другое положение ударения", review_text)

    def test_e_yo_alias_with_same_stress_position_keeps_exact_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = root / "book.txt"
            system = root / "system.txt"
            approved = root / "approved.txt"
            pool = root / "pool.txt"
            audit = root / "audit.tsv"
            out = root / "out"

            book.write_text("холеной", encoding="utf-8")
            system.write_text("# empty\\n", encoding="utf-8")
            approved.write_text("# empty\\n", encoding="utf-8")
            pool.write_text(
                "холеной хол+ёной\\n"
                "холёной хол+ёной\\n",
                encoding="utf-8",
            )
            audit.write_text(
                "word\\tstress\\tsource\\n"
                "холеной\\tхол+ёной\\taot_wiktionary_silero_consensus\\n"
                "холёной\\tхол+ёной\\tstage49_existing\\n",
                encoding="utf-8",
            )

            args = Namespace(
                book=book,
                system_dictionary=system,
                approved_dictionary=approved,
                candidate_dictionary=pool,
                candidate_audit=audit,
                output_dir=out,
            )
            self.assertEqual(tool.build(args), 0)

            candidate_text = (out / "Book_AutoStress_Candidates.txt").read_text(encoding="utf-8")
            self.assertIn("холеной хол+еной", candidate_text)
            review_text = (out / "Book_AutoStress_Review.tsv").read_text(encoding="utf-8-sig")
            self.assertNotIn("ORTHOGRAPHY_ALIAS_REVIEW", review_text)


if __name__ == "__main__":
    unittest.main()
