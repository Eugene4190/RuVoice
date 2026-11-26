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





class ThirdModelCandidateSelectionTests(unittest.TestCase):
    @staticmethod
    def occurrence(word="пример", base=0, ra=1, segment=0, index=0):
        return [
            segment, index, "Глава", segment + 1, word,
            "при+мер", "" if base is None else base,
            "приме́р", "" if ra is None else ra,
        ]

    @staticmethod
    def evidence(aot="1", wikt="", status=""):
        return {
            "aot_stress_positions": aot,
            "wiktionary_stress_positions": wikt,
            "baseline_status": status,
        }

    def test_selects_all_occurrences_of_a_dictionary_supported_disagreement(self):
        rows = [
            self.occurrence(segment=0, index=2),
            self.occurrence(segment=4, index=8),
        ]
        quality = {
            (0, 2): self.evidence("1"),
            (4, 8): self.evidence("1"),
        }
        keys, coords, summary = module.select_third_model_candidates(rows, quality, set())
        self.assertEqual(keys, {"пример"})
        self.assertEqual(coords, {(0, 2), (4, 8)})
        self.assertEqual(summary["candidate_occurrences"], 2)
        self.assertEqual(summary["candidate_segments"], 2)

    def test_oov_consensus_is_not_sent_to_expensive_model_by_default(self):
        rows = [self.occurrence(segment=i) for i in range(3)]
        quality = {(i, 0): self.evidence("", "") for i in range(3)}
        keys, coords, summary = module.select_third_model_candidates(rows, quality, set())
        self.assertEqual(keys, set())
        self.assertEqual(coords, set())
        self.assertEqual(summary["candidate_wordforms"], 0)

    def test_mixed_baseline_occurrences_exclude_whole_wordform(self):
        rows = [
            self.occurrence(base=0, segment=0),
            self.occurrence(base=1, segment=1),
        ]
        quality = {(0, 0): self.evidence("1"), (1, 0): self.evidence("1")}
        keys, coords, _ = module.select_third_model_candidates(rows, quality, set())
        self.assertEqual(keys, set())
        self.assertEqual(coords, set())

    def test_contextual_exception_excludes_whole_wordform(self):
        rows = [
            self.occurrence(segment=0),
            self.occurrence(segment=1),
        ]
        quality = {
            (0, 0): self.evidence("1", "", "CONTEXTUAL_VARIANT_ACCEPTED"),
            (1, 0): self.evidence("1"),
        }
        keys, coords, _ = module.select_third_model_candidates(rows, quality, set())
        self.assertEqual(keys, set())
        self.assertEqual(coords, set())

    def test_dictionary_conflicts_exclude_whole_wordform(self):
        rows = [
            self.occurrence(segment=0),
            self.occurrence(segment=1),
        ]
        quality = {
            (0, 0): self.evidence("0,1", "1"),
            (1, 0): self.evidence("0,1", "1"),
        }
        keys, coords, _ = module.select_third_model_candidates(rows, quality, set())
        self.assertEqual(keys, set())
        self.assertEqual(coords, set())

    def test_function_words_yo_and_existing_overrides_are_not_selected(self):
        rows = [
            self.occurrence(word="молоко", base=0, ra=1, segment=0),
            self.occurrence(word="уже", base=0, ra=1, segment=1),
            self.occurrence(word="ёлка", base=0, ra=1, segment=2),
            self.occurrence(word="пример", base=0, ra=1, segment=3),
        ]
        quality = {
            (0, 0): self.evidence("1"),
            (1, 0): self.evidence("1"),
            (2, 0): self.evidence("1"),
            (3, 0): self.evidence("1"),
        }
        keys, coords, summary = module.select_third_model_candidates(rows, quality, {"пример"})
        self.assertEqual(keys, {"молоко"})
        self.assertEqual(coords, {(0, 0)})
        self.assertGreaterEqual(summary["excluded_by_reason"]["function_word"], 1)
        self.assertGreaterEqual(summary["excluded_by_reason"]["contains_yo"], 1)


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

    def test_partial_third_model_alignment_blocks_book_wide_override(self):
        # Only two of the book's three occurrences reached the aligned model output.
        # Matching models and dictionary evidence on this partial sample are not enough.
        rows = [self.row(segment=i, index=0) for i in range(2)]
        quality = {(i, 0): self.quality("1", "1") for i in range(2)}
        confirmed, oov, evidence, summary = module.build_three_model_overrides(
            rows, quality, set(), expected_occurrence_counts={"пример": 3}
        )
        self.assertEqual(confirmed, [])
        self.assertEqual(oov, [])
        self.assertEqual(evidence, [])
        self.assertEqual(summary["excluded_by_reason"]["incomplete_occurrence_coverage"], 1)

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
        self.assertEqual(summary["excluded_by_reason"]["model_outputs_not_uniform"], 1)

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
