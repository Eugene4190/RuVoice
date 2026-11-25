#!/usr/bin/env python3
"""Build a context-rich, whole-book stress-difference audit from the paired evaluator JSON.

The paired evaluator runs both production RuVoice and production RUAccent over the
entire EPUB. This report does not call either model's output ground truth. It attaches
system dictionary and AOT/Wiktionary consensus provenance to every multisyllabic
stress difference and preserves short context only in the workflow artifact.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

VOWELS = set("аеёиоуыэюя")
ACUTE = "\u0301"


def normalize(word: str) -> str:
    return word.lower().replace("+", "").replace(ACUTE, "").replace("ё", "е")


def acute_position(word: str) -> int | None:
    vowel_index = 0
    for i, char in enumerate(word.lower()):
        if char in VOWELS:
            if i + 1 < len(word) and word[i + 1] == ACUTE:
                return vowel_index
            vowel_index += 1
    return None


def plus_position(word: str) -> int | None:
    plus = word.find("+")
    if plus < 0:
        return None
    return sum(ch.lower() in VOWELS for ch in word[:plus])


def read_marked_dictionary(path: Path) -> dict[str, set[int]]:
    result: dict[str, set[int]] = defaultdict(set)
    if not path.is_file():
        return result
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.replace("=", " ", 1).split()
        if len(parts) < 2:
            continue
        word, marked = parts[0].lower(), parts[1].lower()
        pos = plus_position(marked)
        if pos is not None:
            result[normalize(word)].add(pos)
    return result


def read_provenance(path: Path) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    if not path.is_file():
        return result
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        lines = (line for line in stream if not line.lstrip().startswith("#"))
        reader = csv.DictReader(lines, delimiter="\t")
        for row in reader:
            word = (row.get("word") or "").strip()
            source = (row.get("source") or "").strip()
            if word and source:
                result[normalize(word)].add(source)
    return result



def parse_positions(raw: str | None) -> set[int]:
    """Parse comma-separated stress-vowel positions from the complete quality TSV."""
    if not raw:
        return set()
    return {int(value.strip()) for value in re.split(r"[,;]", str(raw)) if value.strip()}


def read_quality_occurrences(path: Path) -> dict[tuple[int, int], dict[str, str]]:
    """Index full AOT/Wiktionary occurrence evidence by segment and word coordinates."""
    required = {
        "segment_index", "word_index", "aot_stress_positions",
        "wiktionary_stress_positions", "aot_source_details",
        "wiktionary_source_details", "baseline_status", "reviewed_status",
    }
    result: dict[tuple[int, int], dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError("Whole-book quality TSV is missing columns: " + ", ".join(sorted(missing)))
        for row in reader:
            key = (int(row["segment_index"]), int(row["word_index"]))
            if key in result:
                raise ValueError(f"Duplicate quality TSV occurrence coordinates: {key}")
            result[key] = row
    return result


def quality_source_assessment(
    row: dict[str, str] | None,
    before_pos: int | None,
    after_pos: int | None,
) -> tuple[set[int], set[int], set[int], str]:
    """Return AOT, Wiktionary, common positions and a variant-aware source verdict."""
    if row is None:
        return set(), set(), set(), "QUALITY_ROW_MISSING"

    aot_positions = parse_positions(row.get("aot_stress_positions"))
    wiktionary_positions = parse_positions(row.get("wiktionary_stress_positions"))
    shared_positions = aot_positions & wiktionary_positions

    if row.get("baseline_status") == "CONTEXTUAL_VARIANT_ACCEPTED":
        verdict = "CONTEXTUAL_VARIANT_ACCEPTED"
    elif not aot_positions and not wiktionary_positions:
        verdict = "NO_INDEPENDENT_REFERENCE"
    elif aot_positions and wiktionary_positions and not shared_positions:
        verdict = "AOT_WIKTIONARY_DISAGREE_NO_SHARED_VARIANT"
    elif before_pos in shared_positions and after_pos in shared_positions:
        verdict = "CONSENSUS_SUPPORTS_BOTH_VARIANTS"
    elif before_pos in shared_positions:
        verdict = "CONSENSUS_SUPPORTS_RUVOICE"
    elif after_pos in shared_positions:
        verdict = "CONSENSUS_SUPPORTS_RUACCENT"
    elif shared_positions:
        verdict = "CONSENSUS_SUPPORTS_OTHER_VARIANT"
    else:
        available = aot_positions | wiktionary_positions
        if before_pos in available and after_pos not in available:
            verdict = "SINGLE_SOURCE_SUPPORTS_RUVOICE"
        elif after_pos in available and before_pos not in available:
            verdict = "SINGLE_SOURCE_SUPPORTS_RUACCENT"
        else:
            verdict = "SINGLE_SOURCE_OR_VARIANT_REVIEW"
    return aot_positions, wiktionary_positions, shared_positions, verdict

def describe_support(
    expected: int | None,
    positions: set[int],
    no_entry: str,
    supports_baseline: str,
    supports_alt: str,
    different: str,
) -> str:
    if not positions:
        return no_entry
    if expected is None:
        return different
    if positions == {expected}:
        return supports_baseline
    return different


def render_positions(positions: set[int]) -> str:
    return ",".join(str(x) for x in sorted(positions))


AUTO_EXCLUDED_WORDS = {
    "а", "и", "но", "да", "или", "ли", "не", "ни", "бы", "же", "в", "во",
    "на", "над", "под", "с", "со", "к", "ко", "у", "о", "об", "от", "до",
    "из", "за", "по", "при", "для", "без", "через", "перед", "после",
    "между", "около", "вокруг", "как", "что", "чтобы", "если", "когда",
    "где", "кто", "то", "это", "вот", "там", "тут", "уже", "лишь", "ведь",
    "либо", "нибудь", "таки", "обо",
}


def marker_for_word(word: str, position: int) -> str | None:
    """Convert a vowel index into the RuVoice user-dictionary +marker format."""
    clean = word.lower().replace("+", "").replace(ACUTE, "")
    vowel_chars = [index for index, char in enumerate(clean) if char in VOWELS]
    if position < 0 or position >= len(vowel_chars):
        return None
    at = vowel_chars[position]
    return clean[:at] + "+" + clean[at:]


def build_consensus_auto_overrides(
    paired: dict[str, Any],
    quality_occurrences: dict[tuple[int, int], dict[str, str]],
    existing_overrides: dict[str, set[int]] | None = None,
) -> tuple[list[str], list[list[Any]], dict[str, Any]]:
    """
    Produce importable corrections only when every occurrence of a spelling in the
    book has one unambiguous AOT position, one identical Wiktionary position, and
    the merged production RUAccent output follows that position while baseline
    RuVoice consistently does not. This is deliberately stricter than "models differ".
    """
    baseline_rows = paired.get("baseline_tokens", [])
    combined_rows = paired.get("combined_tokens", [])
    combined_by_key: dict[tuple[int, int], dict[str, Any]] = {}
    for row in combined_rows:
        if "segment_index" in row and "word_index" in row:
            combined_by_key[(int(row["segment_index"]), int(row["word_index"]))] = row

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    skipped = Counter()
    for token in baseline_rows:
        source = token.get("source_word")
        if source in (None, "null"):
            source = token.get("ruvoice_output", "")
        source_word = str(source).lower().replace("+", "").replace(ACUTE, "")
        key = normalize(source_word)
        if not re.fullmatch(r"[а-яё]+", key):
            skipped["non_russian_or_non_word"] += 1
            continue
        if len([ch for ch in key if ch in VOWELS]) < 2:
            skipped["monosyllable"] += 1
            continue
        if key in AUTO_EXCLUDED_WORDS:
            skipped["function_word_or_clitic"] += 1
            continue
        # Ё is already a stress signal and must not be converted into a dictionary +
        # marker; normalized e/ё homographs are also not safe for blind word-only rules.
        if "ё" in source_word:
            skipped["contains_yo"] += 1
            continue

        coord = (int(token.get("segment_index", -1)), int(token.get("word_index", -1)))
        combined = combined_by_key.get(coord)
        quality = quality_occurrences.get(coord)
        if combined is None or quality is None:
            skipped["missing_alignment_or_quality"] += 1
            continue
        if normalize(str(token.get("ruvoice_output", ""))) != key:
            skipped["source_output_lexical_mismatch"] += 1
            continue
        combined_word = str(combined.get("ruaccent_merged_output", ""))
        if normalize(combined_word) != key:
            skipped["combined_output_lexical_mismatch"] += 1
            continue
        grouped[key].append({
            "source_word": source_word,
            "baseline_word": str(token.get("ruvoice_output", "")),
            "baseline_position": token.get("ruvoice_stress_vowel_index"),
            "combined_word": combined_word,
            "combined_position": combined.get("ruaccent_stress_vowel_index"),
            "aot": parse_positions(quality.get("aot_stress_positions")),
            "wikt": parse_positions(quality.get("wiktionary_stress_positions")),
            "quality_status": quality.get("baseline_status", ""),
            "chapter": str(token.get("chapter", "")),
            "paragraph": str(token.get("paragraph", "")),
            "context": quality.get("context", ""),
            "aot_details": quality.get("aot_source_details", ""),
            "wikt_details": quality.get("wiktionary_source_details", ""),
        })

    existing_overrides = existing_overrides or {}
    import_lines: list[str] = []
    evidence_rows: list[list[Any]] = []
    reasons = Counter()
    eligible_occurrences = 0
    for key, group in grouped.items():
        if key in existing_overrides:
            reasons["already_manually_reviewed"] += 1
            continue
        if not group:
            continue
        aot_sets = {tuple(sorted(row["aot"])) for row in group}
        wikt_sets = {tuple(sorted(row["wikt"])) for row in group}
        if len(aot_sets) != 1 or len(wikt_sets) != 1:
            reasons["reference_variants_differ_between_occurrences"] += 1
            continue
        aot = set(next(iter(aot_sets)))
        wikt = set(next(iter(wikt_sets)))
        if len(aot) != 1 or len(wikt) != 1 or aot != wikt:
            reasons["no_single_aot_wiktionary_consensus"] += 1
            continue
        expected = next(iter(aot))
        if any(row["quality_status"] == "CONTEXTUAL_VARIANT_ACCEPTED" for row in group):
            reasons["contextual_variant_exception"] += 1
            continue
        baseline_positions = {
            None if row["baseline_position"] in (None, "", "null") else int(row["baseline_position"])
            for row in group
        }
        combined_positions = {
            None if row["combined_position"] in (None, "", "null") else int(row["combined_position"])
            for row in group
        }
        # Every occurrence must be corrected to the single reference position. A
        # mixture means a homograph, contextual stress, or unstable model output.
        if combined_positions != {expected}:
            reasons["ruaccent_not_consistent_with_reference_for_every_occurrence"] += 1
            continue
        if expected in baseline_positions:
            reasons["ruvoice_already_correct_in_some_occurrences"] += 1
            continue
        if None in baseline_positions:
            reasons["baseline_unmarked_occurrence"] += 1
            continue
        if len(baseline_positions) != 1:
            reasons["baseline_has_multiple_wrong_positions"] += 1
            continue

        variants = {row["source_word"] for row in group}
        if len(variants) != 1:
            reasons["orthographic_variants_share_normalized_key"] += 1
            continue
        word = next(iter(variants))
        marked = marker_for_word(word, expected)
        if marked is None:
            reasons["invalid_target_position"] += 1
            continue
        import_lines.append(f"{key} {marked}")
        eligible_occurrences += len(group)
        first = group[0]
        chapters = sorted({row["chapter"] for row in group if row["chapter"]})
        samples = []
        for row in group:
            context = row["context"]
            if context and context not in samples and len(samples) < 5:
                samples.append(context)
        evidence_rows.append([
            key, len(group), ",".join(str(x) for x in sorted(baseline_positions)),
            expected, ",".join(str(x) for x in sorted(aot)),
            ",".join(str(x) for x in sorted(wikt)), ";".join(chapters),
            "; ".join(samples),
            first["aot_details"], first["wikt_details"],
        ])
        reasons["auto_corrected_wordforms"] += 1

    import_lines.sort()
    evidence_rows.sort(key=lambda row: (-int(row[1]), row[0]))
    summary = {
        "automatic_override_wordforms": len(import_lines),
        "automatic_override_occurrences": eligible_occurrences,
        "candidate_wordforms_examined": len(grouped),
        "excluded_wordforms_by_reason": dict(reasons),
        "skipped_occurrences_by_reason": dict(skipped),
        "policy": (
            "A word is emitted only when every occurrence in the EPUB is aligned, "
            "AOT and Wiktionary each expose exactly one identical stress position, "
            "production RUAccent agrees with that position at every occurrence, "
            "and baseline RuVoice is consistently different at every occurrence. "
            "Words with ё, service words, contextual exceptions, and mixed variants are excluded."
        ),
    }
    return import_lines, evidence_rows, summary


def write_tsv(path: Path, headers: list[str], rows: list[list[Any]]) -> None:
def write_tsv(path: Path, headers: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(headers)
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paired-json", type=Path, required=True)
    parser.add_argument("--system-dictionary", type=Path, required=True)
    parser.add_argument("--auto-dictionary", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--quality-occurrences", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    paired = json.loads(args.paired_json.read_text(encoding="utf-8"))
    system = read_marked_dictionary(args.system_dictionary)
    auto = read_marked_dictionary(args.auto_dictionary)
    provenance = read_provenance(args.provenance)
    quality_occurrences = read_quality_occurrences(args.quality_occurrences)

    raw_rows = paired.get("review_candidates", [])
    if not raw_rows:
        raise SystemExit("The paired evaluator has no review_candidates; rerun the full-book evaluator.")

    detail_rows: list[list[Any]] = []
    quality_rows_joined = 0
    quality_rows_missing = 0
    quality_missing_words: set[str] = set()
    grouped: dict[tuple[str, int | None, int | None, str], list[dict[str, Any]]] = defaultdict(list)

    for row in raw_rows:
        before = str(row.get("before", ""))
        after = str(row.get("after", ""))
        word = str(row.get("word", normalize(before)))
        key = normalize(word)
        before_pos = row.get("stress_before_vowel_index")
        after_pos = row.get("stress_after_vowel_index")
        before_pos = None if before_pos is None else int(before_pos)
        after_pos = None if after_pos is None else int(after_pos)

        if before_pos is not None and after_pos is not None and before_pos != after_pos:
            change_kind = "STRESS_MOVED"
        elif before_pos is not None and after_pos is None:
            change_kind = "MULTISYLLABIC_STRESS_REMOVED"
        elif before_pos is None and after_pos is not None:
            change_kind = "MULTISYLLABIC_STRESS_ADDED"
        else:
            change_kind = str(row.get("type", "OTHER"))

        is_clitic = key in {"нибудь", "таки", "либо"}
        sys_positions = system.get(key, set())
        auto_positions = auto.get(key, set())
        auto_sources = provenance.get(key, set())
        curated_consensus_positions = (
            auto_positions if "aot_wiktionary_silero_consensus" in auto_sources else set()
        )
        quality_key = (int(row["segment_index"]), int(row["word_index"]))
        quality_row = quality_occurrences.get(quality_key)
        aot_positions, wiktionary_positions, consensus_positions, consensus_verdict = (
            quality_source_assessment(quality_row, before_pos, after_pos)
        )
        quality_rows_joined += quality_row is not None
        quality_rows_missing += quality_row is None
        if quality_row is None:
            quality_missing_words.add(word)

        if is_clitic:
            consensus_verdict = "NOT_A_DICTIONARY_WORD: clitic/particle"

        if is_clitic:
            system_verdict = "CLITIC_NOT_FOR_STRESS_DICTIONARY"
        elif not sys_positions:
            system_verdict = "NO_BUILTIN_ENTRY"
        elif after_pos in sys_positions and before_pos not in sys_positions:
            system_verdict = "BUILTIN_SUPPORTS_RUACCENT"
        elif before_pos in sys_positions and after_pos not in sys_positions:
            system_verdict = "BUILTIN_SUPPORTS_RUVOICE"
        elif before_pos in sys_positions and after_pos in sys_positions:
            system_verdict = "BUILTIN_ALLOWS_BOTH"
        else:
            system_verdict = "BUILTIN_OTHER_OR_CONFLICT"

        priority = "MANUAL_REVIEW_REQUIRED"
        if is_clitic:
            priority = "EXCLUDE_FROM_WORD_DICTIONARY"
        elif consensus_verdict == "CONTEXTUAL_VARIANT_ACCEPTED":
            priority = "CONTEXTUAL_VARIANT_ACCEPTED_BY_FULL_QUALITY_AUDIT"
        elif consensus_verdict == "CONSENSUS_SUPPORTS_RUACCENT" and system_verdict != "BUILTIN_SUPPORTS_RUVOICE":
            priority = "HIGHER_PRIORITY_REVIEW_RUACCENT_AND_BOTH_SOURCES_AGREE"
        elif consensus_verdict == "CONSENSUS_SUPPORTS_RUVOICE":
            priority = "HIGHER_PRIORITY_REVIEW_RUVOICE_AND_BOTH_SOURCES_AGREE"
        elif consensus_verdict == "CONSENSUS_SUPPORTS_BOTH_VARIANTS":
            priority = "BOTH_STRESS_VARIANTS_SUPPORTED_BY_BOTH_SOURCES"
        elif consensus_verdict == "SINGLE_SOURCE_SUPPORTS_RUACCENT":
            priority = "MANUAL_REVIEW_SINGLE_SOURCE_SUPPORTS_RUACCENT"
        elif consensus_verdict == "SINGLE_SOURCE_SUPPORTS_RUVOICE":
            priority = "MANUAL_REVIEW_SINGLE_SOURCE_SUPPORTS_RUVOICE"
        elif consensus_verdict == "AOT_WIKTIONARY_DISAGREE_NO_SHARED_VARIANT":
            priority = "MANUAL_REVIEW_AOT_WIKTIONARY_DISAGREE"
        elif system_verdict == "BUILTIN_ALLOWS_BOTH":
            priority = "NORMATIVE_VARIANT_OR_SYSTEM_ALLOWS_BOTH"
        elif system_verdict == "BUILTIN_SUPPORTS_RUVOICE":
            priority = "REVIEW_RUACCENT_CONFLICTS_WITH_BUILTIN"

        detail_rows.append([
            priority, change_kind, word, before, after,
            "" if before_pos is None else before_pos,
            "" if after_pos is None else after_pos,
            render_positions(sys_positions), system_verdict,
            render_positions(consensus_positions), ";".join(sorted(auto_sources)),
            consensus_verdict, row.get("chapter", ""), row.get("paragraph", ""),
            row.get("part", ""), row.get("word_index", ""), row.get("context", ""),
            render_positions(aot_positions), render_positions(wiktionary_positions),
            render_positions(curated_consensus_positions),
            quality_row.get("aot_source_details", "") if quality_row else "",
            quality_row.get("wiktionary_source_details", "") if quality_row else "",
            quality_row.get("baseline_status", "") if quality_row else "",
            quality_row.get("reviewed_status", "") if quality_row else "",
        ])
        grouped[(key, before_pos, after_pos, change_kind)].append(row)

    detail_rows.sort(key=lambda r: (
        0 if r[0].startswith("HIGHER_PRIORITY_REVIEW_RUACCENT") else
        1 if r[0].startswith("REVIEW_RUACCENT") else
        2 if r[0] == "MANUAL_REVIEW_REQUIRED" else 3,
        r[2], r[12], int(r[13] or 0), int(r[14] or 0)
    ))

    pair_rows: list[list[Any]] = []
    for (key, before_pos, after_pos, change_kind), group in grouped.items():
        before_variants = sorted({str(r.get("before", "")) for r in group})
        after_variants = sorted({str(r.get("after", "")) for r in group})
        chapters = sorted({str(r.get("chapter", "")) for r in group})
        pair_rows.append([
            key, " / ".join(before_variants), " / ".join(after_variants),
            change_kind, len(group), before_pos if before_pos is not None else "",
            after_pos if after_pos is not None else "", ";".join(chapters),
            str(group[0].get("context", ""))[:500],
        ])
    pair_rows.sort(key=lambda r: (-int(r[4]), r[0], r[3]))

    summary = {
        "book": paired.get("book_file"),
        "paragraphs": paired.get("paragraphs"),
        "segments": paired.get("segments"),
        "words_compared": paired.get("words_compared"),
        "all_stress_changes": paired.get("stress_position_changes"),
        "review_candidate_occurrences": len(raw_rows),
        "review_unique_keys": len({normalize(str(r.get("word", ""))) for r in raw_rows}),
        "review_unique_change_pairs": len(grouped),
        "quality_candidate_rows_joined": quality_rows_joined,
        "quality_candidate_rows_missing": quality_rows_missing,
        "quality_missing_occurrence_words": sorted(quality_missing_words),
        "contextual_variants_accepted_by_full_quality_audit": sum(1 for r in detail_rows if r[11] == "CONTEXTUAL_VARIANT_ACCEPTED"),
        "consensus_supports_ruaccent": sum(1 for r in detail_rows if r[11] == "CONSENSUS_SUPPORTS_RUACCENT"),
        "consensus_supports_ruvoice": sum(1 for r in detail_rows if r[11] == "CONSENSUS_SUPPORTS_RUVOICE"),
        "consensus_supports_both_variants": sum(1 for r in detail_rows if r[11] == "CONSENSUS_SUPPORTS_BOTH_VARIANTS"),
        "single_source_supports_ruaccent": sum(1 for r in detail_rows if r[11] == "SINGLE_SOURCE_SUPPORTS_RUACCENT"),
        "single_source_supports_ruvoice": sum(1 for r in detail_rows if r[11] == "SINGLE_SOURCE_SUPPORTS_RUVOICE"),
        "aot_wiktionary_disagree": sum(1 for r in detail_rows if r[11] == "AOT_WIKTIONARY_DISAGREE_NO_SHARED_VARIANT"),
        "no_independent_reference": sum(1 for r in detail_rows if r[11] == "NO_INDEPENDENT_REFERENCE"),
        "builtin_supports_ruaccent": sum(1 for r in detail_rows if r[8] == "BUILTIN_SUPPORTS_RUACCENT"),
        "builtin_supports_ruvoice": sum(1 for r in detail_rows if r[8] == "BUILTIN_SUPPORTS_RUVOICE"),
        "clitic_occurrences_excluded": sum(1 for r in detail_rows if r[0] == "EXCLUDE_FROM_WORD_DICTIONARY"),
        "accuracy_claim": "NOT_MEASURED: model differences and dictionary agreement are evidence for review, not a gold-labelled accuracy score.",
        "context_note": "Full sentence context appears only in the short-lived GitHub Actions artifact, not in the repository commit or workflow logs.",
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_tsv(
        args.output_dir / "Book_Full_Stress_Review.tsv",
        ["priority", "change_type", "word_key", "ruvoice_output", "ruaccent_merged_output",
         "ruvoice_stress_vowel_index", "ruaccent_stress_vowel_index",
         "built_in_stress_positions", "built_in_verdict",
         "shared_aot_wiktionary_stress_positions", "curated_auto_provenance",
         "aot_wiktionary_verdict", "chapter", "paragraph", "segment_part", "word_index", "context",
         "aot_stress_positions", "wiktionary_stress_positions",
         "curated_auto_consensus_positions", "aot_source_details", "wiktionary_source_details",
         "full_quality_baseline_status", "full_quality_reviewed_status"],
        detail_rows,
    )
    write_tsv(
        args.output_dir / "Book_Full_Stress_Change_Pairs.tsv",
        ["word_key", "ruvoice_forms", "ruaccent_forms", "change_type",
         "occurrences", "ruvoice_stress_vowel_index", "ruaccent_stress_vowel_index",
         "chapters", "sample_context"],
        pair_rows,
    )
    (args.output_dir / "Book_Full_Stress_Summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("WHOLE_BOOK_STRESS_AUDIT=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    print("DETAIL_TSV=" + str(args.output_dir / "Book_Full_Stress_Review.tsv"))
    print("PAIR_TSV=" + str(args.output_dir / "Book_Full_Stress_Change_Pairs.tsv"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
