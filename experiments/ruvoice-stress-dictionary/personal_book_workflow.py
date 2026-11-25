#!/usr/bin/env python3
"""Private, cumulative book-to-RuVoice workflow.

User books and the append-only master dictionary live outside the repository,
under ~/.ruvoice-book-workflow (or RUVOICE_PRIVATE_HOME). Only source-vetted
book candidates that survive the builder's context, spelling and conflict
filters are appended. Every book gets a ZIP with its new delta and full snapshot.
"""
from __future__ import annotations

import argparse
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
from analyze_book import parse_dictionary
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
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _ensure_private_store(root: Path) -> tuple[Path, Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    state_dir = root / "state"
    work_dir = root / "work"
    package_dir = root / "packages"
    for folder in (state_dir, work_dir, package_dir):
        folder.mkdir(parents=True, exist_ok=True)
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
    state["books"][pending["book_sha256"]] = {
        "book_name": pending["book_name"],
        "processed_utc": pending["created_utc"],
        "new_entries": pending.get("new_entries", []),
    }


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


def _write_import_guide(path: Path, book_name: str, has_replacements: bool) -> None:
    replacement_text = (
        "Импортируйте Book_Replacements.txt во вкладку «Замены» только если в файле есть правила. "
        "Правила остаются привязанными к этой книге."
        if has_replacements
        else "Для этой книги отдельные контекстные замены не переданы; файл Book_Replacements.txt содержит только комментарий."
    )
    _atomic_text(
        path,
        (
            f"RuVoice — дополнение для книги: {book_name}\n\n"
            "1. Откройте RuVoice → «Ударения» → импорт TXT.\n"
            "2. Импортируйте Book_New_Stress_Delta.txt отдельным списком с названием этой книги. "
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
) -> dict[str, Any]:
    """Process one book privately and return a ZIP bundle plus a safe summary."""
    book = Path(book)
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

    digest = hashlib.sha256(book.read_bytes()).hexdigest()
    with _LOCK:
        master, state_dir, package_dir = _ensure_private_store(Path(private_home))
        _recover_pending(Path(private_home), master, Path(system_dictionary))
        history_path = state_dir / STATE_NAME
        history = _load_json(history_path, {"schema_version": 1, "books": {}})
        was_processed = digest in history.get("books", {})

        work_dir = Path(private_home) / "work" / digest
        work_dir.mkdir(parents=True, exist_ok=True)
        builder_output = work_dir / "builder"
        builder_output.mkdir(parents=True, exist_ok=True)
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
        new_entries = [] if was_processed else [
            {"word": word, "stress": marked}
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
                "book_name": book.name,
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
        delta_path = builder_output / "Book_New_Stress_Delta.txt"
        _atomic_text(delta_path, delta_text)
        snapshot_path = builder_output / "MyBooks_Cumulative.txt"
        shutil.copyfile(master, snapshot_path)

        replacement_path = builder_output / "Book_Replacements.txt"
        if replacements is not None:
            shutil.copyfile(Path(replacements), replacement_path)
            has_replacements = bool(
                [line for line in replacement_path.read_text(encoding="utf-8-sig").splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
            )
        else:
            _atomic_text(
                replacement_path,
                "# Для этой книги отдельные контекстные/фразовые замены не переданы.\n",
            )
            has_replacements = False

        report_path = builder_output / "Book_Report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        # Never put local home paths into a distributable report.
        for key in ("system_dictionary", "approved_dictionary"):
            report.pop(key, None)
        report["workflow"] = {
            "book_sha256": digest,
            "already_processed_before_this_run": was_processed,
            "newly_approved_entries": new_entries,
            "newly_approved_count": len(new_entries),
            "cumulative_approved_count": len(parse_dictionary(master)[0]),
            "append_only": True,
            "private_storage": True,
            "book_text_included_in_package": False,
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        guide_path = builder_output / "IMPORT.txt"
        _write_import_guide(guide_path, book.name, has_replacements)

        archive_path = package_dir / f"{_safe_stem(book.stem)}-{digest[:10]}.zip"
        include = [
            delta_path, snapshot_path, replacement_path, guide_path, report_path,
            builder_output / "Book_AutoStress_Review.tsv",
            builder_output / "Book_Unresolved_Words.tsv",
        ]
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in include:
                if file_path.is_file():
                    archive.write(file_path, arcname=file_path.name)

        return {
            "archive": str(archive_path),
            "book_sha256": digest,
            "already_processed": was_processed,
            "new_entries": new_entries,
            "new_entry_count": len(new_entries),
            "cumulative_entry_count": len(parse_dictionary(master)[0]),
            "private_home": str(private_home),
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
