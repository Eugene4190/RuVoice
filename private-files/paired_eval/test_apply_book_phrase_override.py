#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).with_name("apply_book_phrase_override.py")
SPEC = importlib.util.spec_from_file_location("apply_book_phrase_override", SOURCE)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class BookPhraseOverrideTests(unittest.TestCase):
    def test_adds_only_the_single_reviewed_phrase(self) -> None:
        original = {
            "homodict": {"сети": ["се́ти", "сети́"]},
            "phrases": {
                "самом": [["о самом интересном", "сам+ом"]],
                "сети": [["в сети значений", "сети́"]],
            },
            "gram": {"дела": {"n": "де́ла"}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "silero_ru.json"
            path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")

            self.assertTrue(module.apply(path))
            result = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(result["homodict"], original["homodict"])
            self.assertEqual(result["gram"], original["gram"])
            self.assertEqual(result["phrases"]["самом"], original["phrases"]["самом"])
            self.assertIn(["в сети значений", "сети́"], result["phrases"]["сети"])
            self.assertEqual(
                [row for row in result["phrases"]["сети"] if row[0] == "сети значений"],
                [["сети значений", "с+ети"]],
            )
            self.assertEqual(len(result["phrases"]["сети"]), 2)

            # A second application is idempotent.
            self.assertFalse(module.apply(path))
            result_again = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(result_again, result)

    def test_refuses_a_conflicting_existing_phrase(self) -> None:
        original = {"phrases": {"сети": [["сети значений", "сети+"] ]}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "silero_ru.json"
            path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError):
                module.apply(path)


if __name__ == "__main__":
    unittest.main()
