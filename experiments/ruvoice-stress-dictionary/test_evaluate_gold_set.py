import csv
import tempfile
import unittest
from pathlib import Path

import evaluate_gold_set as tool


class GoldSetEvaluatorTests(unittest.TestCase):
    def test_repository_seed_is_valid_and_keeps_contextual_homographs_separate(self):
        path = Path(__file__).parent / "data" / "gold" / "seed.tsv"
        rows = tool.load_gold(path)
        self.assertEqual(len(rows), 7)
        marked = [row for row in rows if row["surface"] == "маркированный"]
        self.assertEqual(len(marked), 2)
        self.assertEqual({row["sense_id"] for row in marked}, {"linguistic_term", "labelled_goods"})
        self.assertEqual({row["evaluation_scope"] for row in marked}, {"contextual"})

    def test_marked_form_requires_exact_surface_and_stress_before_vowel(self):
        self.assertIsNone(tool.validate_marked("творог", "тв+орог"))
        self.assertIsNotNone(tool.validate_marked("берег", "бер+ёг"))
        self.assertIsNotNone(tool.validate_marked("творог", "тво+рог"))
        self.assertIsNotNone(tool.validate_marked("творог", "тв+о+рог"))

    def test_variants_count_as_correct_and_abstentions_reduce_coverage(self):
        rows = [
            {
                "gold_id": "G1", "surface": "творог", "primary_marked": "",
                "accepted_variants": ["тв+орог", "твор+ог"],
                "evaluation_scope": "word", "category": "normative_variants",
            },
            {
                "gold_id": "G2", "surface": "позвонит", "primary_marked": "позвон+ит",
                "accepted_variants": ["позвон+ит"],
                "evaluation_scope": "word", "category": "inflectional_form",
            },
            {
                "gold_id": "G3", "surface": "маркированный", "primary_marked": "марк+ированный",
                "accepted_variants": ["марк+ированный"],
                "evaluation_scope": "contextual", "category": "semantic_stress",
            },
        ]
        report = tool.evaluate(
            rows,
            {"G1": "твор+ог", "G2": "позв+онит", "G3": ""},
        )
        overall = report["overall"]
        self.assertEqual(overall["gold_rows"], 3)
        self.assertEqual(overall["emitted_predictions"], 2)
        self.assertEqual(overall["correct_predictions"], 1)
        self.assertEqual(overall["incorrect_predictions"], 1)
        self.assertEqual(overall["abstentions_or_missing"], 1)
        self.assertEqual(overall["coverage_percent"], 66.67)
        self.assertEqual(overall["exact_accuracy_among_emitted_percent"], 50.0)
        self.assertEqual(overall["accuracy_over_all_gold_rows_percent"], 33.33)
        self.assertEqual(report["by_evaluation_scope"]["contextual"]["coverage_percent"], 0.0)
        self.assertEqual(report["by_category"]["semantic_stress"]["abstentions_or_missing"], 1)

    def test_primary_variant_must_be_in_accepted_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gold.tsv"
            columns = [
                "gold_id", "surface", "lemma", "part_of_speech", "morph_features",
                "sense_id", "context", "primary_marked", "accepted_marked",
                "evaluation_scope", "category", "source_title", "source_url",
                "evidence", "reviewed_on",
            ]
            row = {
                "gold_id": "X1", "surface": "творог", "lemma": "творог",
                "part_of_speech": "существительное", "morph_features": "м.р.",
                "sense_id": "food", "context": "Свежий творог.",
                "primary_marked": "твор+ог", "accepted_marked": "тв+орог",
                "evaluation_scope": "word", "category": "variant",
                "source_title": "Test dictionary", "source_url": "https://example.org/dict",
                "evidence": "Test evidence", "reviewed_on": "2026-11-25",
            }
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns, delimiter="\t")
                writer.writeheader()
                writer.writerow(row)
            with self.assertRaisesRegex(tool.GoldSetError, "primary_marked"):
                tool.load_gold(path)

    def test_predictions_reject_duplicate_and_unknown_ids(self):
        rows = [
            {
                "gold_id": "G1", "surface": "творог", "primary_marked": "",
                "accepted_variants": ["тв+орог", "твор+ог"],
                "evaluation_scope": "word", "category": "variant",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "predictions.tsv"
            path.write_text(
                "gold_id\tpredicted_marked\nG1\tтв+орог\nG1\tтвор+ог\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(tool.GoldSetError, "повторный prediction"):
                tool.load_predictions(path, rows)
            path.write_text(
                "gold_id\tpredicted_marked\nUNKNOWN\tтв+орог\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(tool.GoldSetError, "неизвестный gold_id"):
                tool.load_predictions(path, rows)


if __name__ == "__main__":
    unittest.main()
