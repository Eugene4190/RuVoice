#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("build_book_stress_audit.py")
SPEC = importlib.util.spec_from_file_location("build_book_stress_audit", SOURCE)
assert SPEC is not None and SPEC.loader is not None
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class FullDictionaryEvidenceTests(unittest.TestCase):
    def test_quality_rows_are_joined_by_segment_and_word_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "occurrences.tsv"
            path.write_text(
                "segment_index\tword_index\taot_stress_positions\twiktionary_stress_positions\t"
                "aot_source_details\twiktionary_source_details\tbaseline_status\treviewed_status\n"
                "15\t7\t3\t3\taot detail\twikt detail\tA\tB\n",
                encoding="utf-8",
            )
            rows = audit.read_quality_occurrences(path)
        self.assertEqual(rows[(15, 7)]["aot_stress_positions"], "3")
        self.assertEqual(rows[(15, 7)]["wiktionary_source_details"], "wikt detail")

    def test_full_consensus_can_support_ruvoice_against_ruaccent(self) -> None:
        row = {"aot_stress_positions": "3", "wiktionary_stress_positions": "3"}
        aot, wikt, shared, verdict = audit.quality_source_assessment(row, 3, 2)
        self.assertEqual(aot, {3})
        self.assertEqual(wikt, {3})
        self.assertEqual(shared, {3})
        self.assertEqual(verdict, "CONSENSUS_SUPPORTS_RUVOICE")

    def test_both_dictionary_variants_are_preserved(self) -> None:
        row = {"aot_stress_positions": "1,2", "wiktionary_stress_positions": "2"}
        _, _, shared, verdict = audit.quality_source_assessment(row, 1, 2)
        self.assertEqual(shared, {2})
        self.assertEqual(verdict, "CONSENSUS_SUPPORTS_RUACCENT")

    def test_single_source_support_is_not_mislabelled_as_consensus(self) -> None:
        row = {"aot_stress_positions": "", "wiktionary_stress_positions": "2"}
        _, _, shared, verdict = audit.quality_source_assessment(row, 1, 2)
        self.assertEqual(shared, set())
        self.assertEqual(verdict, "SINGLE_SOURCE_SUPPORTS_RUACCENT")

    def test_disagreeing_sources_are_not_mislabelled_as_no_entry(self) -> None:
        row = {"aot_stress_positions": "0", "wiktionary_stress_positions": "1"}
        _, _, shared, verdict = audit.quality_source_assessment(row, 0, 1)
        self.assertEqual(shared, set())
        self.assertEqual(verdict, "AOT_WIKTIONARY_DISAGREE_NO_SHARED_VARIANT")

    def test_contextual_acceptance_overrides_a_dictionary_only_preference(self) -> None:
        row = {
            "aot_stress_positions": "0",
            "wiktionary_stress_positions": "0",
            "baseline_status": "CONTEXTUAL_VARIANT_ACCEPTED",
        }
        _, _, shared, verdict = audit.quality_source_assessment(row, 1, 0)
        self.assertEqual(shared, {0})
        self.assertEqual(verdict, "CONTEXTUAL_VARIANT_ACCEPTED")

    def test_missing_quality_row_is_explicit(self) -> None:
        _, _, shared, verdict = audit.quality_source_assessment(None, 1, 2)
        self.assertEqual(shared, set())
        self.assertEqual(verdict, "QUALITY_ROW_MISSING")

    def test_no_source_entries_are_distinguished_from_disagreement(self) -> None:
        row = {"aot_stress_positions": "", "wiktionary_stress_positions": ""}
        _, _, shared, verdict = audit.quality_source_assessment(row, 1, 2)
        self.assertEqual(shared, set())
        self.assertEqual(verdict, "NO_INDEPENDENT_REFERENCE")




class AutomaticBookOverrideTests(unittest.TestCase):
    @staticmethod
    def occurrence(segment: int, word: int, baseline: int | None = 0, combined: int | None = 1):
        return {
            "segment_index": segment,
            "word_index": word,
            "source_word": "пример",
            "ruvoice_output": "при+мер" if baseline == 0 else "прим+ер" if baseline == 1 else "пример",
            "ruvoice_stress_vowel_index": baseline,
            "chapter": "Глава 1",
            "paragraph": segment + 1,
        }

    @staticmethod
    def combined(segment: int, word: int, position: int = 1):
        return {
            "segment_index": segment,
            "word_index": word,
            "source_word": "пример",
            "ruaccent_merged_output": "приме́р" if position == 1 else "при́мер",
            "ruaccent_stress_vowel_index": position,
        }

    @staticmethod
    def quality(segment: int, word: int, aot: str = "1", wikt: str = "1", status: str = "RUVOICE_DIFFERS_RUACCENT_AND_BOTH_DICTS_AGREE"):
        return {
            "aot_stress_positions": aot,
            "wiktionary_stress_positions": wikt,
            "baseline_status": status,
            "aot_source_details": "пример:nominative",
            "wiktionary_source_details": "пример:noun",
            "context": "Это пример полного контекста.",
        }

    def test_generates_dictionary_rule_only_after_every_occurrence_agrees(self):
        paired = {
            "baseline_tokens": [self.occurrence(0, 0), self.occurrence(1, 0)],
            "combined_tokens": [self.combined(0, 0), self.combined(1, 0)],
        }
        quality = {(0, 0): self.quality(0, 0), (1, 0): self.quality(1, 0)}
        lines, evidence, summary = audit.build_consensus_auto_overrides(paired, quality)
        self.assertEqual(lines, ["пример прим+ер"])
        self.assertEqual(evidence[0][1], 2)
        self.assertEqual(summary["automatic_override_occurrences"], 2)

    def test_does_not_generate_when_ruaccent_disagrees_at_one_occurrence(self):
        paired = {
            "baseline_tokens": [self.occurrence(0, 0), self.occurrence(1, 0)],
            "combined_tokens": [self.combined(0, 0), self.combined(1, 0, position=0)],
        }
        quality = {(0, 0): self.quality(0, 0), (1, 0): self.quality(1, 0)}
        lines, _, summary = audit.build_consensus_auto_overrides(paired, quality)
        self.assertEqual(lines, [])
        self.assertEqual(summary["excluded_wordforms_by_reason"]["ruaccent_not_consistent_with_reference_for_every_occurrence"], 1)

    def test_does_not_generate_when_reference_sources_have_variants(self):
        paired = {"baseline_tokens": [self.occurrence(0, 0)], "combined_tokens": [self.combined(0, 0)]}
        quality = {(0, 0): self.quality(0, 0, aot="0,1", wikt="1")}
        lines, _, summary = audit.build_consensus_auto_overrides(paired, quality)
        self.assertEqual(lines, [])
        self.assertEqual(summary["excluded_wordforms_by_reason"]["no_single_aot_wiktionary_consensus"], 1)

    def test_does_not_generate_when_ruvoice_is_already_correct_in_some_contexts(self):
        paired = {
            "baseline_tokens": [self.occurrence(0, 0), self.occurrence(1, 0, baseline=1)],
            "combined_tokens": [self.combined(0, 0), self.combined(1, 0)],
        }
        quality = {(0, 0): self.quality(0, 0), (1, 0): self.quality(1, 0)}
        lines, _, summary = audit.build_consensus_auto_overrides(paired, quality)
        self.assertEqual(lines, [])
        self.assertEqual(summary["excluded_wordforms_by_reason"]["ruvoice_already_correct_in_some_occurrences"], 1)

    def test_does_not_duplicate_manually_reviewed_book_words(self):
        paired = {"baseline_tokens": [self.occurrence(0, 0)], "combined_tokens": [self.combined(0, 0)]}
        quality = {(0, 0): self.quality(0, 0)}
        lines, _, summary = audit.build_consensus_auto_overrides(paired, quality, {"пример": {0}})
        self.assertEqual(lines, [])
        self.assertEqual(summary["excluded_wordforms_by_reason"]["already_manually_reviewed"], 1)

    def test_excludes_function_words_and_yo_spellings(self):
        tokens = [
            {"segment_index": 0, "word_index": 0, "source_word": "когда", "ruvoice_output": "ко+гда",
             "ruvoice_stress_vowel_index": 0, "chapter": "Г", "paragraph": 1},
            {"segment_index": 0, "word_index": 1, "source_word": "всё", "ruvoice_output": "всё",
             "ruvoice_stress_vowel_index": 0, "chapter": "Г", "paragraph": 1},
        ]
        combined = [
            {"segment_index": 0, "word_index": 0, "ruaccent_merged_output": "когда́", "ruaccent_stress_vowel_index": 1},
            {"segment_index": 0, "word_index": 1, "ruaccent_merged_output": "всё", "ruaccent_stress_vowel_index": 0},
        ]
        quality = {
            (0, 0): self.quality(0, 0, aot="1", wikt="1"),
            (0, 1): self.quality(0, 1, aot="0", wikt="0"),
        }
        # Both rows are excluded for different reasons: "слово" is a service-like test
        # token only if it is in the explicit function-word list; "всё" is excluded for ё.
        paired = {"baseline_tokens": tokens, "combined_tokens": combined}
        lines, _, summary = audit.build_consensus_auto_overrides(paired, quality)
        self.assertEqual(lines, [])
        self.assertEqual(summary["skipped_occurrences_by_reason"]["contains_yo"], 1)


if __name__ == "__main__":
    unittest.main()
