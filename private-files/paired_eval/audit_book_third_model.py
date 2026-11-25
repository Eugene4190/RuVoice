#!/usr/bin/env python3
"""Run an independent character-level Russian stress model over every EPUB segment.

This model is a disagreement detector, not a gold standard. We keep raw per-token
predictions, align them to the production RuVoice/RUAccent passes, and never silently
turn a model-only disagreement into a dictionary correction.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

VOWELS = set("аеёиоуыэюя")
WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*'?", re.UNICODE)
CYR_RE = re.compile(r"^[а-яё]+$")


def norm(value: str) -> str:
    return re.sub(r"[^а-яё]", "", value.lower().replace("ё", "е"))


def word_vowels(value: str) -> list[int]:
    return [i for i, char in enumerate(value.lower()) if char in VOWELS]


def accent_position(token: str) -> int | None:
    # Predictor writes apostrophe immediately after the stressed vowel.
    marks = [i for i, char in enumerate(token) if char in {"'", "’"}]
    if len(marks) == 1 and marks[0] > 0:
        stressed_char = marks[0] - 1
        if token[stressed_char].lower() in VOWELS:
            return sum(ch.lower() in VOWELS for ch in token[:stressed_char])
    lower = token.lower()
    if "ё" in lower:
        return sum(ch in VOWELS for ch in lower[:lower.index("ё")])
    return None


def split_context(text: str, max_chars: int) -> list[str]:
    """Split long segments on whitespace without splitting words."""
    result: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            cut = text.rfind(" ", start + max(40, max_chars // 2), end)
            if cut <= start:
                cut = text.find(" ", end)
                if cut < 0:
                    cut = len(text)
            end = cut
        if end <= start:
            end = min(len(text), start + max_chars)
        chunk = text[start:end]
        if chunk:
            result.append(chunk)
        start = end
    return result


def write_tsv(path: Path, rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow([
            "segment_index", "word_index", "chapter", "paragraph", "source_word",
            "ruvoice_output", "ruvoice_position", "ruaccent_output", "ruaccent_position",
            "third_model_output", "third_model_position", "context",
        ])
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paired-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-chars", type=int, default=220)
    args = parser.parse_args()

    if args.batch_size < 1 or args.batch_size > 32:
        raise SystemExit("--batch-size must be between 1 and 32")
    if args.max_chars < 100 or args.max_chars > 250:
        raise SystemExit("--max-chars must be between 100 and 250")

    paired = json.loads(args.paired_json.read_text(encoding="utf-8"))
    segment_rows = paired.get("segment_contexts", [])
    baseline_rows = paired.get("baseline_tokens", [])
    combined_rows = paired.get("combined_tokens", [])
    if not segment_rows or not baseline_rows or not combined_rows:
        raise SystemExit("Paired JSON must contain segment_contexts, baseline_tokens and combined_tokens")

    base_by_segment: dict[int, list[dict[str, Any]]] = {}
    combined_by_coord = {
        (int(row["segment_index"]), int(row["word_index"])): row
        for row in combined_rows
        if "segment_index" in row and "word_index" in row
    }
    for row in baseline_rows:
        if "segment_index" not in row or "word_index" not in row:
            continue
        base_by_segment.setdefault(int(row["segment_index"]), []).append(row)
    for values in base_by_segment.values():
        values.sort(key=lambda row: int(row["word_index"]))

    jobs: list[tuple[int, int, str, int, int]] = []
    # tuple: (segment index, chunk number, chunk text, global word offset, count)
    segments = sorted(segment_rows, key=lambda row: int(row["segment_index"]))
    expected_segment_count = 0
    for seg in segments:
        index = int(seg["segment_index"])
        context = str(seg.get("context", ""))
        chunks = split_context(context, args.max_chars)
        word_offset = 0
        for chunk_number, chunk in enumerate(chunks):
            count = len(WORD_RE.findall(chunk))
            jobs.append((index, chunk_number, chunk, word_offset, count))
            word_offset += count
        expected_segment_count += len(base_by_segment.get(index, []))

    from ruaccent import load_accentor
    import torch

    torch.set_num_threads(min(4, torch.get_num_threads()))
    print("THIRD_MODEL=ruaccent-predictor 1.2.0", flush=True)
    print("THIRD_MODEL_SEGMENTS=" + str(len(segments)), flush=True)
    print("THIRD_MODEL_WINDOWS=" + str(len(jobs)), flush=True)
    predictor = load_accentor(device="cpu", quantize=False)

    chunks = [job[2] for job in jobs]
    predictions: list[str] = []
    for start in range(0, len(chunks), args.batch_size):
        batch = chunks[start:start + args.batch_size]
        output = predictor(batch, format="apostrophe", batch_size=args.batch_size)
        if isinstance(output, str):
            output = [output]
        if len(output) != len(batch):
            raise RuntimeError("Third model returned an unaligned batch")
        predictions.extend(str(value) for value in output)
        if (start // args.batch_size) % 25 == 0:
            print(f"THIRD_MODEL_PROGRESS={min(start + len(batch), len(chunks))}/{len(chunks)}", flush=True)

    context_by_segment = {int(row["segment_index"]): str(row.get("context", "")) for row in segments}
    out_rows: list[list[Any]] = []
    counters = Counter()
    mismatch_groups: dict[tuple[str, int | None, int | None, int | None], Counter[str]] = {}
    aligned_per_segment: Counter[int] = Counter()
    input_word_offset_per_segment: Counter[int] = Counter()
    for job, predicted_text in zip(jobs, predictions):
        segment_index, chunk_number, chunk_text, word_offset, expected_count = job
        input_words = WORD_RE.findall(chunk_text)
        predicted_words = WORD_RE.findall(predicted_text)
        if len(input_words) != len(predicted_words):
            counters["window_token_count_mismatch"] += 1
            continue
        expected_tokens = base_by_segment.get(segment_index, [])
        for local_index, (input_word, predicted_word) in enumerate(zip(input_words, predicted_words)):
            word_index = word_offset + local_index
            if word_index >= len(expected_tokens):
                counters["production_alignment_missing"] += 1
                continue
            baseline = expected_tokens[word_index]
            source_word = str(baseline.get("source_word") or "")
            if source_word in {"", "null"}:
                counters["source_word_missing"] += 1
                continue
            if norm(input_word) != norm(source_word):
                counters["source_context_alignment_mismatch"] += 1
                continue
            clean_predicted = predicted_word.replace("'", "").replace("’", "")
            if norm(clean_predicted) != norm(source_word):
                counters["third_model_rewrote_word"] += 1
                continue

            third_position = accent_position(predicted_word)
            base_position = baseline.get("ruvoice_stress_vowel_index")
            base_position = None if base_position in (None, "", "null") else int(base_position)
            coord = (segment_index, word_index)
            combined = combined_by_coord.get(coord)
            combined_word = str(combined.get("ruaccent_merged_output", "")) if combined else ""
            combined_position = None
            if combined:
                value = combined.get("ruaccent_stress_vowel_index")
                combined_position = None if value in (None, "", "null") else int(value)
            key = norm(source_word)
            if not CYR_RE.fullmatch(key) or len(word_vowels(key)) < 2:
                counters["not_multisyllabic_russian"] += 1
                continue
            context = context_by_segment.get(segment_index, "")
            out_rows.append([
                segment_index, word_index, baseline.get("chapter", ""),
                baseline.get("paragraph", ""), source_word,
                baseline.get("ruvoice_output", ""), "" if base_position is None else base_position,
                combined_word, "" if combined_position is None else combined_position,
                predicted_word, "" if third_position is None else third_position,
                context,
            ])
            aligned_per_segment[segment_index] += 1
            counters["aligned_multisyllabic_occurrences"] += 1
            if third_position != base_position or third_position != combined_position:
                counters["third_model_disagreement_occurrences"] += 1
                pair = (key, base_position, combined_position, third_position)
                mismatch_groups.setdefault(pair, Counter())[context[:160]] += 1

    out_rows.sort(key=lambda row: (int(row[0]), int(row[1])))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / "Book_Third_Model_AllOccurrences.tsv"
    write_tsv(output_path, out_rows)

    pair_rows = []
    for (word, base, ruaccent, third), contexts in mismatch_groups.items():
        pair_rows.append([
            word, "" if base is None else base,
            "" if ruaccent is None else ruaccent,
            "" if third is None else third,
            sum(contexts.values()), " || ".join(contexts.keys()),
        ])
    pair_rows.sort(key=lambda row: (-int(row[4]), row[0]))
    pairs_path = args.output_dir / "Book_Third_Model_Disagreements.tsv"
    with pairs_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(["word", "ruvoice_position", "ruaccent_position", "third_model_position", "occurrences", "sample_contexts"])
        writer.writerows(pair_rows)

    summary = {
        "book": paired.get("book_file"),
        "segments": len(segments),
        "windows": len(jobs),
        "expected_production_tokens": expected_segment_count,
        "aligned_multisyllabic_occurrences": len(out_rows),
        "third_model_disagreement_occurrences": counters["third_model_disagreement_occurrences"],
        "unique_disagreement_groups": len(mismatch_groups),
        "disagreement_counts": dict(counters),
        "model": "ruaccent-predictor 1.2.0",
        "model_note": (
            "Independent character-level seq2seq model. Its self-reported validation metric is not "
            "treated as a gold score; use this output only as a third opinion. No word is auto-corrected "
            "by this script."
        ),
    }
    (args.output_dir / "Book_Third_Model_Summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("THIRD_MODEL_SUMMARY=" + json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
