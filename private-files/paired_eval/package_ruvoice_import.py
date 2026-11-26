#!/usr/bin/env python3
"""Validate and package book-scoped RuVoice user lists without including EPUB text."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any

CYR_WORD = re.compile(r"^[а-яё]+$", re.IGNORECASE)
MARKED = re.compile(r"^[а-яё]*\+[а-яё]+$", re.IGNORECASE)


def safe_stem(value: str) -> str:
    value = Path(value).stem
    value = re.sub(r"[^A-Za-zА-Яа-яЁё0-9_-]+", "_", value).strip("_-")
    return (value or "Book")[:28]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_stress_list(path: Path) -> list[tuple[str, str]]:
    entries: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            raise ValueError(f"{path.name}:{number}: ожидается «слово слово+ударение»")
        word, marked = parts
        key = word.casefold()
        if not CYR_WORD.fullmatch(word):
            raise ValueError(f"{path.name}:{number}: некорректное русское слово: {word}")
        if not MARKED.fullmatch(marked) or marked.count("+") != 1:
            raise ValueError(f"{path.name}:{number}: неверная разметка ударения: {marked}")
        if marked.replace("+", "").casefold() != key:
            raise ValueError(f"{path.name}:{number}: слово и вариант не совпадают: {word} / {marked}")
        plus_index = marked.index("+")
        if plus_index >= len(marked) - 1 or marked[plus_index + 1].casefold() not in "аеёиоуыэюя":
            raise ValueError(f"{path.name}:{number}: маркер должен стоять перед гласной: {marked}")
        if key in entries and entries[key] != marked:
            raise ValueError(f"{path.name}:{number}: конфликтующая повторная запись: {word}")
        entries[key] = marked
    return sorted(entries.items())


def parse_replacement_list(path: Path) -> list[tuple[str, str]]:
    entries: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key or not value:
            raise ValueError(f"{path.name}:{number}: ожидается «фраза = фраза с +»")
        if "+" not in value or value.replace("+", "") != key:
            raise ValueError(f"{path.name}:{number}: замена должна сохранять исходный текст и только добавлять +: {line}")
        canonical = key.casefold()
        if canonical in entries and entries[canonical] != value:
            raise ValueError(f"{path.name}:{number}: конфликтующее повторное правило: {key}")
        entries[canonical] = value
    return sorted(entries.items())


def sanitize_summary(raw: dict[str, Any], book_name: str, book_sha: str) -> dict[str, Any]:
    if raw.get("ledger_coverage_percent") != 100.0:
        raise ValueError("Нельзя собирать пакет: проверочный реестр не покрывает 100% токенов")
    if raw.get("tokens_from_ruvoice") != raw.get("occurrences_in_quality_ledger"):
        raise ValueError("Нельзя собирать пакет: количество токенов не совпадает с числом записей реестра")
    return {
        "book": book_name,
        "book_sha256": book_sha,
        "tokens_from_original_ruvoice": raw["tokens_from_ruvoice"],
        "occurrences_in_full_context_ledger": raw["occurrences_in_quality_ledger"],
        "ledger_coverage_percent": raw["ledger_coverage_percent"],
        "unique_russian_wordforms": raw.get("unique_wordforms", 0),
        "non_russian_or_special_occurrences": raw.get("non_russian_or_special_occurrences", 0),
        "manual_book_corrections": raw.get("manual_book_override_count", 0),
        "automatic_high_confidence_book_corrections": raw.get("automatic_book_override_count", 0),
        "total_imported_stress_overrides": raw.get("total_book_override_count", 0),
        "imported_context_replacement_rules": None,
        "unscored_function_word_occurrences": raw.get("unscored_function_word_occurrences", 0),
        "unscored_monosyllable_occurrences": raw.get("unscored_monosyllable_occurrences", 0),
        "occurrences_without_independent_reference": raw.get("no_independent_reference_occurrences", 0),
        "function_word_occurrences_requiring_phrase_review": raw.get("unscored_function_word_occurrences", 0),
        "monosyllable_occurrences_not_lexically_scored": raw.get("unscored_monosyllable_occurrences", 0),
        "baseline_suspected_mismatches": raw.get("baseline_suspected_mismatches", 0),
        "reviewed_suspected_mismatches": raw.get("reviewed_ruvoice_suspected_mismatches", 0),
        "status_counts": raw.get("status_counts", {}),
        "reviewed_status_counts": raw.get("reviewed_status_counts", {}),
        "word_occurrences_with_some_independent_reference": raw.get("word_occurrences_with_some_independent_reference", 0),
        "warning": (
            "100% означает, что каждое словоупотребление присутствует в проверочном реестре. "
            "Это не математическая гарантия идеальной нормативной оценки: неоднозначные случаи "
            "и слова без независимого источника не превращаются автоматически в исправления."
        ),
    }


def package(
    *,
    book_path: Path,
    quality_dir: Path,
    replacements_path: Path,
    output: Path,
) -> dict[str, Any]:
    summary_path = quality_dir / "WholeBook_RuVoice_Quality_Summary.json"
    stress_path = quality_dir / "Book_Importable_Stress_Overrides.txt"
    occurrence_path = quality_dir / "WholeBook_RuVoice_AllOccurrences.tsv"
    unique_path = quality_dir / "WholeBook_RuVoice_UniqueWords.tsv"
    for path in (book_path, summary_path, stress_path, replacements_path, occurrence_path, unique_path):
        if not path.is_file():
            raise FileNotFoundError(f"Не найден обязательный файл: {path}")
    raw_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    expected_occurrences = int(raw_summary.get("occurrences_in_quality_ledger", -1))
    required_columns = {
        "baseline_status", "reviewed_status", "source_form", "ruvoice_output",
        "reviewed_output", "context", "segment_index", "word_index",
    }
    ledger_rows = 0
    seen_coordinates: set[tuple[str, str]] = set()
    with occurrence_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        columns = set(reader.fieldnames or [])
        missing_columns = required_columns - columns
        if missing_columns:
            raise ValueError(f"Полный реестр не содержит обязательные колонки: {sorted(missing_columns)}")
        for row in reader:
            ledger_rows += 1
            coordinate = (row["segment_index"], row["word_index"])
            if coordinate in seen_coordinates:
                raise ValueError(f"Полный реестр содержит повторное словоупотребление: {coordinate}")
            seen_coordinates.add(coordinate)
    if ledger_rows != expected_occurrences:
        raise ValueError(
            f"Количество строк полного реестра ({ledger_rows}) не совпадает со сводкой ({expected_occurrences})"
        )
    book_sha = sha256_file(book_path)
    book_name = book_path.name
    stress = parse_stress_list(stress_path)
    replacements = parse_replacement_list(replacements_path)
    summary = sanitize_summary(raw_summary, book_name, book_sha)
    summary["imported_context_replacement_rules"] = len(replacements)
    summary["total_imported_stress_overrides"] = len(stress)
    summary["manual_book_corrections"] = raw_summary.get("manual_book_override_count", 0)
    summary["automatic_high_confidence_book_corrections"] = raw_summary.get("automatic_book_override_count", 0)

    prefix = f"{safe_stem(book_name)}_{book_sha[:8]}"
    stress_name = f"{prefix}_Stress.txt"
    replacements_name = f"{prefix}_Replacements.txt"
    stress_text = (
        "# Отдельный пользовательский список RuVoice «Ударения» для этой книги.\n"
        "# Импортируйте только вместе с соответствующим списком Replacements.\n"
        "# Не заменяйте и не изменяйте «Системный».\n"
        + "".join(f"{word} {marked}\n" for word, marked in stress)
    )
    replacements_text = (
        "# Отдельный пользовательский список RuVoice «Замены» для этой книги.\n"
        "# Исходный EPUB не изменяется. Правила только задают произношение в RuVoice.\n"
        + "".join(f"{key} = {value}\n" for key, value in replacements)
    )
    guide = f"""RuVoice — словари для книги: {book_name}

1. В RuVoice откройте вкладку «Ударения» → меню списка → «Импорт…».
   Выберите файл {stress_name}. Это отдельный список только для этой книги.
2. Откройте вкладку «Замены» → меню списка → «Импорт…».
   Выберите файл {replacements_name}. Он содержит только контекстные правила произношения.
3. Не удаляйте и не переписывайте системный список RuVoice.
4. Оригинальный EPUB не редактировался: в нём нет знаков ударения, плюсов или фонетической переписи.
5. Не импортируйте файлы аудита/очереди OOV как словарь. Неоднозначные формы не были угаданы.
6. При повторном импорте этой же книги используйте те же имена списков; не создавайте дубликаты.

Проверочный охват: {summary['ledger_coverage_percent']}% словоупотреблений
Проверено токенов оригинальным RuVoice: {summary['tokens_from_original_ruvoice']}
Словарных исправлений: {len(stress)}
Контекстных правил: {len(replacements)}

Важно: полный охват реестра не равен абсолютной гарантии безошибочной нормативной разметки.
"""
    safe_summary = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr(stress_name, stress_text)
        archive.writestr(replacements_name, replacements_text)
        archive.writestr("IMPORT.txt", guide)
        archive.writestr("Book_Quality_Summary.json", safe_summary)
        archive.write(occurrence_path, "WholeBook_RuVoice_AllOccurrences.tsv")
        archive.write(unique_path, "WholeBook_RuVoice_UniqueWords.tsv")
    return {
        "output": str(output),
        "book_sha256": book_sha,
        "stress_entries": len(stress),
        "replacement_rules": len(replacements),
        "ledger_rows": ledger_rows,
        "ledger_coverage_percent": summary["ledger_coverage_percent"],
        "zip_members": [
            stress_name, replacements_name, "IMPORT.txt", "Book_Quality_Summary.json",
            "WholeBook_RuVoice_AllOccurrences.tsv", "WholeBook_RuVoice_UniqueWords.tsv",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверить и упаковать пользовательские словари RuVoice для книги")
    parser.add_argument("--book", type=Path, required=True)
    parser.add_argument("--quality-dir", type=Path, required=True)
    parser.add_argument("--replacements", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = package(book_path=args.book, quality_dir=args.quality_dir, replacements_path=args.replacements, output=args.output)
    print("RUVOICE_IMPORT_PACKAGE=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
