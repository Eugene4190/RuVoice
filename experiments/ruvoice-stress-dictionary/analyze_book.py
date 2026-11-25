#!/usr/bin/env python3
"""Inspect how much of an EPUB/TXT book is covered by a RuVoice stress dictionary.

This is a coverage and context report, not a stress oracle: words missing from
the dictionary are not necessarily mispronounced by the model.
Only the Python standard library is used.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

WORD_RE = re.compile(r"[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*")
VOWELS = set("аеёиоуыэюя")
BLOCK_TAGS = {
    "address", "article", "blockquote", "br", "dd", "div", "dl", "dt",
    "h1", "h2", "h3", "h4", "h5", "h6", "li", "ol", "p", "section",
    "table", "td", "th", "tr", "ul",
}
SKIP_TAGS = {"script", "style", "svg", "head", "nav", "noscript"}


class BookTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self.skip_depth += 1
        elif not self.skip_depth and tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        elif not self.skip_depth and tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"[ \t\r\f\v]+", " ", "".join(self.parts)).strip()


def html_to_text(raw: str) -> str:
    parser = BookTextParser()
    parser.feed(raw)
    parser.close()
    return parser.text()


def extract_epub(path: Path) -> str:
    pieces: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            names = [
                name for name in archive.namelist()
                if name.lower().endswith((".xhtml", ".html", ".htm"))
                and not name.lower().split("/")[-1].startswith("nav")
            ]
            for name in sorted(names):
                raw = archive.read(name).decode("utf-8-sig", errors="replace")
                section = html_to_text(raw)
                if section:
                    pieces.append(section)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError(f"Не удалось прочитать EPUB: {exc}") from exc
    if not pieces:
        raise ValueError("В EPUB не найдены читаемые XHTML/HTML главы")
    return "\n\n".join(pieces)


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".epub":
        return extract_epub(path)
    if suffix in {".html", ".htm", ".xhtml"}:
        return html_to_text(path.read_text(encoding="utf-8-sig", errors="replace"))
    if suffix in {".txt", ".text"}:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    raise ValueError("Поддерживаются EPUB, TXT и HTML")


def parse_dictionary(path: Path) -> tuple[dict[str, str], list[str]]:
    entries: dict[str, str] = {}
    conflicts: list[str] = []

    def add_invalid(number: int, word: str, reason: str) -> None:
        key = word.lower()
        if re.fullmatch(r"[а-яё]+", key):
            entries.pop(key, None)
            if not any(f": {key}:" in row for row in conflicts):
                conflicts.append(f"строка {number}: {key}: {reason}")
        else:
            conflicts.append(
                f"строка {number}: некорректный ключ {word!r}: {reason}"
            )

    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if "=" in stripped:
            word, value = (part.strip() for part in stripped.split("=", 1))
            values = value.split("#", 1)[0].strip().split()
            marked = values[0].lower() if values else ""
        else:
            parts = stripped.split()
            if len(parts) < 2:
                word = parts[0].lower() if parts else ""
                add_invalid(number, word, "отсутствует поле ударения")
                continue
            word, marked = parts[0].lower(), parts[1].lower()

        word, marked = word.lower(), marked.lower()
        if not re.fullmatch(r"[а-яё]+", word):
            add_invalid(number, word, "ключ должен быть одним русским словом")
            continue
        if marked.count("+") != 1:
            add_invalid(number, word, "нужно ровно одно обозначение ударения +")
            continue

        pos = marked.index("+")
        bare = marked.replace("+", "")
        if (
            bare.replace("ё", "е") != word.replace("ё", "е")
            or pos >= len(bare)
            or bare[pos] not in VOWELS
        ):
            add_invalid(number, word, "ударная форма не соответствует ключу или + стоит не перед гласной")
            continue

        if word in entries and entries[word] != marked:
            conflicts.append(f"строка {number}: {word}: {entries[word]} / {marked}")
            entries.pop(word, None)
            continue
        if word not in entries and not any(f": {word}:" in row for row in conflicts):
            entries[word] = marked

    return entries, conflicts

def make_context(words: list[str], index: int, radius: int) -> str:
    start = max(0, index - radius)
    end = min(len(words), index + radius + 1)
    left = "…" if start else ""
    right = "…" if end < len(words) else ""
    return left + " ".join(words[start:end]) + right


def analyze(text: str, dictionary: dict[str, str], context_radius: int, max_contexts: int):
    tokens = [match.group(0).lower() for match in WORD_RE.finditer(text)]
    counts = Counter(tokens)
    contexts: dict[str, list[str]] = defaultdict(list)
    hit_contexts: dict[str, list[str]] = defaultdict(list)
    for index, word in enumerate(tokens):
        target = hit_contexts if word in dictionary else contexts
        if len(target[word]) < max_contexts:
            target[word].append(make_context(tokens, index, context_radius))

    total = len(tokens)
    matched = sum(counts[word] for word in counts if word in dictionary)
    unique_matched = sum(1 for word in counts if word in dictionary)
    unique_words = len(counts)
    missing = sorted(
        (word for word, count in counts.items() if word not in dictionary),
        key=lambda word: (-counts[word], word),
    )
    report = {
        "total_word_tokens": total,
        "unique_word_forms": unique_words,
        "dictionary_entries": len(dictionary),
        "matched_word_tokens": matched,
        "matched_unique_forms": unique_matched,
        "weighted_token_coverage_percent": round(100 * matched / total, 2) if total else 0.0,
        "unique_form_coverage_percent": round(100 * unique_matched / unique_words, 2) if unique_words else 0.0,
        "unmatched_unique_forms": len(missing),
        "note": "Coverage is dictionary lookup coverage, not a measured stress-accuracy score.",
    }
    return report, counts, contexts, missing, hit_contexts


def write_tsv(path: Path, header: list[str], rows: Iterable[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(header)
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка покрытия книги пользовательским словарём RuVoice")
    parser.add_argument("book", type=Path, help="книга EPUB, TXT или HTML")
    parser.add_argument("--dictionary", type=Path, required=True, help="TXT-словарь RuVoice")
    parser.add_argument("--output-dir", type=Path, default=Path("book_scan"))
    parser.add_argument("--min-frequency", type=int, default=2)
    parser.add_argument("--context-radius", type=int, default=7, help="число слов слева/справа от слова")
    parser.add_argument("--max-contexts", type=int, default=5)
    args = parser.parse_args()

    if not args.book.is_file():
        parser.error(f"книга не найдена: {args.book}")
    if not args.dictionary.is_file():
        parser.error(f"словарь не найден: {args.dictionary}")
    if args.min_frequency < 1 or args.context_radius < 0 or args.max_contexts < 1:
        parser.error("частота и число контекстов должны быть положительными, radius — неотрицательным")

    try:
        dictionary, conflicts = parse_dictionary(args.dictionary)
        text = extract_text(args.book)
        summary, counts, contexts, missing, hit_contexts = analyze(
            text, dictionary, args.context_radius, args.max_contexts
        )
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "coverage.json").write_text(
        json.dumps(summary | {
            "book": args.book.name,
            "dictionary": args.dictionary.name,
            "dictionary_conflicts": len(conflicts),
            "min_frequency_reported": args.min_frequency,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_tsv(
        args.output_dir / "missing_words.tsv",
        ["word", "frequency", "examples"],
        [
            [word, counts[word], " || ".join(contexts[word])]
            for word in missing if counts[word] >= args.min_frequency
        ],
    )
    write_tsv(
        args.output_dir / "dictionary_hits.tsv",
        ["word", "dictionary_stress", "frequency", "examples"],
        [
            [word, dictionary[word], counts[word], " || ".join(hit_contexts[word])]
            for word in sorted(counts, key=lambda w: (-counts[w], w)) if word in dictionary
        ],
    )
    write_tsv(
        args.output_dir / "dictionary_conflicts.tsv",
        ["conflict"],
        [[row] for row in conflicts],
    )

    print(f"Слов в книге: {summary['total_word_tokens']}")
    print(f"Покрытие словарём: {summary['weighted_token_coverage_percent']:.2f}% по токенам")
    print(f"Неизвестных словоформ: {summary['unmatched_unique_forms']}")
    print(f"Отчёты: {args.output_dir}")
    print("Отсутствие слова в словаре не означает ошибку ударения модели.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
