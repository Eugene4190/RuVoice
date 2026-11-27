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
FUNCTION_WORDS = {
    "а", "и", "но", "да", "или", "ли", "не", "ни", "бы", "же", "в", "во",
    "на", "над", "под", "с", "со", "к", "ко", "у", "о", "об", "от", "до",
    "из", "за", "по", "при", "для", "без", "через", "перед", "после",
    "между", "около", "вокруг", "как", "что", "чтобы", "если", "когда",
    "где", "кто", "то", "это", "вот", "там", "тут", "уже", "лишь", "ведь",
    "либо", "нибудь", "таки", "обо",
}


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


def read_quality(path: Path) -> dict[tuple[int, int], dict[str, str]]:
    result: dict[tuple[int, int], dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            key = (int(row["segment_index"]), int(row["word_index"]))
            result[key] = row
    return result


def read_overrides(path: Path | None) -> set[str]:
    result: set[str] = set()
    if path is None or not path.is_file():
        return result
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.replace("=", " ", 1).split()
        if parts:
            result.add(norm(parts[0]))
    return result


def to_plus(word: str, position: int) -> str | None:
    clean = word.lower().replace("+", "").replace("'", "").replace("’", "")
    vowels = [index for index, char in enumerate(clean) if char in VOWELS]
    if position < 0 or position >= len(vowels):
        return None
    at = vowels[position]
    return clean[:at] + "+" + clean[at:]


def _position(value: Any) -> int | None:
    if value in (None, "", "null"):
        return None
    return int(value)


def select_third_model_candidates(
    rows: list[list[Any]],
    quality: dict[tuple[int, int], dict[str, str]],
    existing: set[str],
) -> tuple[set[str], set[tuple[int, int]], dict[str, Any]]:
    """
    Select only wordforms that could still become safe automatic corrections.

    Every occurrence of a selected form must be present and agree on spelling,
    baseline stress, RUAccent stress and dictionary evidence. The third model is
    then run on every full context segment containing one of those occurrences.
    OOVs and ambiguous forms remain in the full occurrence ledger, but do not
    consume the expensive third-model pass because that model cannot establish
    an importable correction without independent dictionary support.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    excluded = Counter()
    for row in rows:
        segment = int(row[0])
        word_index = int(row[1])
        raw_word = str(row[4]).lower()
        key = norm(raw_word)
        if not CYR_RE.fullmatch(key) or len(word_vowels(key)) < 2:
            excluded["not_multisyllabic_russian"] += 1
            continue
        if key in FUNCTION_WORDS:
            excluded["function_word"] += 1
            continue
        if "ё" in raw_word:
            excluded["contains_yo"] += 1
            continue
        if key in existing:
            excluded["already_in_reviewed_overlay"] += 1
            continue

        evidence = quality.get((segment, word_index), {})
        aot = {int(x) for x in re.split(r"[,;]", evidence.get("aot_stress_positions", "")) if x}
        wikt = {int(x) for x in re.split(r"[,;]", evidence.get("wiktionary_stress_positions", "")) if x}
        grouped.setdefault(key, []).append({
            "word": raw_word,
            "base": _position(row[6]),
            "ruaccent": _position(row[8]),
            "aot": aot,
            "wikt": wikt,
            "status": evidence.get("baseline_status", ""),
            "coord": (segment, word_index),
        })

    candidate_keys: set[str] = set()
    candidate_coords: set[tuple[int, int]] = set()
    for key, group in grouped.items():
        if len({item["word"] for item in group}) != 1:
            excluded["orthographic_variants_share_key"] += 1
            continue
        aot_sets = {tuple(sorted(item["aot"])) for item in group}
        wikt_sets = {tuple(sorted(item["wikt"])) for item in group}
        if len(aot_sets) != 1 or len(wikt_sets) != 1:
            excluded["dictionary_evidence_varies_by_occurrence"] += 1
            continue
        if any(item["status"] == "CONTEXTUAL_VARIANT_ACCEPTED" for item in group):
            excluded["contextual_exception"] += 1
            continue

        baseline_positions = {item["base"] for item in group}
        ruaccent_positions = {item["ruaccent"] for item in group}
        if (len(baseline_positions) != 1 or None in baseline_positions
                or len(ruaccent_positions) != 1 or None in ruaccent_positions):
            excluded["baseline_or_ruaccent_not_uniform"] += 1
            continue
        baseline = next(iter(baseline_positions))
        target = next(iter(ruaccent_positions))
        if baseline == target:
            excluded["ruvoice_already_agrees_with_ruaccent"] += 1
            continue

        aot = set(next(iter(aot_sets)))
        wikt = set(next(iter(wikt_sets)))
        if any(position != target for position in aot | wikt):
            excluded["dictionary_records_alternative_or_conflict"] += 1
            continue
        dictionary_support = (
            (aot == {target} and wikt == {target})
            or (aot == {target} and not wikt)
            or (wikt == {target} and not aot)
        )
        if not dictionary_support:
            excluded["no_unambiguous_dictionary_support"] += 1
            continue

        candidate_keys.add(key)
        candidate_coords.update(item["coord"] for item in group)

    candidate_segments = {segment for segment, _ in candidate_coords}
    return candidate_keys, candidate_coords, {
        "candidate_wordforms": len(candidate_keys),
        "candidate_occurrences": len(candidate_coords),
        "candidate_segments": len(candidate_segments),
        "excluded_by_reason": dict(excluded),
        "policy": (
            "The character model is restricted to forms where all book occurrences "
            "have one baseline stress, RUAccent consistently disagrees, and AOT "
            "and/or Wiktionary provides the same unambiguous alternative. OOV, "
            "contextual and conflicting forms remain in the complete ledger and "
            "are not auto-corrected by this optimization."
        ),
    }


def build_three_model_overrides(
    rows: list[list[Any]],
    quality: dict[tuple[int, int], dict[str, str]],
    existing: set[str],
    expected_occurrence_counts: dict[str, int] | None = None,
) -> tuple[list[str], list[str], list[list[Any]], dict[str, Any]]:
    """
    Group every token occurrence by exact spelling. Confirmed output requires two
    model votes (RUAccent + character Transformer) and at least one unambiguous
    dictionary source. Repeated OOV consensus is kept in a separate review file.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    excluded = Counter()
    for row in rows:
        segment = int(row[0])
        word_index = int(row[1])
        raw_word = str(row[4]).lower()
        key = norm(raw_word)
        if not CYR_RE.fullmatch(key) or len(word_vowels(key)) < 2:
            continue
        if key in FUNCTION_WORDS:
            excluded["function_word"] += 1
            continue
        if "ё" in raw_word:
            excluded["contains_yo"] += 1
            continue
        if key in existing:
            excluded["already_in_reviewed_overlay"] += 1
            continue
        quality_row = quality.get((segment, word_index), {})
        grouped.setdefault(key, []).append({
            "word": raw_word,
            "base": None if row[6] == "" else int(row[6]),
            "ruaccent": None if row[8] == "" else int(row[8]),
            "third": None if row[10] == "" else int(row[10]),
            "aot": {int(x) for x in re.split(r"[,;]", quality_row.get("aot_stress_positions", "")) if x},
            "wikt": {int(x) for x in re.split(r"[,;]", quality_row.get("wiktionary_stress_positions", "")) if x},
            "quality_status": quality_row.get("baseline_status", ""),
            "chapter": str(row[2]),
            "context": str(row[11]),
            "aot_details": quality_row.get("aot_source_details", ""),
            "wikt_details": quality_row.get("wiktionary_source_details", ""),
        })

    confirmed: list[str] = []
    oov_review: list[str] = []
    evidence: list[list[Any]] = []
    tiers = Counter()
    for key, group in grouped.items():
        # An alignment gap must never turn a partial sample into a book-wide rule.
        # The expected count comes from every production RuVoice occurrence, not
        # from the subset that the independent model happened to align.
        if expected_occurrence_counts is not None:
            expected_count = expected_occurrence_counts.get(key, 0)
            if expected_count <= 0 or len(group) != expected_count:
                excluded["incomplete_occurrence_coverage"] += 1
                continue
        if len({row["word"] for row in group}) != 1:
            excluded["orthographic_variants_share_key"] += 1
            continue
        aot_sets = {tuple(sorted(row["aot"])) for row in group}
        wikt_sets = {tuple(sorted(row["wikt"])) for row in group}
        if len(aot_sets) != 1 or len(wikt_sets) != 1:
            excluded["dictionary_evidence_varies_by_occurrence"] += 1
            continue
        aot = set(next(iter(aot_sets)))
        wikt = set(next(iter(wikt_sets)))
        if any(row["quality_status"] == "CONTEXTUAL_VARIANT_ACCEPTED" for row in group):
            excluded["contextual_exception"] += 1
            continue

        third_positions = {row["third"] for row in group}
        ruaccent_positions = {row["ruaccent"] for row in group}
        baseline_positions = {row["base"] for row in group}
        if len(third_positions) != 1 or len(ruaccent_positions) != 1 or None in third_positions or None in ruaccent_positions:
            excluded["model_outputs_not_uniform"] += 1
            continue
        target = next(iter(third_positions))
        if next(iter(ruaccent_positions)) != target:
            excluded["two_independent_models_disagree"] += 1
            continue
        if target in baseline_positions or None in baseline_positions or len(baseline_positions) != 1:
            excluded["baseline_is_mixed_or_already_correct"] += 1
            continue

        # A source that explicitly records another stress position is a contradiction,
        # not "missing evidence". Do not turn dictionary variants into a single rule.
        if any(position != target for position in aot | wikt):
            excluded["dictionary_records_alternative_or_conflict"] += 1
            continue

        tier = None
        if aot == {target} and wikt == {target}:
            tier = "AOT_AND_WIKTIONARY_PLUS_TWO_MODELS"
        elif (aot == {target} and not wikt) or (wikt == {target} and not aot):
            tier = "ONE_DICTIONARY_PLUS_TWO_MODELS"
        elif not aot and not wikt and len(group) >= 3:
            tier = "REPEATED_OOV_TWO_MODEL_CONSENSUS"

        if tier is None:
            excluded["insufficient_reference_or_repetition"] += 1
            continue
        word = group[0]["word"]
        marked = to_plus(word, target)
        if marked is None:
            excluded["invalid_stress_position"] += 1
            continue
        line = f"{key} {marked}"
        chapters = sorted({row["chapter"] for row in group if row["chapter"]})
        contexts = []
        for row in group:
            if row["context"] and row["context"] not in contexts and len(contexts) < 5:
                contexts.append(row["context"])
        evidence.append([
            tier, key, len(group), next(iter(baseline_positions)), target,
            ",".join(map(str, sorted(aot))), ",".join(map(str, sorted(wikt))),
            ";".join(chapters), " || ".join(contexts),
            group[0]["aot_details"], group[0]["wikt_details"],
        ])
        if tier == "REPEATED_OOV_TWO_MODEL_CONSENSUS":
            oov_review.append(line)
        else:
            confirmed.append(line)
        tiers[tier] += 1

    confirmed.sort()
    oov_review.sort()
    evidence.sort(key=lambda row: (-int(row[2]), row[1]))
    summary = {
        "confirmed_wordforms": len(confirmed),
        "confirmed_occurrences": sum(int(row[2]) for row in evidence if row[0] != "REPEATED_OOV_TWO_MODEL_CONSENSUS"),
        "repeated_oov_review_wordforms": len(oov_review),
        "repeated_oov_review_occurrences": sum(int(row[2]) for row in evidence if row[0] == "REPEATED_OOV_TWO_MODEL_CONSENSUS"),
        "candidate_wordforms_examined": len(grouped),
        "tiers": dict(tiers),
        "excluded_by_reason": dict(excluded),
        "policy": (
            "Confirmed word rules require RUAccent and the independent character model to agree "
            "on every occurrence, baseline RuVoice to use one different stress throughout, and "
            "one unambiguous AOT or Wiktionary source to support the target. Repeated OOVs with "
            "three or more matching occurrences are emitted separately for review, not import."
        ),
    }
    return confirmed, oov_review, evidence, summary


def require_full_model_occurrence_coverage(
    expected_coords: set[tuple[int, int]],
    actual_coords: set[tuple[int, int]],
) -> None:
    """Fail a full-book run rather than silently accepting skipped model occurrences."""
    missing = sorted(expected_coords - actual_coords)
    unexpected = sorted(actual_coords - expected_coords)
    if missing or unexpected:
        raise RuntimeError(
            "Full-book third-model occurrence alignment is incomplete: "
            f"expected={len(expected_coords)}, aligned={len(actual_coords)}, "
            f"missing={missing[:20]}, unexpected={unexpected[:20]}"
        )


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
    parser.add_argument("--quality-occurrences", type=Path, required=True)
    parser.add_argument("--reviewed-overrides", type=Path)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-chars", type=int, default=220)
    parser.add_argument("--all-segments", action="store_true", help="Run the research model over every segment; default checks only fully eligible correction candidates.")
    args = parser.parse_args()

    if args.batch_size < 1 or args.batch_size > 32:
        raise SystemExit("--batch-size must be between 1 and 32")
    if args.max_chars < 100 or args.max_chars > 250:
        raise SystemExit("--max-chars must be between 100 and 250")

    paired = json.loads(args.paired_json.read_text(encoding="utf-8"))
    quality = read_quality(args.quality_occurrences)
    existing_overrides = read_overrides(args.reviewed_overrides)
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

    # Build the exact occurrence input once, then identify complete wordforms
    # where an independent third opinion could still produce a safe correction.
    all_segments = sorted(segment_rows, key=lambda row: int(row["segment_index"]))
    preselection_rows: list[list[Any]] = []
    for baseline in baseline_rows:
        segment_index = int(baseline["segment_index"])
        word_index = int(baseline["word_index"])
        combined = combined_by_coord.get((segment_index, word_index), {})
        preselection_rows.append([
            segment_index, word_index, baseline.get("chapter", ""),
            baseline.get("paragraph", ""), baseline.get("source_word", ""),
            baseline.get("ruvoice_output", ""),
            baseline.get("ruvoice_stress_vowel_index", ""),
            combined.get("ruaccent_merged_output", ""),
            combined.get("ruaccent_stress_vowel_index", ""),
        ])
    candidate_keys, candidate_coords, candidate_summary = select_third_model_candidates(
        preselection_rows, quality, existing_overrides
    )

    if args.all_segments:
        segments = all_segments
    else:
        selected_segment_ids = {segment for segment, _ in candidate_coords}
        segments = [
            row for row in all_segments
            if int(row["segment_index"]) in selected_segment_ids
        ]

    jobs: list[tuple[int, int, str, int, int]] = []
    # tuple: (segment index, chunk number, chunk text, global word offset, count)
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

    predictions: list[str] = []
    if jobs:
        from ruaccent import load_accentor
        import torch

        torch.set_num_threads(min(4, torch.get_num_threads()))
        print("THIRD_MODEL=ruaccent-predictor 1.2.0", flush=True)
        predictor = load_accentor(device="cpu", quantize=False)
        chunks = [job[2] for job in jobs]
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
    else:
        print("THIRD_MODEL_SKIPPED=NO_ELIGIBLE_CORRECTION_CANDIDATES", flush=True)

    print("THIRD_MODEL_BOOK_SEGMENTS=" + str(len(all_segments)), flush=True)
    print("THIRD_MODEL_SEGMENTS_INFERRED=" + str(len(segments)), flush=True)
    print("THIRD_MODEL_WINDOWS_INFERRED=" + str(len(jobs)), flush=True)
    print("THIRD_MODEL_CANDIDATE_WORDFORMS=" + str(candidate_summary["candidate_wordforms"]), flush=True)

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
            if not args.all_segments and key not in candidate_keys:
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
    actual_coord_list = [(int(row[0]), int(row[1])) for row in out_rows]
    actual_coords = set(actual_coord_list)
    if len(actual_coord_list) != len(actual_coords):
        raise RuntimeError("Third-model output contains duplicate production occurrence coordinates")

    # Candidate wordforms are eligible for automatic correction only when every
    # occurrence selected during preflight was actually inferred and aligned.
    candidate_actual_coords = actual_coords & candidate_coords
    if candidate_actual_coords != candidate_coords:
        missing = sorted(candidate_coords - candidate_actual_coords)[:20]
        raise RuntimeError(
            "Third-model candidate occurrence coverage mismatch; automatic corrections are blocked. "
            f"missing={missing}"
        )
    if not args.all_segments and actual_coords != candidate_coords:
        extra = sorted(actual_coords - candidate_coords)[:20]
        raise RuntimeError(
            "Third-model selected-mode output contains unexpected occurrences. "
            f"extra={extra}"
        )

    expected_model_coords: set[tuple[int, int]] = set()
    expected_occurrence_counts: Counter[str] = Counter()
    for baseline in baseline_rows:
        coord = (int(baseline["segment_index"]), int(baseline["word_index"]))
        source_word = str(baseline.get("source_word") or baseline.get("ruvoice_output") or "")
        key = norm(source_word)
        if CYR_RE.fullmatch(key) and len(word_vowels(key)) >= 2:
            expected_model_coords.add(coord)
            expected_occurrence_counts[key] += 1
    missing_model_coords = expected_model_coords - actual_coords
    if args.all_segments:
        require_full_model_occurrence_coverage(expected_model_coords, actual_coords)

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

    confirmed_lines, oov_lines, evidence_rows, auto_summary = build_three_model_overrides(
        out_rows, quality, existing_overrides,
        expected_occurrence_counts=expected_occurrence_counts,
    )
    confirmed_path = args.output_dir / "Book_Three_Model_Confirmed_Overrides.txt"
    confirmed_path.write_text(
        "# Подтверждённые книжные исправления: RUAccent и независимая модель согласны, "
        "и ударение поддержано хотя бы одним словарём.\n"
        "# Только отдельный словарь для этой книги; не добавлять в глобальный Системный.txt.\n"
        + ("\n".join(confirmed_lines) + "\n" if confirmed_lines else ""),
        encoding="utf-8",
    )
    oov_path = args.output_dir / "Book_Three_Model_OOV_Review.txt"
    oov_path.write_text(
        "# Повторяющиеся авторские/редкие формы: две модели согласны минимум в трёх вхождениях, "
        "но независимой словарной статьи нет.\n"
        "# ЭТО НЕ ГОТОВЫЙ ИМПОРТ: отдельная очередь проверки.\n"
        + ("\n".join(oov_lines) + "\n" if oov_lines else ""),
        encoding="utf-8",
    )
    evidence_path = args.output_dir / "Book_Three_Model_Override_Evidence.tsv"
    with evidence_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow([
            "tier", "word", "book_frequency", "ruvoice_position", "consensus_position",
            "aot_positions", "wiktionary_positions", "chapters", "sample_contexts",
            "aot_details", "wiktionary_details",
        ])
        writer.writerows(evidence_rows)
    auto_summary_path = args.output_dir / "Book_Three_Model_Override_Summary.json"
    auto_summary_path.write_text(
        json.dumps(auto_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    summary = {
        "book": paired.get("book_file"),
        "all_book_segments": len(all_segments),
        "segments": len(segments),
        "windows": len(jobs),
        "expected_production_tokens_in_inferred_segments": expected_segment_count,
        "candidate_selection": candidate_summary,
        "candidate_occurrence_coverage": (
            "FULL" if candidate_actual_coords == candidate_coords
            else f"{len(candidate_actual_coords)}/{len(candidate_coords)}"
        ),
        "all_segments_mode": bool(args.all_segments),
        "expected_multisyllabic_occurrences": len(expected_model_coords),
        "aligned_multisyllabic_occurrences": len(actual_coords),
        "missing_multisyllabic_occurrences": len(missing_model_coords),
        "multisyllabic_occurrence_coverage_percent": (
            round(100 * len(actual_coords & expected_model_coords) / len(expected_model_coords), 4)
            if expected_model_coords else 100.0
        ),
        "third_model_disagreement_occurrences": counters["third_model_disagreement_occurrences"],
        "unique_disagreement_groups": len(mismatch_groups),
        "disagreement_counts": dict(counters),
        "model": "ruaccent-predictor 1.2.0",
        "model_note": (
            "Independent character-level seq2seq model. Its self-reported validation metric is not "
            "treated as a gold score; use this output only as a third opinion. In default mode, "
            "inference is limited to complete wordforms with a consistent RUAccent disagreement "
            "and unambiguous AOT/Wiktionary support; every occurrence of each selected wordform "
            "is still inferred and alignment-checked. Use --all-segments for an exhaustive research run."
        ),
        "auto_override_summary": auto_summary,
        "confirmed_override_file": str(confirmed_path),
        "oov_review_file_not_for_import": str(oov_path),
    }
    (args.output_dir / "Book_Third_Model_Summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("THIRD_MODEL_SUMMARY=" + json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
    print("THIRD_MODEL_CONFIRMED_OVERRIDES=" + str(confirmed_path) + " WORDS=" + str(len(confirmed_lines)), flush=True)
    print("THIRD_MODEL_OOV_REVIEW=" + str(oov_path) + " WORDS=" + str(len(oov_lines)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
