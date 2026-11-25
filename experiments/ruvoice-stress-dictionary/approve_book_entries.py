#!/usr/bin/env python3
"""Append explicitly approved book-specific entries to the cumulative RuVoice list.

This tool is deliberately append-only: it never replaces or deletes an existing
approved row, and it aborts before writing if a selected entry is unknown or
conflicts with the built-in or cumulative dictionary.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from analyze_book import parse_dictionary
from build_book_dictionary import (
    DEFAULT_APPROVED,
    DEFAULT_SYSTEM,
    load_dictionary,
    norm,
    orthographic_alias_conflict_reason,
    orthographic_alias_review_reason,
)
from build_dictionary import validate_entry


def read_selected_words(path: Path) -> list[str]:
    rows: list[str] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        value = line.split("#", 1)[0].strip().lower()
        if value:
            if not re.fullmatch(r"[а-яё]+", value):
                raise ValueError(f"Некорректное слово в списке утверждения: {value!r}")
            rows.append(value)
    if len(set(rows)) != len(rows):
        raise ValueError("В списке утверждения есть повторяющиеся точные словоформы")
    return rows


def build(args: argparse.Namespace) -> int:
    for path in (args.candidate_file, args.approve_words, args.system_dictionary, args.approved_dictionary):
        if not path.is_file():
            raise FileNotFoundError(f"Не найден обязательный файл: {path}")

    candidate, candidate_conflicts = load_dictionary(args.candidate_file)
    system, system_conflicts = load_dictionary(args.system_dictionary)
    approved, approved_conflicts = load_dictionary(args.approved_dictionary)

    bad_candidate_keys = {
        match.group(1)
        for row in candidate_conflicts
        if (match := re.search(r": ([а-яё]+):", row))
    }
    selected = read_selected_words(args.approve_words)
    candidate_idx: dict[str, list[tuple[str, str]]] = {}
    for word, marked in candidate.items():
        candidate_idx.setdefault(norm(word), []).append((word, marked))
    system_idx: dict[str, list[tuple[str, str]]] = {}
    for word, marked in system.items():
        system_idx.setdefault(norm(word), []).append((word, marked))
    approved_idx: dict[str, list[tuple[str, str]]] = {}
    for word, marked in approved.items():
        approved_idx.setdefault(norm(word), []).append((word, marked))

    additions: list[tuple[str, str]] = []
    already_present: list[str] = []
    errors: list[str] = []

    for requested in selected:
        key = norm(requested)
        if requested in bad_candidate_keys:
            errors.append(f"{requested}: в файле кандидатов конфликтующие варианты")
            continue

        # Normalized е/ё matches are collision signals, never proof that the
        # requested exact spelling exists in a dictionary source.
        alias_issues: list[str] = []
        for source_name, index, conflicts in (
            ("файле кандидатов", candidate_idx, bad_candidate_keys),
            ("системном словаре", system_idx, system_conflicts),
            ("накопительном словаре", approved_idx, approved_conflicts),
        ):
            rows = index.get(key, [])
            reason = orthographic_alias_review_reason(requested, rows)
            if reason:
                alias_issues.append(f"{source_name}: {reason}")
            conflict_reason = orthographic_alias_conflict_reason(requested, conflicts)
            if conflict_reason:
                alias_issues.append(f"{source_name}: {conflict_reason}")
        if alias_issues:
            errors.append(
                f"{requested}: е/ё-совпадение требует отдельной проверки: "
                + "; ".join(alias_issues)
            )
            continue

        exact_matches = [
            (word, marked) for word, marked in candidate_idx.get(key, [])
            if word == requested
        ]
        if len(exact_matches) != 1:
            errors.append(
                f"{requested}: точная словоформа не найдена однозначно "
                "в файле кандидатов; е/ё-алиас не считается совпадением"
            )
            continue
        candidate_word, marked = exact_matches[0]
        reason = validate_entry(candidate_word, marked)
        if reason:
            errors.append(f"{requested}: некорректная запись: {reason}")
            continue

        if requested in system_conflicts:
            errors.append(f"{requested}: во встроенном системном словаре есть конфликтующая или некорректная запись")
            continue
        existing_system = system.get(requested)
        if existing_system is not None:
            if norm(existing_system) != norm(marked):
                errors.append(f"{requested}: ударение расходится со встроенным словарём")
            else:
                already_present.append(requested)
            continue

        if requested in approved_conflicts:
            errors.append(f"{requested}: в накопительном словаре есть конфликтующая или некорректная запись")
            continue
        existing_approved = approved.get(requested)
        if existing_approved is not None:
            if norm(existing_approved) != norm(marked):
                errors.append(f"{requested}: ударение расходится с накопительным словарём")
            else:
                already_present.append(requested)
            continue

        additions.append((candidate_word, marked))
    if errors:
        raise ValueError("Ничего не добавлено. Исправьте список утверждения:\n- " + "\n- ".join(errors))

    # Append only. The old file bytes/content are left intact.
    if additions:
        with args.approved_dictionary.open("a", encoding="utf-8", newline="\n") as stream:
            original = args.approved_dictionary.read_text(encoding="utf-8-sig")
            if original and not original.endswith(("\n", "\r")):
                stream.write("\n")
            stream.write(f"\n# Approved additions from {args.candidate_file.name}\n")
            for word, marked in sorted(additions):
                stream.write(f"{word} {marked}\n")

    report = {
        "candidate_file": args.candidate_file.name,
        "approved_words_file": args.approve_words.name,
        "approved_dictionary": str(args.approved_dictionary),
        "selected_count": len(selected),
        "added_count": len(additions),
        "already_present_count": len(already_present),
        "already_present": already_present,
        "append_only": True,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    report_path = args.report or args.approved_dictionary.parent / "last_approval_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Добавить только выбранные проверенные записи в накопительный словарь")
    parser.add_argument("--candidate-file", type=Path, required=True, help="Book_AutoStress_Candidates.txt")
    parser.add_argument("--approve-words", type=Path, required=True, help="UTF-8: одно утверждённое слово на строку")
    parser.add_argument("--system-dictionary", type=Path, default=DEFAULT_SYSTEM)
    parser.add_argument("--approved-dictionary", type=Path, default=DEFAULT_APPROVED)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        return build(args)
    except (OSError, ValueError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
