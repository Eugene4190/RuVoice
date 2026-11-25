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


if __name__ == "__main__":
    unittest.main()
