from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import package_ruvoice_import as package


class PackageRuVoiceImportTests(unittest.TestCase):
    def make_fixture(self, root: Path, coverage: float = 100.0):
        book = root / "Test Book.epub"
        book.write_bytes(b"not-in-the-zip")
        quality = root / "quality"
        quality.mkdir()
        (quality / "WholeBook_RuVoice_Quality_Summary.json").write_text(
            json.dumps({
                "tokens_from_ruvoice": 100,
                "occurrences_in_quality_ledger": 100,
                "ledger_coverage_percent": coverage,
                "unique_wordforms": 45,
                "non_russian_or_special_occurrences": 3,
                "manual_book_override_count": 1,
                "automatic_book_override_count": 2,
                "total_book_override_count": 3,
            }),
            encoding="utf-8",
        )
        (quality / "Book_Importable_Stress_Overrides.txt").write_text(
            "# comments\n"
            "замок зам+ок\n"
            "биополя биопол+я\n",
            encoding="utf-8",
        )
        (quality / "Book_Unresolved_OOV_Review.txt").write_text(
            "# not importable\nrareword раре+ворд\n",
            encoding="utf-8",
        )
        with (quality / "WholeBook_RuVoice_AllOccurrences.tsv").open("w", encoding="utf-8-sig") as stream:
            stream.write(
                "baseline_status\treviewed_status\tsource_form\truvoice_output\treviewed_output\t"
                "context\tsegment_index\tword_index\n"
            )
            for index in range(100):
                stream.write(
                    f"BOTH_MATCH_AOT_WIKT\tBOTH_MATCH_AOT_WIKT\tпример\tпри+мер\tпри+мер\t"
                    f"Контекст примера {index}\t{index}\t0\n"
                )
        (quality / "WholeBook_RuVoice_UniqueWords.tsv").write_text(
            "priority_status\tword\tbook_frequency\tsample_contexts\n"
            "BOTH_MATCH_AOT_WIKT\tпример\t100\tКонтекст примера\n",
            encoding="utf-8-sig",
        )
        replacements = root / "replacements.txt"
        replacements.write_text(
            "# book-only\n"
            "сети значений = с+ети значений\n",
            encoding="utf-8",
        )
        return book, quality, replacements

    def test_package_contains_import_lists_full_occurrence_ledger_and_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            book, quality, replacements = self.make_fixture(root)
            output = root / "result.zip"
            summary = package.package(
                book_path=book, quality_dir=quality,
                replacements_path=replacements, output=output,
            )
            self.assertEqual(summary["ledger_coverage_percent"], 100.0)
            self.assertEqual(summary["stress_entries"], 2)
            self.assertEqual(summary["replacement_rules"], 1)
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                self.assertEqual(len(names), 6)
                self.assertNotIn(book.name, names)
                self.assertIn("WholeBook_RuVoice_AllOccurrences.tsv", names)
                self.assertIn("WholeBook_RuVoice_UniqueWords.tsv", names)
                ledger = archive.read("WholeBook_RuVoice_AllOccurrences.tsv").decode("utf-8-sig")
                self.assertEqual(len(ledger.splitlines()) - 1, 100)
                self.assertIn("Контекст примера 99", ledger)
                stress_name = next(x for x in names if x.endswith("_Stress.txt"))
                replacements_name = next(x for x in names if x.endswith("_Replacements.txt"))
                stress_text = archive.read(stress_name).decode("utf-8")
                replacements_text = archive.read(replacements_name).decode("utf-8")
                self.assertIn("замок зам+ок", stress_text)
                self.assertIn("сети значений = с+ети значений", replacements_text)
                report = json.loads(archive.read("Book_Quality_Summary.json"))
                self.assertEqual(report["occurrences_in_full_context_ledger"], 100)
                self.assertEqual(report["total_imported_stress_overrides"], 2)
                self.assertNotIn("context", report)

    def test_package_refuses_a_ledger_that_does_not_match_the_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            book, quality, replacements = self.make_fixture(root)
            ledger = quality / "WholeBook_RuVoice_AllOccurrences.tsv"
            ledger.write_text(
                "baseline_status\treviewed_status\tsource_form\truvoice_output\treviewed_output\t"
                "context\tsegment_index\tword_index\n"
                "BOTH_MATCH_AOT_WIKT\tBOTH_MATCH_AOT_WIKT\tпример\tпри+мер\tпри+мер\t"
                "Контекст\t0\t0\n",
                encoding="utf-8-sig",
            )
            with self.assertRaisesRegex(ValueError, "не совпадает со сводкой"):
                package.package(
                    book_path=book, quality_dir=quality,
                    replacements_path=replacements, output=root / "result.zip",
                )

    def test_package_refuses_incomplete_occurrence_coverage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            book, quality, replacements = self.make_fixture(root, coverage=99.0)
            with self.assertRaisesRegex(ValueError, "100%"):
                package.package(
                    book_path=book, quality_dir=quality,
                    replacements_path=replacements, output=root / "result.zip",
                )

    def test_stress_conflict_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            book, quality, replacements = self.make_fixture(root)
            (quality / "Book_Importable_Stress_Overrides.txt").write_text(
                "замок зам+ок\nзамок з+амок\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "конфликтующая"):
                package.package(
                    book_path=book, quality_dir=quality,
                    replacements_path=replacements, output=root / "result.zip",
                )

    def test_replacement_must_not_change_visible_spelling(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            book, quality, replacements = self.make_fixture(root)
            replacements.write_text("кафе = кафэ\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "только добавлять"):
                package.package(
                    book_path=book, quality_dir=quality,
                    replacements_path=replacements, output=root / "result.zip",
                )


if __name__ == "__main__":
    unittest.main()
