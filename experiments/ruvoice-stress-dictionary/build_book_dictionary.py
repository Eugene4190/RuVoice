#!/usr/bin/env python3
"""Build a book-specific RuVoice stress-dictionary supplement.

The built-in system dictionary and the cumulative approved list are read-only.
Only candidate entries that occur in this book and have upstream AOT/Wiktionary
consensus (or a curated source) are emitted. They remain provisional until reviewed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from analyze_book import WORD_RE, extract_text, parse_dictionary
from build_dictionary import Entry, validate_entry, write_dictionary

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
DEFAULT_SYSTEM = (
    REPO_ROOT / "project/ruvoice-1.1.3-stage4.9/app/src/main/assets/"
    "dicts/stress/Системный.txt"
)
DEFAULT_APPROVED = HERE / "data/approved/RuVoice_Accumulated_Approved.txt"
DEFAULT_POOL = HERE / "output/RuVoice_AutoStress.txt"
DEFAULT_AUDIT = HERE / "reports/RuVoice_AutoStress_accepted.tsv"
DEFAULT_RULES = HERE / "data/curated/book_candidate_review_rules.tsv"
ALLOWED_SOURCES = {"aot_wiktionary_silero_consensus", "curated_manual_reviewed"}
WORD_ONLY_RE = re.compile(r"[а-яё]+")
VOWELS = set("аеёиоуыэюя")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def norm(value: str) -> str:
    return value.lower().replace("ё", "е")


def load_dictionary(path: Path) -> tuple[dict[str, str], set[str]]:
    entries, conflicts = parse_dictionary(path)
    conflict_keys: set[str] = set()
    for row in conflicts:
        match = re.search(r": ([а-яё]+):", row)
        if match:
            conflict_keys.add(match.group(1))
    return entries, conflict_keys


def normalized_index(entries: dict[str, str]) -> dict[str, list[tuple[str, str]]]:
    index: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for word, marked in entries.items():
        index[norm(word)].append((word, marked))
    return index


def orthographic_alias_review_reason(
    word: str, normalized_rows: list[tuple[str, str]]
) -> str | None:
    """Return a review reason when е/ё-only aliases could change the stress."""
    exact_rows = [(form, marked) for form, marked in normalized_rows if form == word]
    aliases = [(form, marked) for form, marked in normalized_rows if form != word]
    if not aliases:
        return None
    if not exact_rows:
        forms = ", ".join(sorted({form for form, _ in aliases}))
        return (
            f"найдено только написание е/ё-алиаса ({forms}); точная словоформа {word} "
            "не подтверждена, автоматический перенос запрещён"
        )

    def stress_position(marked: str) -> int:
        marker = marked.index("+")
        return sum(char in VOWELS for char in marked[:marker])

    exact_positions = {stress_position(marked) for _, marked in exact_rows}
    alias_positions = {stress_position(marked) for _, marked in aliases}
    differing = alias_positions - exact_positions
    if differing:
        forms = ", ".join(sorted({form for form, _ in aliases}))
        return (
            f"написание е/ё-алиаса ({forms}) имеет другое положение ударения "
            f"({sorted(differing)}) чем точная форма ({sorted(exact_positions)})"
        )
    return None


def orthographic_alias_conflict_reason(word: str, conflict_forms: set[str]) -> str | None:
    """Hold a form when an е/ё alias was removed from a source due to conflict."""
    aliases = sorted(
        form for form in conflict_forms
        if form != word and norm(form) == norm(word)
    )
    if not aliases:
        return None
    return (
        "у е/ё-алиаса есть конфликтующие записи ("
        + ", ".join(aliases)
        + "); автоматический перенос запрещён"
    )


def load_provenance(path: Path) -> dict[str, tuple[str, str]]:
    """Keep exact spelling, marked form and source together for every candidate."""
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        data_lines = (line for line in stream if not line.lstrip().startswith("#"))
        reader = csv.DictReader(data_lines, delimiter="\t")
        required = {"word", "stress", "source"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"Некорректный аудит источников: {path}")
        result: dict[str, tuple[str, str]] = {}
        for row in reader:
            word = (row.get("word") or "").strip().lower()
            marked = (row.get("stress") or "").strip().lower()
            source = (row.get("source") or "").strip()
            if not word or source not in ALLOWED_SOURCES:
                continue
            reason = validate_entry(word, marked)
            if reason:
                raise ValueError(
                    f"Некорректное ударение в provenance для {word}: {marked!r}: {reason}"
                )
            current = (marked, source)
            previous = result.get(word)
            if previous is not None and previous != current:
                raise ValueError(
                    f"Конфликт provenance для точной формы {word}: {previous} / {current}"
                )
            result[word] = current
    return result


def load_candidate_rules(path: Path) -> dict[str, tuple[str, str, str]]:
    rules: dict[str, tuple[str, str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        required = {"word", "action", "reason", "source"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"Некорректные правила контекстной проверки: {path}")
        for row in reader:
            word = (row.get("word") or "").strip().lower()
            action = (row.get("action") or "").strip()
            reason = (row.get("reason") or "").strip()
            source = (row.get("source") or "").strip()
            if not word:
                continue
            if action not in {"WITHHOLD_UNSTRESSED", "CONTEXT_REVIEW"}:
                raise ValueError(f"Неизвестное действие для {word}: {action}")
            if word in rules:
                raise ValueError(f"Повторное правило для точной словоформы {word}")
            rules[word] = (action, reason, source)
    return rules


def adapt_marked_form(book_word: str, source_marked: str) -> str:
    """Preserve the source stress position but use the book's е/ё spelling."""
    marked_source = source_marked.lower()
    position = marked_source.index("+")
    bare_source = marked_source.replace("+", "")
    if len(bare_source) != len(book_word):
        raise ValueError("Нельзя сопоставить длину словоформ")
    proposed = book_word[:position] + "+" + book_word[position:]
    reason = validate_entry(book_word, proposed)
    if reason:
        raise ValueError(reason)
    return proposed


def make_output_dir(book: Path, book_hash: str) -> Path:
    safe_stem = re.sub(r"[^a-zA-Zа-яА-ЯёЁ0-9._-]+", "_", book.stem).strip("._-")
    safe_stem = safe_stem[:60] or "book"
    return HERE / "output" / "books" / f"{safe_stem}-{book_hash[:10]}"


def build(args: argparse.Namespace) -> int:
    candidate_rules_path = getattr(args, "candidate_rules", DEFAULT_RULES)
    paths = [args.book, args.system_dictionary, args.approved_dictionary,
             args.candidate_dictionary, args.candidate_audit, candidate_rules_path]
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"Не найден обязательный файл: {path}")

    book_text = extract_text(args.book)
    tokens = [match.group(0).lower() for match in WORD_RE.finditer(book_text)]
    counts = Counter(tokens)

    system, system_conflicts = load_dictionary(args.system_dictionary)
    approved, approved_conflicts = load_dictionary(args.approved_dictionary)
    pool, pool_conflicts = load_dictionary(args.candidate_dictionary)
    provenance = load_provenance(args.candidate_audit)
    candidate_rules = load_candidate_rules(candidate_rules_path)

    system_idx = normalized_index(system)
    approved_idx = normalized_index(approved)
    pool_idx = normalized_index(pool)
    known_idx: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for entries in (system, approved, pool):
        for known_word, marked in entries.items():
            known_idx[norm(known_word)].append((known_word, marked))

    # Provenance is attached only to the exact spelling in the audit and pool.
    # A normalized е/ё alias must never inherit another form's source label.
    eligible_pool: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for word, (provenance_stress, source) in provenance.items():
        marked = pool.get(word)
        if marked is None:
            continue
        if marked != provenance_stress:
            raise ValueError(
                f"Provenance stress mismatch for {word}: audit={provenance_stress!r}, pool={marked!r}"
            )
        eligible_pool[word].append((word, marked, source))

    candidates: list[Entry] = []
    review_rows: list[list[object]] = []
    unresolved_rows: list[list[object]] = []
    already_system_tokens = 0
    already_approved_tokens = 0
    book_approved_entries: list[Entry] = []
    new_candidate_tokens = 0
    conflict_tokens = 0
    conflict_forms = 0
    withheld_rule_tokens = 0
    withheld_rule_forms = 0
    hyphenated_forms = 0

    for word, frequency in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        if "-" in word or not WORD_ONLY_RE.fullmatch(word):
            hyphenated_forms += 1
            unresolved_rows.append([word, frequency, "составная/дефисная форма; автоматически не разбирается"])
            continue

        key = norm(word)
        conflicted_alias_reason = orthographic_alias_conflict_reason(
            word, system_conflicts | approved_conflicts | pool_conflicts
        )
        alias_reason = (
            conflicted_alias_reason
            or orthographic_alias_review_reason(word, known_idx.get(key, []))
        )
        if alias_reason:
            aliases = sorted(
                {form for form, _ in known_idx.get(key, []) if form != word}
                | {
                    form for form in system_conflicts | approved_conflicts | pool_conflicts
                    if form != word and norm(form) == key
                }
            )
            review_rows.append([
                word, frequency, " / ".join(aliases), "ORTHOGRAPHY_ALIAS_REVIEW", alias_reason
            ])
            conflict_tokens += frequency
            conflict_forms += 1
            continue

        base_rows = [(word, system[word])] if word in system else []
        approved_rows = [(word, approved[word])] if word in approved else []
        pool_rows = eligible_pool.get(word, [])

        if word in system_conflicts:
            review_rows.append([word, frequency, "", "CONFLICT", "во встроенном словаре есть конфликтующая или некорректная запись"])
            conflict_tokens += frequency
            conflict_forms += 1
            continue
        if len(base_rows) > 1:
            variants = {norm(marked) for _, marked in base_rows}
            if len(variants) > 1:
                review_rows.append([word, frequency, "", "CONFLICT", "во встроенном словаре конфликт после нормализации е/ё"])
                conflict_tokens += frequency
                conflict_forms += 1
                continue
        if base_rows:
            already_system_tokens += frequency
            continue

        if word in approved_conflicts:
            review_rows.append([word, frequency, "", "CONFLICT", "в накопительном словаре есть конфликтующая или некорректная запись"])
            conflict_tokens += frequency
            conflict_forms += 1
            continue
        if len(approved_rows) > 1 and len({norm(marked) for _, marked in approved_rows}) > 1:
            review_rows.append([word, frequency, "", "CONFLICT", "накопительный словарь содержит конфликтующие ударения"])
            conflict_tokens += frequency
            conflict_forms += 1
            continue
        if approved_rows:
            # The approved master is append-only: a later book/source may
            # disagree, but it must never silently replace the stored entry.
            pool_marked = pool.get(word)
            if word in pool_conflicts or (
                pool_marked is not None and norm(pool_marked) != norm(approved_rows[0][1])
            ):
                proposed = pool_marked or " / ".join(
                    sorted(marked for _, marked, _ in pool_rows)
                )
                review_rows.append([
                    word, frequency, proposed, "ACCUMULATED_MASTER_CONFLICT",
                    "новое предложение источника расходится с уже утверждённой записью; "
                    "старое ударение сохранено без перезаписи",
                ])
                conflict_tokens += frequency
                conflict_forms += 1
                continue
            already_approved_tokens += frequency
            try:
                approved_marked = adapt_marked_form(word, approved_rows[0][1])
            except (ValueError, IndexError) as exc:
                review_rows.append([word, frequency, approved_rows[0][1], "INVALID_APPROVED", str(exc)])
                conflict_tokens += frequency
                conflict_forms += 1
                continue
            book_approved_entries.append(Entry(word, approved_marked, "accumulated_approved", f"book_frequency={frequency}"))
            continue

        if word in pool_conflicts:
            review_rows.append([word, frequency, "", "CONFLICT", "пул кандидатов содержит конфликтующую или некорректную запись"])
            conflict_tokens += frequency
            conflict_forms += 1
            continue

        rule = candidate_rules.get(word)
        if rule:
            action, reason, source_url = rule
            review_rows.append([word, frequency, "", action, reason + (f" Source: {source_url}" if source_url else "")])
            withheld_rule_forms += 1
            withheld_rule_tokens += frequency
            continue

        variants = {norm(marked): marked for _, marked, _ in pool_rows}
        if len(variants) > 1:
            rendered = " / ".join(sorted(variants.values()))
            review_rows.append([word, frequency, rendered, "CONFLICT", "источники-кандидаты дают разные ударения"])
            conflict_tokens += frequency
            conflict_forms += 1
            continue
        if not pool_rows:
            unresolved_rows.append([word, frequency, "нет подтверждённой записи в пуле AOT/Wiktionary"])
            continue

        _, source_marked, source = pool_rows[0]
        try:
            proposed = adapt_marked_form(word, source_marked)
        except (ValueError, IndexError) as exc:
            review_rows.append([word, frequency, source_marked, "INVALID", str(exc)])
            conflict_tokens += frequency
            conflict_forms += 1
            continue

        candidates.append(Entry(word, proposed, source, f"book_frequency={frequency}"))
        new_candidate_tokens += frequency

    # The provisional combined export is explicitly marked and must not be
    # mistaken for an approved/import-ready list.
    approved_entries = [
        Entry(word, marked, "accumulated_approved")
        for word, marked in sorted(approved.items())
    ]
    provisional_entries = approved_entries + candidates

    output_dir = args.output_dir or make_output_dir(args.book, sha256(args.book))
    output_dir.mkdir(parents=True, exist_ok=True)

    candidate_txt = output_dir / "Book_AutoStress_Candidates.txt"
    write_dictionary(candidate_txt, candidates)

    candidate_review_tsv = output_dir / "Book_AutoStress_Candidate_Review.tsv"
    with candidate_review_tsv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(["word", "proposed_stress", "frequency_in_book", "source", "status"])
        for entry in candidates:
            frequency = entry.note.split("=", 1)[1] if "=" in entry.note else ""
            writer.writerow([entry.word, entry.marked, frequency, entry.source, "UNREVIEWED"])

    book_approved_txt = output_dir / "Book_Approved_Additions.txt"
    write_dictionary(book_approved_txt, book_approved_entries)

    cumulative_export = output_dir / "RuVoice_Accumulated_Approved.txt"
    write_dictionary(cumulative_export, approved_entries)

    provisional_txt = output_dir / "Book_Stress_Dictionary_PROVISIONAL_DO_NOT_IMPORT.txt"
    write_dictionary(provisional_txt, provisional_entries)
    content = provisional_txt.read_text(encoding="utf-8")
    provisional_txt.write_text(
        "# PROVISIONAL: review Book_AutoStress_Review.tsv before importing.\n" + content,
        encoding="utf-8",
    )

    review_tsv = output_dir / "Book_AutoStress_Review.tsv"
    with review_tsv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(["word", "frequency_in_book", "proposed_stress", "status", "reason"])
        writer.writerows(review_rows)

    unresolved_tsv = output_dir / "Book_Unresolved_Words.tsv"
    with unresolved_tsv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(["word", "frequency_in_book", "reason"])
        writer.writerows(unresolved_rows)

    total = len(tokens)
    unique = len(counts)
    report = {
        "book": args.book.name,
        "book_sha256": sha256(args.book),
        "system_dictionary": str(args.system_dictionary),
        "system_dictionary_sha256": sha256(args.system_dictionary),
        "approved_dictionary": str(args.approved_dictionary),
        "approved_dictionary_sha256": sha256(args.approved_dictionary),
        "candidate_pool_sha256": sha256(args.candidate_dictionary),
        "candidate_provenance_sha256": sha256(args.candidate_audit),
        "candidate_rules_sha256": sha256(candidate_rules_path),
        "total_word_tokens": total,
        "unique_word_forms": unique,
        "already_in_system_tokens": already_system_tokens,
        "already_in_approved_supplement_tokens": already_approved_tokens,
        "new_candidate_forms": len(candidates),
        "new_candidate_tokens": new_candidate_tokens,
        "conflict_forms": conflict_forms,
        "conflict_tokens": conflict_tokens,
        "withheld_by_context_rules_forms": withheld_rule_forms,
        "withheld_by_context_rules_tokens": withheld_rule_tokens,
        "unresolved_forms": len(unresolved_rows),
        "hyphenated_or_compound_forms": hyphenated_forms,
        "cumulative_approved_entries": len(approved_entries),
        "provisional_combined_entries": len(provisional_entries),
        "candidate_source_policy": sorted(ALLOWED_SOURCES),
        "warning": "Book candidates are not approved corrections. Review every candidate in context; missing dictionary entries do not prove a model error.",
    }
    (output_dir / "Book_Report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Дополнения этой книги, уже утверждённые ранее: {book_approved_txt}")
    print(f"Полный накопительный утверждённый словарь: {cumulative_export}")
    print(f"Кандидаты для проверки: {candidate_txt}")
    print(f"Таблица проверки кандидатов: {candidate_review_tsv}")
    print(f"Отчёт проверки: {review_tsv}")
    print(f"Неизвестные формы: {unresolved_tsv}")
    print(f"Временный объединённый файл (НЕ ИМПОРТИРОВАТЬ): {provisional_txt}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Создать дополнение к словарю RuVoice только по словам из конкретной книги"
    )
    parser.add_argument("book", type=Path, help="книга EPUB, TXT или HTML")
    parser.add_argument("--system-dictionary", type=Path, default=DEFAULT_SYSTEM)
    parser.add_argument("--approved-dictionary", type=Path, default=DEFAULT_APPROVED)
    parser.add_argument("--candidate-dictionary", type=Path, default=DEFAULT_POOL)
    parser.add_argument("--candidate-audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--candidate-rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    try:
        return build(args)
    except (OSError, ValueError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
