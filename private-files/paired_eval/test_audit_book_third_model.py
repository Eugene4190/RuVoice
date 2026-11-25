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
        self.assertEqual(module.accent_position("всё"), 1)
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


if __name__ == "__main__":
    unittest.main()
