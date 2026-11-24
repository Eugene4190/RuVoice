#!/usr/bin/env python3
"""Build an importable RuVoice stress dictionary from independent candidate lists.

Input rows use the upstream format: word = stressed+word # note
Output rows use RuVoice's import format: word stressed+word
Only the standard library is required.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

VOWELS = set("аеёиоуыэюя")
WORD_RE = re.compile(r"^[а-яё]+$", re.IGNORECASE)
ASSIGN_RE = re.compile(r"^\s*([^=]+?)\s*=\s*(\S+)(?:\s+#\s*(.*))?\s*$")
COUNT_RE = re.compile(r"^\s*(\d+)\s*(?:,|$)")


@dataclass(frozen=True)
class Entry:
    word: str
    marked: str
    source: str
    note: str = ""
    observations: int | None = None


@dataclass(frozen=True)
class Rejected:
    word: str
    marked: str
    source: str
    reason: str
    note: str = ""
    observations: int | None = None


def normalize_yo(value: str) -> str:
    return value.replace("ё", "е")


def validate_entry(word: str, marked: str) -> str | None:
    word, marked = word.lower(), marked.lower()
    if not WORD_RE.fullmatch(word):
        return "ключ должен быть одним русским словом"
    if not re.fullmatch(r"[а-яё+]+", marked):
        return "вариант должен содержать только русские буквы и знак +"
    if marked.count("+") != 1:
        return "нужно ровно одно обозначение ударения +"
    pos = marked.index("+")
    bare = marked.replace("+", "")
    if pos >= len(bare) or bare[pos] not in VOWELS:
        return "знак + должен стоять непосредственно перед гласной"
    if normalize_yo(word) != normalize_yo(bare):
        return "ключ и вариант должны обозначать ту же словоформу (е/ё допускается)"
    if sum(ch in VOWELS for ch in bare) < 2:
        return "у слова только один слог; отдельная поправка не нужна"
    return None


def parse_assignment(line: str) -> tuple[str, str, str] | None:
    if not line.strip() or line.lstrip().startswith("#"):
        return None
    match = ASSIGN_RE.match(line.rstrip("\r\n"))
    if not match:
        return None
    word, marked, note = match.groups()
    return word.strip().lower(), marked.strip().lower(), (note or "").strip()


def read_source_list(path: Path, label: str) -> tuple[list[Entry], list[Rejected]]:
    accepted: list[Entry] = []
    rejected: list[Rejected] = []
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path}: ожидается UTF-8: {exc}") from exc
    for number, line in enumerate(lines, 1):
        parsed = parse_assignment(line)
        if not parsed:
            continue
        word, marked, note = parsed
        reason = validate_entry(word, marked)
        if reason:
            rejected.append(Rejected(word, marked, label, f"строка {number}: {reason}", note))
        else:
            accepted.append(Entry(word, marked, label, note))
    return accepted, rejected


def read_consensus_candidates(path: Path, minimum: int) -> tuple[list[Entry], list[Rejected]]:
    accepted: list[Entry] = []
    rejected: list[Rejected] = []
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path}: ожидается UTF-8: {exc}") from exc
    for number, line in enumerate(lines, 1):
        parsed = parse_assignment(line)
        if not parsed:
            continue
        word, marked, note = parsed
        count = COUNT_RE.match(note)
        observations = int(count.group(1)) if count else None
        reason = validate_entry(word, marked)
        if reason:
            rejected.append(Rejected(word, marked, "stress_candidates", f"строка {number}: {reason}", note, observations))
        elif observations is None:
            rejected.append(Rejected(word, marked, "stress_candidates", f"строка {number}: нет числа контекстов", note))
        elif observations < minimum:
            rejected.append(Rejected(word, marked, "stress_candidates",
                                     f"только {observations} контекст(а/ов), требуется {minimum}", note, observations))
        else:
            accepted.append(Entry(word, marked, "stress_candidates", note, observations))
    return accepted, rejected


def read_review_only(path: Path) -> tuple[list[Entry], list[Rejected]]:
    rows, rejected = read_source_list(path, "build3_review_only")
    rejected.extend(Rejected(e.word, e.marked, e.source,
                             "официальный build3 помечает запись как требующую просмотра; в авто-словарь не включена",
                             e.note) for e in rows)
    return [], rejected


def merge_entries(source_groups: list[list[Entry]], candidates: list[Entry]) -> tuple[list[Entry], list[Rejected]]:
    rejected: list[Rejected] = []
    by_word: dict[str, list[Entry]] = defaultdict(list)
    for group in source_groups:
        for entry in group:
            by_word[entry.word].append(entry)

    selected: dict[str, Entry] = {}
    for word, group in by_word.items():
        variants = {entry.marked for entry in group}
        if len(variants) > 1:
            rejected.append(Rejected(word, " / ".join(sorted(variants)), "trusted_sources",
                                     "исходные списки расходятся; запись отложена"))
            continue
        selected[word] = group[-1]

    candidate_groups: dict[str, list[Entry]] = defaultdict(list)
    for entry in candidates:
        candidate_groups[entry.word].append(entry)
    for word, group in candidate_groups.items():
        variants = {entry.marked for entry in group}
        if len(variants) > 1:
            rejected.append(Rejected(word, " / ".join(sorted(variants)), "stress_candidates",
                                     "разные ударения в кандидатах; автоматически не выбрано"))
            continue
        candidate = max(group, key=lambda e: e.observations or 0)
        existing = selected.get(word)
        if existing:
            if existing.marked != candidate.marked:
                rejected.append(Rejected(word, candidate.marked, candidate.source,
                                         f"конфликт с источником {existing.source}: {existing.marked}; сохранён источник"))
            continue
        selected[word] = candidate

    return sorted(selected.values(), key=lambda entry: entry.word), rejected


def write_dictionary(path: Path, entries: Iterable[Entry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("# RuVoice user stress dictionary\n")
        stream.write("# Format: word stressed+word. Import into the Stress dictionaries tab.\n")
        for entry in entries:
            stream.write(f"{entry.word} {entry.marked}\n")


def write_report(path: Path, rows: Iterable[Rejected]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(["word", "stress", "source", "reason", "observations", "note"])
        for row in rows:
            writer.writerow([row.word, row.marked, row.source, row.reason,
                             row.observations if row.observations is not None else "", row.note])


def build(args: argparse.Namespace) -> int:
    if not args.source_list and not args.candidates and not args.review_candidates:
        print("Укажите хотя бы один источник: --source-list, --candidates или --review-candidates", file=sys.stderr)
        return 2

    source_groups: list[list[Entry]] = []
    rejected: list[Rejected] = []
    source_count = 0
    for path in args.source_list:
        rows, bad = read_source_list(path, path.name)
        source_groups.append(rows)
        rejected.extend(bad)
        source_count += len(rows)

    candidates: list[Entry] = []
    if args.candidates:
        rows, bad = read_consensus_candidates(args.candidates, args.min_observations)
        candidates.extend(rows)
        rejected.extend(bad)
    if args.review_candidates:
        _, bad = read_review_only(args.review_candidates)
        rejected.extend(bad)

    merged, conflicts = merge_entries(source_groups, candidates)
    rejected.extend(conflicts)
    write_dictionary(args.output, merged)
    write_report(args.report, rejected)

    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "output": str(args.output),
        "review_report": str(args.report),
        "entry_count": len(merged),
        "source_entry_count": source_count,
        "automatic_candidate_count": sum(1 for e in merged if e.source == "stress_candidates"),
        "withheld_or_rejected_count": len(rejected),
        "minimum_candidate_observations": args.min_observations,
        "inputs": [str(p) for p in args.source_list]
                  + ([str(args.candidates)] if args.candidates else [])
                  + ([str(args.review_candidates)] if args.review_candidates else []),
        "warning": "Observation counts are not calibrated probabilities. Validate against real text before relying on every entry."
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"В словаре: {len(merged)}")
    print(f"Из исходных списков: {source_count}")
    print(f"Автоматических консенсусных: {manifest['automatic_candidate_count']}")
    print(f"Отложено/отклонено: {len(rejected)}")
    print(f"Словарь: {args.output}")
    print(f"Отчёт: {args.report}")
    print(f"Манифест: {args.manifest}")
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Сборка импортируемого пользовательского словаря ударений RuVoice")
    parser.add_argument("--source-list", type=Path, action="append", default=[],
                        help="проверенный список в формате word = stressed+word; можно указать несколько раз")
    parser.add_argument("--candidates", type=Path,
                        help="stress_candidates.txt из официального stress_compare.py")
    parser.add_argument("--review-candidates", type=Path,
                        help="stress_fixes_new.txt из build3; всегда только отчёт, не авто-словарь")
    parser.add_argument("--min-observations", type=int, default=3,
                        help="минимальное число контекстов для stress_candidates (по умолчанию 3)")
    parser.add_argument("--output", type=Path, default=Path("output/RuVoice_AutoStress.txt"))
    parser.add_argument("--report", type=Path, default=Path("reports/RuVoice_AutoStress_review.tsv"))
    parser.add_argument("--manifest", type=Path, default=Path("reports/run_manifest.json"))
    return parser


def main() -> int:
    parser = make_parser()
    args = parser.parse_args()
    if args.min_observations < 1:
        parser.error("--min-observations должен быть не меньше 1")
    try:
        return build(args)
    except (OSError, ValueError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
