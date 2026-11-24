#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("full_book_ruvoice_quality.py")
SPEC = importlib.util.spec_from_file_location("full_book_ruvoice_quality", SOURCE)
assert SPEC is not None and SPEC.loader is not None
quality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quality)


class WholeBookQualityVerdictTests(unittest.TestCase):
    def test_variant_supported_by_one_source_is_not_reported_as_error(self) -> None:
        status, _ = quality.verdict(
            "блохами", 1, 0, {0: {"блоха: noun"}},
            {0: {"блоха: plural"}, 1: {"блоха: alternate"}}, set()
        )
        self.assertEqual(status, "BASELINE_SUPPORTED_BY_ONE_SOURCE_VARIANT")

    def test_variant_supported_by_both_sources_is_accepted(self) -> None:
        status, _ = quality.verdict(
            "маркирована", 2, 1, {1: {"маркировать:short"}},
            {1: {"маркировать:short"}, 2: {"маркированный:meaning"}}, set()
        )
        self.assertEqual(status, "BASELINE_SUPPORTED_BY_BOTH_SOURCE_VARIANTS")

    def test_two_source_consensus_can_identify_a_candidate(self) -> None:
        status, _ = quality.verdict(
            "утрам", 1, 0, {0: {"утро:dative plural"}},
            {0: {"утро:dative plural"}}, set()
        )
        self.assertEqual(status, "RUVOICE_DIFFERS_RUACCENT_AND_BOTH_DICTS_AGREE")

    def test_both_models_wrong_against_consensus_stays_visible(self) -> None:
        status, _ = quality.verdict(
            "несчастлив", 1, 1, {2: {"несчастливый:short masculine"}},
            {2: {"несчастливый:short masculine"}}, set()
        )
        self.assertEqual(status, "BOTH_DIFFER_FROM_AOT_WIKT")

    def test_contextual_genitive_variant_is_not_false_positive(self) -> None:
        rules = quality.load_context_acceptances(
            SOURCE.with_name("book_context_acceptances.tsv")
        )
        status, _ = quality.verdict(
            "следа", 1, 1, {0: {"след:genitive"}},
            {0: {"след:genitive"}}, set(),
            "Мишура без следа растает позади.", rules
        )
        self.assertEqual(status, "CONTEXTUAL_VARIANT_ACCEPTED")

    def test_context_rule_does_not_apply_without_matching_context(self) -> None:
        rules = quality.load_context_acceptances(
            SOURCE.with_name("book_context_acceptances.tsv")
        )
        status, _ = quality.verdict(
            "следа", 1, 1, {0: {"след:genitive"}},
            {0: {"след:genitive"}}, set(),
            "На бумаге остался следа? Нет.", rules
        )
        self.assertNotEqual(status, "CONTEXTUAL_VARIANT_ACCEPTED")

    def test_late_is_contextual_comparative_adverb(self) -> None:
        rules = quality.load_context_acceptances(
            SOURCE.with_name("book_context_acceptances.tsv")
        )
        status, _ = quality.verdict(
            "позднее", 1, 1, {0: {"поздний:adjective"}},
            {0: {"поздний:adjective"}}, set(),
            "Родившийся позднее получает другое понятие.", rules
        )
        self.assertEqual(status, "CONTEXTUAL_VARIANT_ACCEPTED")

    def test_yo_counts_as_stressed_without_combining_acute(self) -> None:
        self.assertEqual(quality.acute_position("далёко"), 1)
        self.assertEqual(quality.acute_position("поздне́е"), 1)

    def test_expanded_numeral_twenty_is_stressed_on_first_syllable(self) -> None:
        overlay = SOURCE.with_name("book_reviewed_overrides.txt")
        entries = dict(line.split() for line in overlay.read_text(encoding="utf-8").splitlines() if line.strip())
        self.assertEqual(entries["двадцать"], "два+дцать")
        self.assertEqual(quality.acute_position("два́дцать"), 0)


if __name__ == "__main__":
    unittest.main()
