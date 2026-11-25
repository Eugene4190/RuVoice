#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("audit_book_third_model.py")
SPEC = importlib.util.spec_from_file_location("audit_book_third_model", SOURCE)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class ThirdModelAuditParsingTests(unittest.TestCase):
    def test_parses_apostrophe_after_stressed_vowel(self):
        self.assertEqual(module.accent_position("приве'т"), 1)
        self.assertEqual(module.accent_position("моло'ко"), 1)

    def test_yo_is_intrinsically_stressed(self):
        self.assertEqual(module.accent_position("всё"), 0)
        self.assertEqual(module.accent_position("ёлка"), 0)

    def test_multiple_apostrophes_are_not_silently_accepted(self):
        self.assertIsNone(module.accent_position("пр'иве'т"))

    def test_long_segments_split_without_losing_any_characters(self):
        source = "Первое длинное предложение. " * 20
        chunks = module.split_context(source, 100)
        self.assertEqual("".join(chunks), source)
        self.assertGreater(len(chunks), 1)

    def test_word_normalization_ignores_stress_and_yo_distinction(self):
        self.assertEqual(module.norm("Всё́"), "все")
        self.assertEqual(module.norm("Сло+во"), "слово")




class ThreeModelOverrideTests(unittest.TestCase):
    @staticmethod
    def row(word="пример", base=0, ra=1, third=1, segment=0, index=0, context="Это пример контекста."):
        return [
            segment, index, "Глава 1", segment + 1, word,
            "при+мер", "" if base is None else base,
            "приме́р", "" if ra is None else ra,
            "приме'р", "" if third is None else third,
            context,
        ]

    @staticmethod
    def quality(aot="", wikt="", status=""):
        return {
            "aot_stress_positions": aot,
            "wiktionary_stress_positions": wikt,
            "baseline_status": status,
            "aot_source_details": "пример:noun",
            "wiktionary_source_details": "пример:noun",
        }

    def test_one_dictionary_plus_two_models_creates_confirmed_entry(self):
        rows = [self.row(segment=0, index=0), self.row(segment=1, index=0)]
        quality = {(0, 0): self.quality("1", ""), (1, 0): self.quality("1", "")}
        confirmed, oov, evidence, summary = module.build_three_model_overrides(rows, quality, set())
        self.assertEqual(confirmed, ["пример прим+ер"])
        self.assertEqual(oov, [])
        self.assertEqual(evidence[0][0], "ONE_DICTIONARY_PLUS_TWO_MODELS")
        self.assertEqual(summary["confirmed_occurrences"], 2)

    def test_repeated_oov_is_separate_not_importable(self):
        rows = [self.row(segment=i, index=0) for i in range(3)]
        quality = {(i, 0): self.quality() for i in range(3)}
        confirmed, oov, evidence, summary = module.build_three_model_overrides(rows, quality, set())
        self.assertEqual(confirmed, [])
        self.assertEqual(oov, ["пример прим+ер"])
        self.assertEqual(evidence[0][0], "REPEATED_OOV_TWO_MODEL_CONSENSUS")
        self.assertEqual(summary["repeated_oov_review_occurrences"], 3)

    def test_source_variant_conflict_blocks_override(self):
        rows = [self.row(segment=0, index=0), self.row(segment=1, index=0)]
        quality = {(0, 0): self.quality("0,1", "1"), (1, 0): self.quality("0,1", "1")}
        confirmed, oov, _, summary = module.build_three_model_overrides(rows, quality, set())
        self.assertEqual(confirmed, [])
        self.assertEqual(oov, [])
        self.assertEqual(summary["excluded_by_reason"]["dictionary_records_alternative_or_conflict"], 1)

    def test_models_must_agree_at_every_occurrence(self):
        rows = [self.row(segment=0, index=0), self.row(segment=1, index=0, third=0)]
        quality = {(0, 0): self.quality("1", "1"), (1, 0): self.quality("1", "1")}
        confirmed, oov, _, summary = module.build_three_model_overrides(rows, quality, set())
        self.assertEqual(confirmed, [])
        self.assertEqual(oov, [])
        self.assertEqual(summary["excluded_by_reason"]["two_independent_models_disagree"], 1)

    def test_baseline_must_be_consistently_wrong(self):
        rows = [self.row(segment=0, index=0), self.row(segment=1, index=0, base=1)]
        quality = {(0, 0): self.quality("1", "1"), (1, 0): self.quality("1", "1")}
        confirmed, oov, _, summary = module.build_three_model_overrides(rows, quality, set())
        self.assertEqual(confirmed, [])
        self.assertEqual(oov, [])
        self.assertEqual(summary["excluded_by_reason"]["baseline_is_mixed_or_already_correct"], 1)

    def test_contextual_exception_blocks_override(self):
        rows = [self.row(segment=0, index=0), self.row(segment=1, index=0)]
        quality = {(0, 0): self.quality("1", "1", "CONTEXTUAL_VARIANT_ACCEPTED"),
                   (1, 0): self.quality("1", "1")}
        confirmed, oov, _, summary = module.build_three_model_overrides(rows, quality, set())
        self.assertEqual(confirmed, [])
        self.assertEqual(oov, [])
        self.assertEqual(summary["excluded_by_reason"]["contextual_exception"], 1)

    def test_existing_manual_override_is_not_duplicated(self):
        rows = [self.row(segment=0, index=0), self.row(segment=1, index=0)]
        quality = {(0, 0): self.quality("1", "1"), (1, 0): self.quality("1", "1")}
        confirmed, oov, _, summary = module.build_three_model_overrides(rows, quality, {"пример"})
        self.assertEqual(confirmed, [])
        self.assertEqual(oov, [])
        self.assertEqual(summary["excluded_by_reason"]["already_in_reviewed_overlay"], 2)


if __name__ == "__main__":
    unittest.main()
