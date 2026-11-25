#!/usr/bin/env python3
"""Private, cumulative book-to-RuVoice workflow.

User books and the append-only master dictionary live outside the repository,
under ~/.ruvoice-book-workflow (or RUVOICE_PRIVATE_HOME). Only source-vetted
book candidates that survive the builder's context, spelling and conflict
filters are appended. Every book gets a ZIP with its new delta and full snapshot.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import approve_book_entries
import build_book_dictionary
from analyze_book import extract_text, parse_dictionary
from build_dictionary import Entry, write_dictionary

HERE = Path(__file__).resolve().parent
DEFAULT_PRIVATE_HOME = Path(
    os.environ.get("RUVOICE_PRIVATE_HOME", str(Path.home() / ".ruvoice-book-workflow"))
)
_LOCK = threading.RLock()
MASTER_NAME = "RuVoice_Accumulated_Approved.txt"
STATE_NAME = "book_history.json"
PENDING_NAME = "pending_approval.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Zа-яА-ЯёЁ0-9._-]+", "_", value).strip("._-")
    return (cleaned[:64] or "book")


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _ensure_private_store(root: Path) -> tuple[Path, Path, Path]:
    _private_dir(root)
    state_dir = root / "state"
    work_dir = root / "work"
    package_dir = root / "packages"
    for folder in (state_dir, work_dir, package_dir):
        _private_dir(folder)
    master = root / MASTER_NAME
    if not master.exists():
        _atomic_text(
            master,
            "# Личный накопительный словарь RuVoice. Хранится только в приватной папке пользователя.\n"
            "# Формат: точная словоформа пробел форма с + перед ударной гласной.\n"
            "# Записи добавляются автоматически только после строгих source/context/conflict-фильтров.\n",
        )
    history = state_dir / STATE_NAME
    if not history.exists():
        _atomic_json(history, {"schema_version": 1, "books": {}})
    return master, state_dir, package_dir


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Некорректный JSON state: {path}")
    return value


def _record_book(state: dict[str, Any], pending: dict[str, Any]) -> None:
    state.setdefault("schema_version", 1)
    state.setdefault("books", {})
    state.setdefault("entries", {})
    digest = pending["book_sha256"]
    book_name = pending["book_name"]
    state["books"][digest] = {
        "book_name": book_name,
        "processed_utc": pending["created_utc"],
        "new_entries": pending.get("new_entries", []),
        "encountered_master_entries": state["books"].get(digest, {}).get(
            "encountered_master_entries", []
        ),
    }
    for row in pending.get("new_entries", []):
        word = row["word"]
        entry = state["entries"].setdefault(word, {
            "stress": row["stress"],
            "source": row.get("source", "source-provenance-not-recorded"),
            "first_added_in": book_name,
            "first_added_book_sha256": digest,
            "books_seen_in": [],
        })
        if entry.get("stress") != row["stress"]:
            raise ValueError(
                f"История provenance содержит конфликт для {word}: "
                f"{entry.get('stress')} / {row['stress']}"
            )


def _record_book_occurrences(
    state: dict[str, Any],
    *,
    book_sha256: str,
    book_name: str,
    encountered: list[dict[str, str]],
) -> None:
    state.setdefault("entries", {})
    record = state.setdefault("books", {}).setdefault(book_sha256, {
        "book_name": book_name,
        "processed_utc": _utc_now(),
        "new_entries": [],
    })
    by_word = {row["word"]: row for row in record.get("encountered_master_entries", [])}
    for row in encountered:
        word, stress = row["word"], row["stress"]
        by_word[word] = {"word": word, "stress": stress}
        entry = state["entries"].setdefault(word, {
            "stress": stress,
            "source": "pre-existing-master-without-local-provenance",
            "first_added_in": None,
            "first_added_book_sha256": None,
            "books_seen_in": [],
        })
        if entry.get("stress") != stress:
            raise ValueError(
                f"Master и private provenance расходятся для {word}: "
                f"{entry.get('stress')} / {stress}"
            )
        seen = entry.setdefault("books_seen_in", [])
        if not any(item.get("book_sha256") == book_sha256 for item in seen):
            seen.append({"book_name": book_name, "book_sha256": book_sha256})
    record["encountered_master_entries"] = sorted(
        by_word.values(), key=lambda row: row["word"]
    )


def _approve_into_private_master(
    candidate_file: Path,
    selected_file: Path,
    system_dictionary: Path,
    master: Path,
    work_dir: Path,
) -> None:
    """Use the existing conflict validator against a staged copy, then swap atomically."""
    staged_master = work_dir / "master.staged.txt"
    approval_report = work_dir / "approval_report.json"
    shutil.copyfile(master, staged_master)
    try:
        approve_book_entries.build(
            SimpleNamespace(
                candidate_file=candidate_file,
                approve_words=selected_file,
                system_dictionary=system_dictionary,
                approved_dictionary=staged_master,
                report=approval_report,
            )
        )
        try:
            os.chmod(staged_master, 0o600)
        except OSError:
            pass
        os.replace(staged_master, master)
    finally:
        if staged_master.exists():
            staged_master.unlink()


def _recover_pending(root: Path, master: Path, system_dictionary: Path) -> None:
    state_dir = root / "state"
    pending_path = state_dir / PENDING_NAME
    if not pending_path.exists():
        return
    pending = _load_json(pending_path, {})
    work_dir = Path(pending["work_dir"])
    candidate_file = Path(pending["candidate_file"])
    selected_file = Path(pending["selected_file"])
    if not candidate_file.is_file() or not selected_file.is_file():
        raise RuntimeError(
            "Обнаружена незавершённая транзакция накопителя, но её приватные файлы отсутствуют: "
            + str(pending_path)
        )
    _approve_into_private_master(
        candidate_file, selected_file, system_dictionary, master, work_dir
    )
    history_path = state_dir / STATE_NAME
    history = _load_json(history_path, {"schema_version": 1, "books": {}})
    _record_book(history, pending)
    _atomic_json(history_path, history)
    pending_path.unlink(missing_ok=True)


def _replacement_rule_parts(line: str) -> tuple[str, str] | None:
    text = line.strip()
    if not text or text.startswith("#") or "=" not in text:
        return None
    left, right = text.split("=", 1)
    key, value = left.strip(), right.strip()
    if not key or not value:
        return None
    return key, value


def _literal_phrase_pattern(key: str) -> re.Pattern[str] | None:
    words = key.split()
    if len(words) < 2:
        return None
    if not all(re.fullmatch(r"[A-Za-zА-Яа-яЁё-]+", word) for word in words):
        return None
    return re.compile(
        r"(?<![\w])" + r"\s+".join(re.escape(word) for word in words) + r"(?![\w])",
        re.IGNORECASE | re.UNICODE,
    )


def _build_book_replacements(
    book: Path,
    *,
    prior_path: Path,
    user_path: Path | None,
) -> tuple[str, list[list[str]], int]:
    """Keep prior per-book rules, add matching reviewed phrases and explicit user rules."""
    book_text = extract_text(book)
    curated_path = HERE.parents[1] / "private-files/paired_eval/book_reviewed_replacements.txt"
    curated_lines = (
        curated_path.read_text(encoding="utf-8-sig").splitlines()
        if curated_path.is_file() else []
    )
    prior_lines = (
        prior_path.read_text(encoding="utf-8-sig").splitlines()
        if prior_path.is_file() else []
    )
    user_lines = (
        Path(user_path).read_text(encoding="utf-8-sig").splitlines()
        if user_path is not None else []
    )

    selected: list[str] = []
    by_key: dict[str, tuple[str, str]] = {}
    review: list[list[str]] = []
    auto_count = 0

    def add_lines(lines: list[str], source: str, *, auto_match: bool = False) -> None:
        nonlocal auto_count
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = _replacement_rule_parts(line)
            if parts is None:
                review.append([line, "", source, "INVALID_RULE", "ожидается строка «ключ = замена»"])
                continue
            key, value = parts
            if auto_match:
                pattern = _literal_phrase_pattern(key)
                if pattern is None or not pattern.search(book_text):
                    continue
            normalized_key = re.sub(r"\s+", " ", key.lower())
            previous = by_key.get(normalized_key)
            if previous is not None:
                if previous[0] != value:
                    review.append([
                        key, f"{previous[0]} <> {value}", source, "HELD_CONFLICT",
                        f"сохранено более раннее правило из источника {previous[1]}",
                    ])
                continue
            by_key[normalized_key] = (value, source)
            selected.append(line)
            if auto_match:
                auto_count += 1
            review.append([
                key, value, source, "INCLUDED",
                "буквальная фраза найдена в тексте книги" if auto_match
                else "явно приложенное или ранее сохранённое правило",
            ])

    # Earlier book-specific choices have the highest priority and are append-only.
    add_lines(prior_lines, "previously_saved_for_this_book")
    add_lines(curated_lines, "curated_reviewed_phrase", auto_match=True)
    add_lines(user_lines, "user_supplied_for_this_book")

    header = "# Контекстные замены только для этой книги. Не объединять с глобальным Системный.txt.\\n"
    content = header + "".join(line + "\n" for line in selected)
    return content, review, auto_count


def _write_replacement_review(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(["key", "replacement_or_conflict", "source", "status", "reason"])
        writer.writerows(rows)


def _write_import_guide(
    path: Path,
    book_name: str,
    delta_filename: str,
    replacement_filename: str,
    has_replacements: bool,
) -> None:
    replacement_text = (
        f"Импортируйте {replacement_filename} во вкладку «Замены» только если в файле есть правила. "
        "Правила остаются привязанными к этой книге."
        if has_replacements
        else f"Для этой книги отдельные контекстные замены не переданы; файл {replacement_filename} содержит только комментарий."
    )
    _atomic_text(
        path,
        (
            f"RuVoice — дополнение для книги: {book_name}\n\n"
            "1. Откройте RuVoice → «Ударения» → импорт TXT.\n"
            f"2. Импортируйте {delta_filename} отдельным списком с названием этой книги. "
            "Не удаляйте и не отключайте списки предыдущих книг. Если дельта пуста, новых слов для импорта нет.\n"
            f"3. {replacement_text}\n"
            "4. MyBooks_Cumulative.txt — полный резервный снимок вашего личного словаря. "
            "Это backup, а не команда заменить или удалить списки в RuVoice. Храните его отдельно.\n"
            "5. Откройте EPUB в RuVoice и проверьте чтение вместе с озвучкой. Сомнительные случаи перечислены в отчётах.\n\n"
            "Автоматически добавляются только точные словоформы, прошедшие разрешённую политику provenance, "
            "контекстные правила и проверки конфликтов. Конфликты с уже утверждённым накопителем не перезаписываются.\n"
        ),
    )


def process_book(
    book: Path,
    *,
    private_home: Path = DEFAULT_PRIVATE_HOME,
    system_dictionary: Path = build_book_dictionary.DEFAULT_SYSTEM,
    candidate_dictionary: Path = build_book_dictionary.DEFAULT_POOL,
    candidate_audit: Path = build_book_dictionary.DEFAULT_AUDIT,
    candidate_rules: Path = build_book_dictionary.DEFAULT_RULES,
    replacements: Path | None = None,
    book_name: str | None = None,
) -> dict[str, Any]:
    """Process one book privately and return a ZIP bundle plus a safe summary."""
    book = Path(book)
    display_name = (
        re.split(r"[/\\\\]", str(book_name))[-1]
        if book_name else book.name
    )
    if not book.is_file():
        raise FileNotFoundError(f"Книга не найдена: {book}")
    if book.suffix.lower() not in {".epub", ".txt", ".html", ".htm"}:
        raise ValueError("Поддерживаются EPUB, TXT и HTML")
    if replacements is not None and not Path(replacements).is_file():
        raise FileNotFoundError(f"Файл книжных замен не найден: {replacements}")
    for required in (system_dictionary, candidate_dictionary, candidate_audit, candidate_rules):
        if not Path(required).is_file():
            raise FileNotFoundError(f"Не найден обязательный файл pipeline: {required}")

    import hashlib

    digest_builder = hashlib.sha256()
    with book.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest_builder.update(chunk)
    digest = digest_builder.hexdigest()
    private_root = Path(private_home).expanduser().resolve()
    with _LOCK:
        master, state_dir, package_dir = _ensure_private_store(private_root)
        _recover_pending(private_root, master, Path(system_dictionary))
        history_path = state_dir / STATE_NAME
        history = _load_json(history_path, {"schema_version": 1, "books": {}})
        was_processed = digest in history.get("books", {})

        work_dir = private_root / "work" / digest
        _private_dir(work_dir)
        builder_output = work_dir / "builder"
        _private_dir(builder_output)
        args = SimpleNamespace(
            book=book,
            system_dictionary=Path(system_dictionary),
            approved_dictionary=master,
            candidate_dictionary=Path(candidate_dictionary),
            candidate_audit=Path(candidate_audit),
            candidate_rules=Path(candidate_rules),
            output_dir=builder_output,
        )
        build_book_dictionary.build(args)

        candidate_file = builder_output / "Book_AutoStress_Candidates.txt"
        candidates, candidate_conflicts = parse_dictionary(candidate_file)
        if candidate_conflicts:
            raise ValueError("Сборщик создал неоднозначный файл кандидатов: " + "; ".join(candidate_conflicts))
        candidate_meta: dict[str, dict[str, str]] = {}
        review_path = builder_output / "Book_AutoStress_Candidate_Review.tsv"
        with review_path.open("r", encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream, delimiter="\t"):
                candidate_meta[row["word"]] = row
        new_entries = [] if was_processed else [
            {
                "word": word,
                "stress": marked,
                "source": candidate_meta.get(word, {}).get("source", "source-provenance-not-recorded"),
                "frequency_in_book": int(candidate_meta.get(word, {}).get("frequency_in_book") or 0),
            }
            for word, marked in sorted(candidates.items())
        ]
        delta_text = "".join(f"{row['word']} {row['stress']}\n" for row in new_entries)
        if was_processed or not delta_text:
            delta_text = (
                "# Повторная обработка: книга уже учтена; новых записей нет.\n"
                if was_processed
                else "# Для этой книги новых безопасных записей нет.\n"
            )

        if not was_processed:
            selected_file = work_dir / "approve_words.txt"
            _atomic_text(selected_file, "".join(row["word"] + "\n" for row in new_entries))
            pending = {
                "book_sha256": digest,
                "book_name": display_name,
                "created_utc": _utc_now(),
                "new_entries": new_entries,
                "work_dir": str(work_dir),
                "candidate_file": str(candidate_file),
                "selected_file": str(selected_file),
            }
            pending_path = state_dir / PENDING_NAME
            _atomic_json(pending_path, pending)
            if new_entries:
                _approve_into_private_master(
                    candidate_file, selected_file, Path(system_dictionary), master, work_dir
                )
            history = _load_json(history_path, {"schema_version": 1, "books": {}})
            _record_book(history, pending)
            _atomic_json(history_path, history)
            pending_path.unlink(missing_ok=True)

        # Rebuild against the updated master so reports and per-book known forms
        # reflect the state that the user will actually have after this run.
        build_book_dictionary.build(args)
        approved_in_book, approved_conflicts_in_book = parse_dictionary(
            builder_output / "Book_Approved_Additions.txt"
        )
        if approved_conflicts_in_book:
            raise ValueError(
                "Неоднозначные ранее утверждённые записи в книге: "
                + "; ".join(approved_conflicts_in_book)
            )
        current_history = _load_json(
            history_path, {"schema_version": 1, "books": {}, "entries": {}}
        )
        _record_book_occurrences(
            current_history,
            book_sha256=digest,
            book_name=display_name,
            encountered=[
                {"word": word, "stress": marked}
                for word, marked in sorted(approved_in_book.items())
            ],
        )
        _atomic_json(history_path, current_history)
        book_stem = _safe_stem(Path(display_name).stem)
        delta_filename = f"{book_stem}_New_Stress_Delta.txt"
        delta_path = builder_output / delta_filename
        _atomic_text(delta_path, delta_text)
        snapshot_path = builder_output / "MyBooks_Cumulative.txt"
        shutil.copyfile(master, snapshot_path)

        replacement_filename = f"{book_stem}_Replacements.txt"
        replacement_path = builder_output / replacement_filename
        replacements_dir = private_root / "replacements"
        _private_dir(replacements_dir)
        replacement_store = replacements_dir / f"{digest}.txt"
        if replacements is not None and Path(replacements).suffix.lower() != ".txt":
            raise ValueError("Файл контекстных замен должен иметь расширение .txt")
        replacement_content, replacement_review_rows, auto_phrase_count = _build_book_replacements(
            book,
            prior_path=replacement_store,
            user_path=Path(replacements) if replacements is not None else None,
        )
        _atomic_text(replacement_store, replacement_content)
        shutil.copyfile(replacement_store, replacement_path)
        try:
            os.chmod(replacement_path, 0o600)
        except OSError:
            pass
        replacement_lines = [
            line for line in replacement_path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        has_replacements = bool(replacement_lines)
        replacement_review_path = builder_output / "Book_Replacements_Review.tsv"
        _write_replacement_review(replacement_review_path, replacement_review_rows)
        history = _load_json(history_path, {"schema_version": 1, "books": {}})
        book_record = history.setdefault("books", {}).setdefault(digest, {})
        book_record["replacements"] = {
            "private_file": replacement_store.name,
            "sha256": hashlib.sha256(replacement_store.read_bytes()).hexdigest(),
            "has_rules": has_replacements,
        }
        _atomic_json(history_path, history)

        report_path = builder_output / "Book_Report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        # Never put local home paths into a distributable report.
        for key in ("system_dictionary", "approved_dictionary"):
            report.pop(key, None)
        report["book"] = display_name
        report["warning"] = (
            "Automatically appended entries passed the configured exact-form, source-provenance, "
            "context-rule and conflict filters. The source policy is conservative but is not a guarantee "
            "of perfect pronunciation; inspect playback for unusual names and ambiguous forms. "
            "Conflicts with an existing approved master entry are held and never overwrite it."
        )
        report["workflow"] = {
            "book_sha256": digest,
            "already_processed_before_this_run": was_processed,
            "newly_approved_entries": new_entries,
            "newly_approved_count": len(new_entries),
            "cumulative_approved_count": len(parse_dictionary(master)[0]),
            "append_only": True,
            "private_storage": True,
            "per_book_replacements_persisted": True,
            "auto_selected_reviewed_phrase_rules": auto_phrase_count,
            "book_text_included_in_package": False,
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        guide_path = builder_output / "IMPORT.txt"
        _write_import_guide(
            guide_path, display_name, delta_filename, replacement_filename, has_replacements
        )
        history_snapshot = builder_output / "MyBooks_History.json"
        shutil.copyfile(history_path, history_snapshot)

        archive_path = package_dir / f"{_safe_stem(Path(display_name).stem)}-{digest[:10]}.zip"
        include = [
            delta_path, snapshot_path, history_snapshot, replacement_path, replacement_review_path,
            guide_path, report_path, builder_output / "Book_AutoStress_Review.tsv",
            builder_output / "Book_Unresolved_Words.tsv",
        ]
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in include:
                if file_path.is_file():
                    archive.write(file_path, arcname=file_path.name)
        try:
            os.chmod(archive_path, 0o600)
            os.chmod(snapshot_path, 0o600)
            os.chmod(history_snapshot, 0o600)
        except OSError:
            pass

        return {
            "archive": str(archive_path),
            "book_sha256": digest,
            "already_processed": was_processed,
            "new_entries": new_entries,
            "new_entry_count": len(new_entries),
            "cumulative_entry_count": len(parse_dictionary(master)[0]),
            "private_home": str(private_root),
            "book_name": display_name,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Локально и приватно обработать книгу, пополнить личный словарь и собрать ZIP для RuVoice"
    )
    parser.add_argument("book", type=Path, help="EPUB/TXT/HTML")
    parser.add_argument("--private-home", type=Path, default=DEFAULT_PRIVATE_HOME)
    parser.add_argument("--system-dictionary", type=Path, default=build_book_dictionary.DEFAULT_SYSTEM)
    parser.add_argument("--candidate-dictionary", type=Path, default=build_book_dictionary.DEFAULT_POOL)
    parser.add_argument("--candidate-audit", type=Path, default=build_book_dictionary.DEFAULT_AUDIT)
    parser.add_argument("--candidate-rules", type=Path, default=build_book_dictionary.DEFAULT_RULES)
    parser.add_argument("--replacements", type=Path, help="необязательный файл контекстных замен именно этой книги")
    args = parser.parse_args()
    try:
        result = process_book(
            args.book,
            private_home=args.private_home,
            system_dictionary=args.system_dictionary,
            candidate_dictionary=args.candidate_dictionary,
            candidate_audit=args.candidate_audit,
            candidate_rules=args.candidate_rules,
            replacements=args.replacements,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
