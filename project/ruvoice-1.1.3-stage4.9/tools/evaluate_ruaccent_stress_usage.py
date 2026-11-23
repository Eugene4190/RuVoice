#!/usr/bin/env python3
"""Run the real nn_stress_usage model against a small Russian sanity corpus.

This is a diagnostic smoke evaluation, not a full accuracy benchmark. The
corpus checks only selected NO_STRESS function-word contexts documented by
stressonnx. Mismatches should be inspected, not automatically treated as a
broken model.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

try:
    from .probe_ruaccent_stress_usage import (
        ProbeError,
        load_probe_runtime,
        probe_with_runtime,
    )
except ImportError:
    from probe_ruaccent_stress_usage import ProbeError, load_probe_runtime, probe_with_runtime

DEFAULT_CORPUS = Path(__file__).parent / "data" / "ruaccent_stress_usage_smoke.json"


def load_corpus(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeError(f"Cannot read smoke corpus {path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise ProbeError("Smoke corpus must be an object containing a cases array")
    if payload.get("schema_version") != 1:
        raise ProbeError("Unsupported smoke corpus schema_version")
    seen_ids: set[str] = set()
    for case in payload["cases"]:
        if not isinstance(case, dict):
            raise ProbeError("Every smoke case must be an object")
        case_id = case.get("id")
        text = case.get("text")
        expectations = case.get("expect")
        if not isinstance(case_id, str) or not case_id or case_id in seen_ids:
            raise ProbeError(f"Missing or duplicate case id: {case_id!r}")
        seen_ids.add(case_id)
        if not isinstance(text, str) or not text.strip():
            raise ProbeError(f"Case {case_id}: text must be a non-empty string")
        if not isinstance(expectations, list) or not expectations:
            raise ProbeError(f"Case {case_id}: expect must be a non-empty array")
        for expected in expectations:
            if not isinstance(expected, dict):
                raise ProbeError(f"Case {case_id}: expectation must be an object")
            if not isinstance(expected.get("word"), str) or not expected["word"]:
                raise ProbeError(f"Case {case_id}: expectation word is missing")
            if expected.get("label") not in {"STRESS", "NO_STRESS"}:
                raise ProbeError(f"Case {case_id}: label must be STRESS or NO_STRESS")
            occurrence = expected.get("occurrence", 0)
            if not isinstance(occurrence, int) or occurrence < 0:
                raise ProbeError(f"Case {case_id}: occurrence must be a non-negative integer")
    return payload


def _matching_word_indices(word_labels: list[dict[str, Any]], target: str) -> list[int]:
    target_folded = target.casefold()
    return [
        index for index, item in enumerate(word_labels)
        if str(item.get("word", "")).casefold() == target_folded
    ]


def evaluate_cases(
    corpus: dict[str, Any],
    probe: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate expected labels using an injected probe (easy to unit-test)."""
    case_results: list[dict[str, Any]] = []
    total = passed = missing = 0
    for case in corpus["cases"]:
        result = probe(case["text"])
        word_labels = result.get("word_labels")
        if not isinstance(word_labels, list):
            raise ProbeError(f"Case {case['id']}: probe did not return word_labels")
        checks: list[dict[str, Any]] = []
        for expected in case["expect"]:
            total += 1
            indices = _matching_word_indices(word_labels, expected["word"])
            occurrence = expected.get("occurrence", 0)
            if occurrence >= len(indices):
                missing += 1
                checks.append({
                    "word": expected["word"],
                    "expected": expected["label"],
                    "actual": None,
                    "status": "MISSING",
                })
                continue
            observed = word_labels[indices[occurrence]]
            actual = observed.get("label")
            is_pass = actual == expected["label"]
            passed += int(is_pass)
            checks.append({
                "word": expected["word"],
                "occurrence": occurrence,
                "expected": expected["label"],
                "actual": actual,
                "confidence": observed.get("confidence"),
                "label_scores": observed.get("label_scores"),
                "status": "PASS" if is_pass else "MISMATCH",
            })
        case_results.append({
            "id": case["id"],
            "text": case["text"],
            "checks": checks,
        })
    return {
        "corpus": corpus.get("name", "unnamed"),
        "total_checks": total,
        "passed": passed,
        "mismatches": total - passed - missing,
        "missing": missing,
        "pass_rate": (passed / total) if total else 0.0,
        "cases": case_results,
        "warning": (
            "This is a small diagnostic set for selected NO_STRESS function-word contexts, "
            "not a comprehensive accuracy benchmark. A mismatch is an item to inspect."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_directory", type=Path, help="directory containing verified nn_stress_usage files")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--json", action="store_true", help="print full JSON report")
    parser.add_argument("--strict", action="store_true", help="return exit code 2 if any expected label mismatches")
    args = parser.parse_args(argv)
    try:
        corpus = load_corpus(args.corpus)
        runtime = load_probe_runtime(args.model_directory)
        report = evaluate_cases(corpus, lambda text: probe_with_runtime(text, runtime))
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"Corpus: {report['corpus']}")
            print(f"Checks: {report['passed']}/{report['total_checks']} matched; "
                  f"mismatches={report['mismatches']}; missing={report['missing']}")
            for case in report["cases"]:
                print(f"\n{case['id']}: {case['text']}")
                for check in case["checks"]:
                    confidence = check.get("confidence")
                    confidence_text = "n/a" if confidence is None else f"{confidence:.3f}"
                    print(
                        f"  {check['status']:<8} {check['word']}: "
                        f"expected={check['expected']} actual={check['actual']} "
                        f"confidence={confidence_text}"
                    )
            print("\n" + report["warning"])
        if args.strict and (report["mismatches"] or report["missing"]):
            return 2
        return 0
    except (OSError, ValueError, ProbeError, KeyError, TypeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
