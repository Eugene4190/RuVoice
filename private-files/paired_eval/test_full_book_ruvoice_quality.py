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
            "маркирована", 1, 1, {1: {"маркировать:short"}},
            {1: {"маркировать:short"}, 2: {"маркированный:meaning"}}, set()
        )
        self.assertEqual(status, "BASELINE_SUPPORTED_BY_BOTH_SOURCE_VARIANTS")

    def test_po_utram_keeps_the_normative_adverbial_variant(self) -> None:
        rules = quality.load_context_acceptances(
            SOURCE.with_name("book_context_acceptances.tsv")
        )
        status, _ = quality.verdict(
            "утрам", 1, 1, {0: {"утро:dative plural"}},
            {0: {"утро:dative plural"}}, set(),
            "Фигура появляется по утрам.", rules
        )
        self.assertEqual(status, "CONTEXTUAL_VARIANT_ACCEPTED")

    def test_isolated_utram_dative_does_not_use_the_adverbial_exception(self) -> None:
        rules = quality.load_context_acceptances(
            SOURCE.with_name("book_context_acceptances.tsv")
        )
        status, _ = quality.verdict(
            "утрам", 0, 0, {0: {"утро:dative plural"}},
            {0: {"утро:dative plural"}}, set(),
            "К этим утрам готовились заранее.", rules
        )
        self.assertNotEqual(status, "CONTEXTUAL_VARIANT_ACCEPTED")

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

    def test_reviewed_overlay_uses_plus_before_the_stressed_vowel(self) -> None:
        overlay = SOURCE.with_name("book_reviewed_overrides.txt")
        entries = dict(line.split() for line in overlay.read_text(encoding="utf-8").splitlines() if line.strip())
        expected = {
            "несчастлив": "несчастл+ив",
            "отнята": "отнят+а",
            "шумы": "ш+умы",
            "двадцать": "дв+адцать",
            "десять": "д+есять",
            "издревле": "издр+евле",
            "утолщилась": "утолщ+илась",
            "арбайт": "+арбайт",
            "маше": "маш+е",
            "сапинс": "+сапинс",
            "взаимовымогательства": "взаимовымог+ательства",
            "взаимовымогающим": "взаимовымог+ающим",
            "внутриличностных": "внутрил+ичностных",
            "неприспособление": "неприспособл+ение",
            "нетелесного": "нетел+есного",
            "религиообразовании": "религиообразов+ании",
            "самосуществования": "самосуществов+ания",
        }
        self.assertEqual(entries, expected)
        expected_positions = {
            "несчастлив": 2, "отнята": 2, "шумы": 0, "двадцать": 0,
            "десять": 0, "издревле": 1, "утолщилась": 2,
            "арбайт": 0, "маше": 1, "сапинс": 0,
            "взаимовымогательства": 5, "взаимовымогающим": 5,
            "внутриличностных": 2, "неприспособление": 4,
            "нетелесного": 2, "религиообразовании": 7,
            "самосуществования": 5,
        }
        vowels = set("аеёиоуыэюя")
        for word, variant in entries.items():
            marker = variant.index("+")
            self.assertIn(variant[marker + 1].lower(), vowels)
            self.assertEqual(sum(ch in vowels for ch in variant[:marker]), expected_positions[word])
        self.assertEqual(quality.acute_position("два́дцать"), 0)


if __name__ == "__main__":
    unittest.main()
