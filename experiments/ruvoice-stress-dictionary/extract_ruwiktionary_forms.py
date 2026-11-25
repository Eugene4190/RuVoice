#!/usr/bin/env python3
"""Extract stressed Russian forms from the Russian-language Wiktionary edition.

Input is Kaikki/Wiktextract raw JSONL (plain or gzip) from
https://kaikki.org/ruwiktionary/rawdata.html. This is a separate source stream
from tools/wikt_forms.py, which reads Russian-language entries of English
Wiktionary. Output is review data only; this script never writes app assets or
the approved/global dictionary.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, TextIO

ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "data" / "raw" / "raw-wiktextract-data.jsonl.gz"
DEFAULT_OUTPUT = ROOT / ".work" / "ruwiktionary_forms.tsv"
DEFAULT_MANIFEST = ROOT / ".work" / "ruwiktionary_forms_manifest.json"
SOURCE_URL = "https://kaikki.org/ruwiktionary/rawdata.html"
ACCENT = "\u0301"
VOWELS = set("аеёиоуыэюя")
CYRILLIC_FORM_RE = re.compile(r"^[а-яё\u0301-]+$", re.IGNORECASE)
SKIP_TAGS = {
    "romanization",
    "table-tags",
    "inflection-template",
    "class",
    "canonical",
}


@dataclass
class Extraction:
    # surface -> marked form -> source descriptors
    forms: dict[str, dict[str, set[str]]]
    russian_article_count: int
    skipped_form_count: int

    @property
    def multi_variant_surface_count(self) -> int:
        return sum(1 for variants in self.forms.values() if len(variants) > 1)


def strip_stress_marks(value: str) -> str:
    return value.replace(ACCENT, "")


def stressed_form(value: str) -> tuple[str, str] | None:
    """Return (surface, marked) where '+' precedes the primary stressed vowel.

    If combining acute accents are present, the last one is treated as primary,
    matching Russian Wiktionary's notation for compounds with secondary stress.
    An unmarked ё or a single-vowel form is a fallback. A multisyllabic form
    without an acute and without ё is withheld rather than guessed.
    """
    if not isinstance(value, str):
        return None
    form = value.lower()
    if not CYRILLIC_FORM_RE.fullmatch(form):
        return None
    surface = strip_stress_marks(form)
    if not surface or " " in surface or surface.startswith("-"):
        return None

    if ACCENT in form:
        accent_index = form.rindex(ACCENT)
        vowel_index = accent_index - 1
        vowel_index -= form[:accent_index].count(ACCENT)
    elif "ё" in surface:
        vowel_index = surface.index("ё")
    else:
        vowel_positions = [i for i, char in enumerate(surface) if char in VOWELS]
        if len(vowel_positions) != 1:
            return None
        vowel_index = vowel_positions[0]

    if vowel_index < 0 or vowel_index >= len(surface):
        return None
    if surface[vowel_index] not in VOWELS:
        return None
    marked = surface[:vowel_index] + "+" + surface[vowel_index:]
    return surface, marked


def _normalised_form(value: str) -> str:
    return strip_stress_marks(value.lower())


def extract_jsonl(lines: Iterable[str]) -> Extraction:
    """Parse Wiktextract JSONL without retaining raw article objects."""
    table: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    russian_article_count = 0
    skipped_form_count = 0

    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            article = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on input line {line_number}: {exc}") from exc

        if not isinstance(article, dict) or article.get("lang_code") != "ru":
            continue
        russian_article_count += 1

        lemma = article.get("word")
        if not isinstance(lemma, str) or not lemma.strip():
            continue
        lemma = lemma.lower()
        pos = str(article.get("pos") or "")

        raw_forms = article.get("forms")
        form_items = list(raw_forms) if isinstance(raw_forms, list) else []

        # Prefer a stress-marked lemma row from the inflection table. Do not
        # append an unaccented lemma independently when that would let ё
        # override an explicit primary-stress mark elsewhere in a compound.
        lemma_matches = [
            item for item in form_items
            if isinstance(item, dict)
            and isinstance(item.get("form"), str)
            and _normalised_form(item["form"]) == _normalised_form(lemma)
        ]
        if lemma_matches:
            for item in lemma_matches:
                tags = item.get("tags")
                tag_list = list(tags) if isinstance(tags, list) else []
                if "lemma" not in tag_list:
                    tag_list.append("lemma")
                item["tags"] = tag_list
        else:
            form_items.append({"form": lemma, "tags": ["lemma"]})

        for item in form_items:
            if not isinstance(item, dict):
                skipped_form_count += 1
                continue
            raw_form = item.get("form")
            parsed = stressed_form(raw_form)
            if parsed is None:
                skipped_form_count += 1
                continue

            surface, marked = parsed
            raw_tags = item.get("tags")
            tags = tuple(sorted(
                str(tag) for tag in raw_tags
                if isinstance(tag, str)
            )) if isinstance(raw_tags, list) else ()
            if SKIP_TAGS.intersection(tags):
                skipped_form_count += 1
                continue

            descriptor = f"{lemma}:{pos}:{','.join(tags)}"
            table[surface][marked].add(descriptor)

    return Extraction(
        forms={word: dict(variants) for word, variants in table.items()},
        russian_article_count=russian_article_count,
        skipped_form_count=skipped_form_count,
    )


def open_jsonl(path: Path) -> TextIO:
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig")  # type: ignore[return-value]
    return path.open("r", encoding="utf-8-sig")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_tsv(path: Path, extraction: Extraction) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as output:
        for surface in sorted(extraction.forms):
            variants = extraction.forms[surface]
            columns = [
                marked + " " + "|".join(sorted(variants[marked]))
                for marked in sorted(variants)
            ]
            output.write(surface + "\t" + "\t".join(columns) + "\n")


def build_manifest(
    input_path: Path,
    output_path: Path,
    dump_date: str,
    input_sha256: str,
    extraction: Extraction,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_edition": "Russian-language Wiktionary (ru.wiktionary.org)",
        "source_dump_date": dump_date,
        "source_download_page": SOURCE_URL,
        "extractor": "extract_ruwiktionary_forms.py",
        "input_file": input_path.name,
        "input_size_bytes": input_path.stat().st_size,
        "input_sha256": input_sha256,
        "output_file": output_path.name,
        "output_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "russian_article_count": extraction.russian_article_count,
        "distinct_surface_form_count": len(extraction.forms),
        "surface_forms_with_multiple_stress_variants": extraction.multi_variant_surface_count,
        "skipped_form_count": extraction.skipped_form_count,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "review_policy": "separate source stream; do not auto-merge or export to production",
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, default=DEFAULT_INPUT)
    parser.add_argument(
        "--dump-date",
        required=True,
        help="Date of the source ruwiktionary dump, YYYY-MM-DD (for example 2026-11-01)",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        datetime.strptime(args.dump_date, "%Y-%m-%d")
        if not args.input.is_file():
            raise FileNotFoundError(f"Input file not found: {args.input}")
        input_sha256 = sha256_file(args.input)
        with open_jsonl(args.input) as source:
            extraction = extract_jsonl(source)
        write_tsv(args.output, extraction)

        manifest = build_manifest(
            args.input,
            args.output,
            args.dump_date,
            input_sha256,
            extraction,
        )
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ruwiktionary extraction failed: {exc}", file=sys.stderr)
        return 2

    print(
        "RUWIKTIONARY_EXTRACTION="
        + json.dumps(manifest, ensure_ascii=False, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
