#!/usr/bin/env python3
"""Generate the stock RuVoice target-word baseline on the identical gold corpus.

This mirrors the existing tools/homo_eval.py evaluation: packaged Silero Stress
accentor + the app's gramPass/phrase/BERT homograph resolver + stress fixes.
The output is keyed by corpus item id so the Kotlin production RUAccent runner
can compare the final merged target accent on exactly the same examples.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "project" / "ruvoice-1.1.3-stage4.9"
TOOLS = PROJECT / "tools"
sys.path.insert(0, str(TOOLS))

import torch
from torch.jit.mobile import _load_for_lite_interpreter
from silero_stress import load_accentor
import phrases_extra as pe
import stress_fixes as sf
from aot_morph import Table

WORD_RE = re.compile(r"[а-яё+-]+", re.IGNORECASE)


def plus_from_gold(value: str) -> str:
    marker = value.find("\u0301")
    if marker <= 0:
        raise ValueError(f"Gold target has no acute mark: {value!r}")
    return (value[: marker - 1] + "+" + value[marker - 1 :]).replace("\u0301", "")


def phrase_pick(word: str, text: str, phrases: dict) -> str | None:
    for pattern, variant in phrases.get(word, []):
        if re.search(r"(?<![а-яё-])" + re.escape(pattern) + r"(?![а-яё-])", text):
            return variant
    return None


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: evaluate_stock_ruvoice_baseline.py homograph_corpus.json output.json")
    corpus_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    torch.set_num_threads(1)
    silero_json = PROJECT / "app/src/main/assets/silero/silero_ru.json"
    with silero_json.open(encoding="utf-8") as stream:
        data = json.load(stream)
    gram = data["gram"]
    homodict = data["homodict"]
    phrases = data["phrases"]
    fixes = sf.load_fixes()
    morph = Table()
    for word, items in pe.load_extra().items():
        phrases[word] = sorted(items + [tuple(row) for row in phrases.get(word, [])], key=lambda x: -len(x[0]))

    # Same packaged homo.ptl and resolver path as the Android app's gold test.
    accentor = load_accentor()
    accentor.homosolver.model = _load_for_lite_interpreter(
        os.environ.get("HOMO") or str(PROJECT / "app/src/full/assets/silero/homo.ptl")
    )

    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    results = []
    total = correct = missing = phrase_skips = 0
    misses = []

    for index, item in enumerate(corpus):
        item_id = int(item["id"])
        gold_raw = str(item["homograph"]).lower()
        gold = plus_from_gold(gold_raw)
        word = gold.replace("+", "")
        context = str(item["context"]).lower()

        # Existing homo_eval.py counts single target-word rows only; phrase targets
        # have no single token to compare and are excluded by the Android test too.
        if any(ch.isspace() for ch in word):
            phrase_skips += 1
            continue

        got = accentor(context, put_yo=False, put_yo_homo=False)
        tokens = WORD_RE.findall(got)
        plain_tokens = [token.replace("+", "") for token in tokens]
        positions = [i for i, token in enumerate(plain_tokens) if token == word]
        if not positions:
            missing += 1
            continue

        occurrence = max(0, int(item.get("occurrence", 0)))
        target_index = positions[min(occurrence, len(positions) - 1)]
        raw_tokens = WORD_RE.findall(str(item["context"]))
        raw = raw_tokens if len(raw_tokens) == len(tokens) else None

        # This is the current app mirror: Silero stress -> gramPass/phrases/BERT -> fixes.
        baseline = pe.app_pick(
            word, plain_tokens, target_index, context, gram, homodict, morph,
            lambda w, txt: phrase_pick(w, txt, phrases), raw
        ) or tokens[target_index]
        if word in fixes and not pe.extra_pick(word, context):
            baseline = fixes[word]

        target_variant = gold
        baseline_clean = baseline.replace("+", "")
        if baseline_clean.replace("ё", "е").removesuffix("ъ") != word.replace("ё", "е").removesuffix("ъ"):
            raise RuntimeError(
                f"Baseline token alignment changed for item {item_id}: {baseline!r} vs {word!r}"
            )
        expected_index = target_variant.find("+")
        baseline_index = baseline.find("+")
        is_correct = baseline_index == expected_index
        total += 1
        correct += int(is_correct)

        results.append({
            "id": item_id,
            "word": word,
            "gold": target_variant,
            "stock": baseline,
            "raw_silero": tokens[target_index],
            "context": str(item["context"]),
            "stock_correct": is_correct,
        })
        if not is_correct and len(misses) < 100:
            misses.append({
                "id": item_id,
                "context": str(item["context"]),
                "expected": target_variant,
                "stock": baseline,
                "raw_silero": tokens[target_index],
            })

        if (index + 1) % 200 == 0:
            print(f"STOCK_BASELINE_PROGRESS={index + 1}/{len(corpus)}", flush=True)

    payload = {
        "schema_version": 1,
        "method": "Existing homo_eval.py mirror: Silero Stress + app gramPass/phrases/BERT + stress fixes",
        "source_script": "project/ruvoice-1.1.3-stage4.9/tools/homo_eval.py",
        "items_total": len(corpus),
        "items_scored": total,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
        "missing_target": missing,
        "skipped_multiword_target": phrase_skips,
        "results": results,
        "misses": misses,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rate = 100.0 * correct / max(total, 1)
    print(
        f"STOCK_RUVOICE_BASELINE={correct}/{total} ({rate:.2f}%); "
        f"missing={missing}; multiword skipped={phrase_skips}"
    )
    print(f"STOCK_BASELINE_REPORT={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
