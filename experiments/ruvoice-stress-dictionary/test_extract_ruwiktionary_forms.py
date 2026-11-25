import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path

import extract_ruwiktionary_forms as tool


def article(word, pos, forms, lang_code="ru", **extra):
    payload = {"word": word, "pos": pos, "lang_code": lang_code, "forms": forms}
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


class RussianWiktionaryExtractorTests(unittest.TestCase):
    def test_explicit_primary_stress_overrides_unmarked_yo(self):
        # The lemma contains ё, but the Russian Wiktionary paradigm explicitly
        # marks the primary stress on е in бедрум. Do not invent a second variant
        # by appending the unaccented headword independently.
        line = article(
            "четырёхбедрумный",
            "adj",
            [
                {
                    "form": "четырёхбе\u0301друмный",
                    "tags": ["masculine", "nominative", "singular"],
                },
                {
                    "form": "четырёхбе\u0301друмная",
                    "tags": ["feminine", "nominative", "singular"],
                },
                {
                    "form": "четырёхбе\u0301друмно",
                    "tags": ["short", "neuter"],
                },
            ],
        )
        result = tool.extract_jsonl([line])

        self.assertEqual(result.russian_article_count, 1)
        self.assertEqual(
            result.forms["четырёхбедрумный"]["четырёхб+едрумный"],
            {"четырёхбедрумный:adj:lemma,masculine,nominative,singular"},
        )
        self.assertEqual(
            result.forms["четырёхбедрумная"]["четырёхб+едрумная"],
            {"четырёхбедрумный:adj:feminine,nominative,singular"},
        )
        self.assertNotIn("четырёх+бедрумный", result.forms["четырёхбедрумный"])
        self.assertEqual(
            result.forms["четырёхбедрумно"].keys(),
            {"четырёхб+едрумно"},
        )

    def test_multiple_acute_marks_use_last_as_primary(self):
        parsed = tool.stressed_form("четы\u0301рёхбе\u0301друмный")
        self.assertEqual(parsed, ("четырёхбедрумный", "четырёхб+едрумный"))

    def test_fallback_for_yo_and_single_vowel(self):
        self.assertEqual(tool.stressed_form("жёлтый"), ("жёлтый", "ж+ёлтый"))
        self.assertEqual(tool.stressed_form("дом"), ("дом", "д+ом"))
        self.assertIsNone(tool.stressed_form("четырехбедрумный"))

    def test_non_russian_articles_and_skipped_forms_are_ignored(self):
        lines = [
            article(
                "example",
                "noun",
                [{"form": "пример", "tags": ["nominative"]}],
                lang_code="en",
            ),
            article(
                "пример",
                "noun",
                [
                    {"form": "приме\u0301р", "tags": ["nominative"]},
                    {"form": "romanized", "tags": ["romanization"]},
                ],
            ),
        ]
        result = tool.extract_jsonl(lines)
        self.assertEqual(result.russian_article_count, 1)
        self.assertEqual(
            result.forms["пример"]["прим+ер"],
            {"пример:noun:lemma,nominative"},
        )
        self.assertNotIn("romanized", result.forms)
        self.assertGreaterEqual(result.skipped_form_count, 1)

    def test_canonical_headword_form_is_preserved(self):
        # Wiktextract's "canonical" tag can represent the stressed headword
        # form when it differs from the page title; it is not a non-lexical tag.
        line = article(
            "словарь",
            "noun",
            [{"form": "слова\u0301рь", "tags": ["canonical"]}],
        )
        result = tool.extract_jsonl([line])
        self.assertEqual(
            result.forms["словарь"]["слов+арь"],
            {"словарь:noun:canonical,lemma"},
        )

    def test_homographic_stress_variants_are_not_collapsed(self):
        lines = [
            article("мука", "noun", [{"form": "му\u0301ка", "tags": ["food"]}]),
            article("мука", "noun", [{"form": "мука\u0301", "tags": ["suffering"]}]),
        ]
        result = tool.extract_jsonl(lines)
        self.assertEqual(
            set(result.forms["мука"]),
            {"м+ука", "мук+а"},
        )
        self.assertEqual(result.multi_variant_surface_count, 1)

    def test_context_jsonl_keeps_distinct_senses_for_same_form(self):
        tags = ["singular", "nominative"]
        lines = [
            article(
                "замок",
                "noun",
                [{"form": "за\\u0301мок", "tags": tags}],
                tags=["masculine"],
                senses=[{"glosses": ["укреплённое жилище"], "tags": ["masculine"]}],
            ),
            article(
                "замок",
                "noun",
                [{"form": "за\\u0301мок", "tags": tags}],
                tags=["masculine"],
                senses=[{"glosses": ["устройство для запирания"], "tags": ["masculine"]}],
            ),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "contexts.jsonl"
            with output.open("w", encoding="utf-8", newline="\\n") as stream:
                result = tool.extract_jsonl(lines, stream)
            records = [
                json.loads(line)
                for line in output.read_text(encoding="utf-8").splitlines()
            ]

        # The compact stress TSV may merge identical descriptors, but the streamed
        # context data must keep both source senses without retaining them in memory.
        self.assertEqual(
            result.forms["замок"]["з+амок"],
            {"замок:noun:nominative,singular"},
        )
        self.assertEqual(result.context_record_count, 2)
        self.assertEqual(len(records), 2)
        self.assertEqual(
            {record["senses"][0]["glosses"][0] for record in records},
            {"укреплённое жилище", "устройство для запирания"},
        )
        self.assertTrue(all(record["source_line"] in {1, 2} for record in records))

    def test_malformed_json_reports_line_number(self):
        with self.assertRaisesRegex(ValueError, "line 2"):
            tool.extract_jsonl(['{"lang_code":"en"}', "{broken json"])

    def test_four_bedroom_candidate_sheet_is_complete_and_withheld(self):
        root = Path(__file__).resolve().parent
        review_file = root / "reports" / "ruwiktionary-four-bedroom-provisional.tsv"
        with review_file.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream, delimiter="\t"))

        expected_surfaces = {
            "четырёхбедрумна",
            "четырёхбедрумная",
            "четырёхбедрумно",
            "четырёхбедрумного",
            "четырёхбедрумное",
            "четырёхбедрумной",
            "четырёхбедрумном",
            "четырёхбедрумному",
            "четырёхбедрумною",
            "четырёхбедрумную",
            "четырёхбедрумны",
            "четырёхбедрумные",
            "четырёхбедрумный",
            "четырёхбедрумным",
            "четырёхбедрумными",
            "четырёхбедрумных",
        }
        self.assertEqual(len(rows), 16)
        self.assertEqual({row["surface"] for row in rows}, expected_surfaces)
        self.assertEqual(len({row["candidate_id"] for row in rows}), 16)
        for row in rows:
            self.assertEqual(
                row["provisional_marked"],
                row["surface"].replace("бедрум", "б+едрум"),
            )
            self.assertEqual(
                row["approval_status"],
                "WITHHELD_PENDING_HUMAN_PRONUNCIATION_REVIEW",
            )
            self.assertEqual(
                row["source_url"],
                "https://ru.wiktionary.org/wiki/четырёхбедрумный",
            )

    def test_gzip_input_and_tsv_manifest_are_written(self):
        lines = [
            article(
                "беречь",
                "verb",
                [{"form": "берё\u0301г", "tags": ["masculine", "past", "singular"]}],
            )
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "raw.jsonl.gz"
            output = root / "forms.tsv"
            context_output = root / "contexts.jsonl"
            manifest = root / "manifest.json"
            with gzip.open(source, "wt", encoding="utf-8") as stream:
                stream.write("\n".join(lines) + "\n")

            with (
                tool.open_jsonl(source) as stream,
                context_output.open("w", encoding="utf-8", newline="\\n") as context_stream,
            ):
                result = tool.extract_jsonl(stream, context_stream)
            tool.write_tsv(output, result)
            metadata = tool.build_manifest(
                source,
                output,
                "2026-11-01",
                tool.sha256_file(source),
                result,
                context_output,
            )
            manifest.write_text(
                json.dumps(metadata, ensure_ascii=False),
                encoding="utf-8",
            )

            self.assertIn("берёг\tбер+ёг ", output.read_text(encoding="utf-8"))
            loaded = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(loaded["source_dump_date"], "2026-11-01")
            self.assertEqual(loaded["source_edition"], "Russian-language Wiktionary (ru.wiktionary.org)")
            self.assertEqual(loaded["distinct_surface_form_count"], 1)
            self.assertEqual(loaded["context_record_count"], 1)
            self.assertEqual(loaded["context_output_file"], "contexts.jsonl")
            self.assertEqual(len(loaded["context_output_sha256"]), 64)
            self.assertEqual(len(loaded["input_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
