#!/usr/bin/env python3
"""Validate and score RuVoice predictions against an independent stress gold set."""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

VOWELS = set("аеёиоуыэюя")
GOLD_COLUMNS = {
    "gold_id", "surface", "lemma", "part_of_speech", "morph_features",
    "sense_id", "context", "primary_marked", "accepted_marked",
    "evaluation_scope", "category", "source_title", "source_url",
    "evidence", "reviewed_on",
}
PREDICTION_COLUMNS = {"gold_id", "predicted_marked"}
VALID_SCOPES = {"word", "contextual"}
WORD_RE = re.compile(r"^[а-яё]+$")


class GoldSetError(ValueError):
    """Raised when a gold set or prediction file is malformed."""


def validate_marked(surface: str, marked: str) -> str | None:
    """Validate exact spelling and a single stress marker before a vowel."""
    if not marked:
        return "пустая форма ударения"
    if not re.fullmatch(r"[а-яё+]+", marked):
        return "форма должна содержать только русские буквы и знак +"
    if marked.count("+") != 1:
        return "нужен ровно один знак +"
    marker = marked.index("+")
    bare = marked.replace("+", "")
    if marker >= len(bare) or bare[marker] not in VOWELS:
        return "знак + должен стоять непосредственно перед гласной"
    if bare != surface:
        return f"после удаления + получено {bare!r}, ожидалось точное написание {surface!r}"
    if sum(char in VOWELS for char in bare) < 2:
        return "односложная форма не должна иметь отдельную запись ударения"
    return None


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            if not reader.fieldnames:
                raise GoldSetError(f"Пустой или некорректный TSV: {path}")
            rows = [
                {key: (value or "").strip() for key, value in row.items() if key}
                for row in reader
            ]
            return list(reader.fieldnames), rows
    except (OSError, UnicodeError, csv.Error) as exc:
        raise GoldSetError(f"Не удалось прочитать {path}: {exc}") from exc


def load_gold(path: Path) -> list[dict[str, str]]:
    columns, rows = read_tsv(path)
    missing = sorted(GOLD_COLUMNS - set(columns))
    if missing:
        raise GoldSetError(f"В gold TSV отсутствуют колонки: {', '.join(missing)}")
    if not rows:
        raise GoldSetError("Gold set не содержит строк")

    seen: set[str] = set()
    for line_number, row in enumerate(rows, 2):
        gold_id = row["gold_id"]
        surface = row["surface"]
        if not gold_id or gold_id in seen:
            raise GoldSetError(f"Строка {line_number}: пустой или повторный gold_id {gold_id!r}")
        seen.add(gold_id)
        if not WORD_RE.fullmatch(surface):
            raise GoldSetError(f"Строка {line_number}: некорректная русская словоформа {surface!r}")
        if row["evaluation_scope"] not in VALID_SCOPES:
            raise GoldSetError(
                f"Строка {line_number}: evaluation_scope должен быть word или contextual"
            )
        for required in ("lemma", "part_of_speech", "morph_features", "sense_id",
                        "context", "category", "source_title", "source_url",
                        "evidence", "reviewed_on"):
            if not row[required]:
                raise GoldSetError(f"Строка {line_number}: не заполнено обязательное поле {required}")
        if not row["source_url"].startswith(("https://", "http://")):
            raise GoldSetError(f"Строка {line_number}: некорректный source_url")

        accepted = [item.strip() for item in row["accepted_marked"].split("|") if item.strip()]
        if not accepted:
            raise GoldSetError(f"Строка {line_number}: accepted_marked не содержит вариантов")
        if len(set(accepted)) != len(accepted):
            raise GoldSetError(f"Строка {line_number}: повторяется accepted-вариант")
        for marked in accepted:
            reason = validate_marked(surface, marked)
            if reason:
                raise GoldSetError(
                    f"Строка {line_number}: неверный accepted-вариант {marked!r}: {reason}"
                )

        primary = row["primary_marked"]
        if primary:
            reason = validate_marked(surface, primary)
            if reason:
                raise GoldSetError(
                    f"Строка {line_number}: неверный primary-вариант {primary!r}: {reason}"
                )
            if primary not in accepted:
                raise GoldSetError(
                    f"Строка {line_number}: primary_marked должен входить в accepted_marked"
                )
        row["accepted_variants"] = accepted
    return rows


def load_predictions(path: Path, gold_rows: list[dict[str, str]]) -> dict[str, str]:
    columns, rows = read_tsv(path)
    missing = sorted(PREDICTION_COLUMNS - set(columns))
    if missing:
        raise GoldSetError(f"В predictions TSV отсутствуют колонки: {', '.join(missing)}")

    gold_by_id = {row["gold_id"]: row for row in gold_rows}
    predictions: dict[str, str] = {}
    for line_number, row in enumerate(rows, 2):
        gold_id = row["gold_id"]
        if gold_id not in gold_by_id:
            raise GoldSetError(f"Строка {line_number}: неизвестный gold_id {gold_id!r}")
        if gold_id in predictions:
            raise GoldSetError(f"Строка {line_number}: повторный prediction для {gold_id}")
        predicted = row["predicted_marked"]
        if predicted and predicted.upper() != "ABSTAIN":
            reason = validate_marked(gold_by_id[gold_id]["surface"], predicted)
            if reason:
                raise GoldSetError(
                    f"Строка {line_number}: неверное предсказание {predicted!r}: {reason}"
                )
        predictions[gold_id] = predicted
    return predictions


def metric_summary(items: Iterable[tuple[dict[str, str], str]]) -> dict[str, int | float]:
    values = list(items)
    total = len(values)
    emitted = [(row, pred) for row, pred in values if pred and pred.upper() != "ABSTAIN"]
    correct = sum(pred in row["accepted_variants"] for row, pred in emitted)
    primary_available = [(row, pred) for row, pred in emitted if row["primary_marked"]]
    primary_correct = sum(pred == row["primary_marked"] for row, pred in primary_available)
    return {
        "gold_rows": total,
        "emitted_predictions": len(emitted),
        "abstentions_or_missing": total - len(emitted),
        "correct_predictions": correct,
        "incorrect_predictions": len(emitted) - correct,
        "coverage_percent": round(100 * len(emitted) / total, 2) if total else 0.0,
        "exact_accuracy_among_emitted_percent": (
            round(100 * correct / len(emitted), 2) if emitted else 0.0
        ),
        "accuracy_over_all_gold_rows_percent": (
            round(100 * correct / total, 2) if total else 0.0
        ),
        "primary_variant_accuracy_percent": (
            round(100 * primary_correct / len(primary_available), 2)
            if primary_available else None
        ),
    }


def evaluate(gold_rows: list[dict[str, str]], predictions: dict[str, str] | None) -> dict:
    prediction_map = predictions or {}
    pairs = [(row, prediction_map.get(row["gold_id"], "")) for row in gold_rows]
    by_scope: dict[str, list] = defaultdict(list)
    by_category: dict[str, list] = defaultdict(list)
    for row, predicted in pairs:
        by_scope[row["evaluation_scope"]].append((row, predicted))
        by_category[row["category"]].append((row, predicted))

    return {
        "dataset": "RuVoice independent stress gold set",
        "gold_rows": len(gold_rows),
        "predictions_supplied": predictions is not None,
        "independence_policy": (
            "Gold labels are based on cited lexicographic sources and human annotation, "
            "not on RuVoice/RUAccent predictions or AOT/Wiktionary model consensus."
        ),
        "overall": metric_summary(pairs) if predictions is not None else None,
        "by_evaluation_scope": {
            key: metric_summary(value) for key, value in sorted(by_scope.items())
        } if predictions is not None else {},
        "by_category": {
            key: metric_summary(value) for key, value in sorted(by_category.items())
        } if predictions is not None else {},
        "warning": (
            "This seed set is small and deliberately selected; its scores are smoke-test "
            "metrics, not a representative estimate of Russian stress accuracy."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Проверить разметку gold set и оценить предсказания ударений"
    )
    parser.add_argument(
        "--gold", type=Path,
        default=Path(__file__).parent / "data/gold/seed.tsv",
        help="независимый gold TSV",
    )
    parser.add_argument(
        "--predictions", type=Path,
        help="TSV с колонками gold_id и predicted_marked; пустое поле/ABSTAIN — отказ",
    )
    parser.add_argument("--json-out", type=Path, help="дополнительно записать JSON-отчёт")
    args = parser.parse_args()

    try:
        gold_rows = load_gold(args.gold)
        predictions = load_predictions(args.predictions, gold_rows) if args.predictions else None
        report = evaluate(gold_rows, predictions)
    except (GoldSetError, OSError, ValueError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
