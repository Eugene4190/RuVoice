#!/usr/bin/env python3
"""Whole-book audit of real RuVoice outputs against AOT and Russian Wiktionary.

No model is treated as ground truth. For every token produced by production RuVoice,
this script attaches:
- the official AOT morphological stress alternatives;
- stressed variants extracted from the full Russian Wiktionary/Wiktextract dump;
- the built-in RuVoice stress-dictionary entry;
- the independent RUAccent output from the paired production run.

The primary measurable subset is unambiguous multisyllabic content-word forms where
AOT and Wiktionary agree on the same stress position. All other cases remain visible
as ambiguous, context-sensitive, missing-reference or manual-review records.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

VOWELS = set("аеёиоуыэюя")
WIKT_SKIP_TAGS = {"romanization", "table-tags", "inflection-template", "class", "canonical"}
ACUTE = "\u0301"
CYR = re.compile(r"^[а-яё]+$")
CYR_ACCENTED = re.compile(r"^[а-яё\u0301-]+$")
FUNCTION_WORDS = {
    "а", "и", "но", "да", "или", "ли", "не", "ни", "бы", "же", "в", "во",
    "на", "над", "под", "с", "со", "к", "ко", "у", "о", "об", "от", "до",
    "из", "за", "по", "при", "для", "без", "через", "перед", "после",
    "между", "около", "вокруг", "как", "что", "чтобы", "если", "когда",
    "где", "кто", "то", "это", "вот", "там", "тут", "уже", "лишь", "ведь",
    "либо", "нибудь", "таки", "обо",
}


def norm(value: str) -> str:
    return value.lower().replace("+", "").replace(ACUTE, "").replace("ё", "е")


def vowel_position(marked: str, marker: str) -> int | None:
    if marker not in marked:
        return None
    char_index = marked.rfind(marker)
    if marker == ACUTE:
        char_index -= 1
    if char_index < 0:
        return None
    return sum(ch.lower() in VOWELS for ch in marked[:char_index])


def marked_position(marked: str) -> int | None:
    if "+" not in marked:
        return None
    return vowel_position(marked, "+")


def acute_position(marked: str) -> int | None:
    return vowel_position(marked, ACUTE)


def read_ruvoice_system(path: Path) -> dict[str, set[int]]:
    result: dict[str, set[int]] = defaultdict(set)
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.replace("=", " ", 1).split()
        if len(parts) < 2:
            continue
        pos = marked_position(parts[1].lower())
        if pos is not None:
            result[norm(parts[0])].add(pos)
    return result


def add_ref(
    mapping: dict[str, dict[int, set[str]]],
    word: str,
    position: int | None,
    detail: str,
) -> None:
    if position is None or not word:
        return
    mapping[norm(word)][position].add(detail)


def load_aot(path: Path, target_words: set[str]) -> dict[str, dict[int, set[str]]]:
    morph_path = path / "morphs.json"
    gramtab_path = path / "gramtab.json"
    if not morph_path.is_file() or not gramtab_path.is_file():
        raise FileNotFoundError(f"В AOT не найдены {morph_path} и {gramtab_path}")
    data = json.loads(morph_path.read_text(encoding="utf-8"))
    gramtab = json.loads(gramtab_path.read_text(encoding="utf-8"))["gramcodes"]
    flexia_models = data["flexia_models"]
    accent_models = data["accent_models"]
    result: dict[str, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    scanned = 0

    for lemma_data in data["lemmas"]:
        acc_model = accent_models[lemma_data["a"]]
        if all(value == 255 for value in acc_model):
            continue
        flexia = flexia_models[lemma_data["f"]]
        first_ending = flexia["endings"][0]["flexia"]
        lemma = lemma_data["l"]
        stem = lemma[:len(lemma) - len(first_ending)] if first_ending and lemma.endswith(first_ending) else lemma
        common = gramtab.get(lemma_data.get("t", ""), {}).get("g", [])

        for ending, accent_from_end in zip(flexia["endings"], acc_model):
            if accent_from_end == 255:
                continue
            form = (ending.get("prefix", "") + stem + ending["flexia"]).lower()
            key = norm(form)
            if key not in target_words:
                continue
            vowel_indices = [i for i, char in enumerate(form) if char in VOWELS]
            if accent_from_end >= len(vowel_indices):
                continue
            stressed_char = vowel_indices[len(vowel_indices) - 1 - accent_from_end]
            stress_pos = sum(char in VOWELS for char in form[:stressed_char])
            gram = gramtab.get(ending["gramcode"], {})
            detail = ":".join([
                lemma.lower(),
                gram.get("p", ""),
                ",".join(common + gram.get("g", [])),
            ])
            result[key][stress_pos].add(detail)
            scanned += 1

    print(f"AOT_BOOK_FORMS={len(result)} AOT_MATCHED_MORPH_FORMS={scanned}", flush=True)
    return result


def wikt_mark(form: str) -> tuple[str, int | None] | None:
    cleaned = form.lower()
    if not CYR_ACCENTED.fullmatch(cleaned):
        return None
    bare = cleaned.replace(ACUTE, "")
    if not CYR.fullmatch(bare):
        return None
    if ACUTE in cleaned:
        pos = vowel_position(cleaned, ACUTE)
        return bare, pos
    # Match the upstream RU Wiktionary extraction: ё is intrinsically stressed.
    if "ё" in bare:
        idx = bare.index("ё")
        return bare, sum(ch in VOWELS for ch in bare[:idx])
    return None


def load_wiktionary(path: Path, target_words: set[str]) -> dict[str, dict[int, set[str]]]:
    result: dict[str, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    articles = 0
    matched_forms = 0
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get("lang_code") != "ru":
                continue
            articles += 1
            lemma = str(data.get("word", "")).lower()
            pos = str(data.get("pos", ""))
            forms = list(data.get("forms", []))
            forms.append({"form": data.get("word", ""), "tags": ["lemma"]})
            for form_data in forms:
                if WIKT_SKIP_TAGS.intersection(str(tag) for tag in form_data.get("tags", [])):
                    continue
                form_text = str(form_data.get("form", "")).lower()
                parsed = wikt_mark(form_text)
                if parsed is None:
                    continue
                bare, position = parsed
                key = norm(bare)
                if key not in target_words:
                    continue
                tags = [str(x) for x in form_data.get("tags", [])]
                detail = lemma + ":" + pos + ":" + ",".join(tags)
                result[key][position].add(detail)
                matched_forms += 1
            if articles % 100000 == 0:
                print(f"WIKTIONARY_PROGRESS articles={articles} target_matches={matched_forms}", flush=True)

    print(f"WIKTIONARY_BOOK_FORMS={len(result)} WIKTIONARY_MATCHED_FORMS={matched_forms} ARTICLES={articles}", flush=True)
    return result


def positions_text(source: dict[int, set[str]]) -> str:
    return ";".join(
        f"{position}:{'|'.join(sorted(details)[:8])}"
        for position, details in sorted(source.items())
    )


def variants_text(source: dict[int, set[str]]) -> str:
    return ",".join(str(position) for position in sorted(source))


def verdict(
    key: str,
    base_position: int | None,
    ruaccent_position: int | None,
    aot: dict[int, set[str]],
    wikt: dict[int, set[str]],
    system: set[int],
) -> tuple[str, str]:
    vowels = sum(ch in VOWELS for ch in key)
    if key in FUNCTION_WORDS:
        return "FUNCTION_WORD_CONTEXT_REQUIRED", "Служебное слово/частица; словарное ударение не равно фразовому"
    if vowels < 2:
        return "MONOSYLLABLE_NOT_SCORED", "Односложное слово: отдельное ударение в словаре не оценивается"
    if aot and wikt:
        aot_positions = set(aot)
        wikt_positions = set(wikt)
        common = aot_positions & wikt_positions
        if len(aot_positions) == 1 and len(wikt_positions) == 1 and len(common) == 1:
            agreed = next(iter(common))
            base_ok = base_position == agreed
            ruaccent_ok = ruaccent_position == agreed
            if base_ok and ruaccent_ok:
                return "BOTH_MATCH_AOT_WIKT", "RuVoice и RUAccent совпали с единственным AOT/Wiktionary вариантом"
            if not base_ok and ruaccent_ok and base_position in system:
                return "BUILTIN_DICTIONARY_CONFLICTS_WITH_AOT_WIKT", "Встроенный словарь поддерживает RuVoice, но AOT и Wiktionary согласны с RUAccent"
            if not base_ok and ruaccent_ok:
                return "RUVOICE_DIFFERS_RUACCENT_AND_BOTH_DICTS_AGREE", "RUAccent и оба словаря согласны против RuVoice"
            if base_ok and not ruaccent_ok:
                return "RUACCENT_DIFFERS_RUVOICE_AND_BOTH_DICTS_AGREE", "RuVoice и оба словаря согласны против RUAccent"
            return "BOTH_DIFFER_FROM_AOT_WIKT", "Обе модели расходятся с согласным вариантом двух словарей"
        if common:
            if base_position in common:
                return "BASELINE_ONE_OF_SHARED_VARIANTS", "Ударение RuVoice входит в общий набор допустимых вариантов"
            return "SHARED_VARIANTS_BUT_BASELINE_OUTSIDE", "Источники имеют общие варианты, но RuVoice вне них"
        return "AOT_WIKT_DISAGREE", "AOT и Wiktionary дают разные ударения"
    if aot or wikt:
        source = aot if aot else wikt
        name = "AOT" if aot else "WIKTIONARY"
        if len(source) > 1:
            return "SINGLE_SOURCE_MULTIPLE_VARIANTS", f"{name} допускает несколько вариантов"
        pos = next(iter(source))
        if base_position == pos:
            return "SINGLE_SOURCE_SUPPORTS_RUVOICE", f"Только {name} найден; совпадает с RuVoice"
        if ruaccent_position == pos:
            return "SINGLE_SOURCE_SUPPORTS_RUACCENT", f"Только {name} найден; совпадает с RUAccent"
        return "SINGLE_SOURCE_DIFFERS_FROM_BOTH", f"Только {name} найден и не совпадает с моделями"
    if system:
        if base_position in system:
            return "BUILTIN_SUPPORTS_RUVOICE_ONLY", "Есть встроенная словарная запись, но независимые источники не нашлись"
        return "BUILTIN_DIFFERS_OR_AMBIGUOUS", "Встроенная запись не подтверждает результат RuVoice"
    return "NO_INDEPENDENT_REFERENCE", "Независимая словарная форма не найдена"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paired-json", type=Path, required=True)
    parser.add_argument("--aot-dir", type=Path, required=True)
    parser.add_argument("--wiktionary-gz", type=Path, required=True)
    parser.add_argument("--system-dictionary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    paired = json.loads(args.paired_json.read_text(encoding="utf-8"))
    tokens = paired.get("baseline_tokens", [])
    contexts = paired.get("segment_contexts", [])
    if not tokens:
        raise SystemExit("В paired JSON нет baseline_tokens. Нужен новый полный production-run.")

    context_by_segment = {
        int(row["segment_index"]): str(row.get("context", ""))
        for row in contexts
    }
    target_words = {
        norm(str(row.get("source_word") if row.get("source_word") not in (None, "null") else row.get("ruvoice_output", "")))
        for row in tokens
    }
    target_words = {word for word in target_words if CYR.fullmatch(word)}
    print(f"BOOK_BASELINE_TOKENS={len(tokens)} BOOK_UNIQUE_FORMS={len(target_words)}", flush=True)

    aot = load_aot(args.aot_dir, target_words)
    wikt = load_wiktionary(args.wiktionary_gz, target_words)
    system = read_ruvoice_system(args.system_dictionary)

    # Use the complete independently merged token stream, not only changed-token samples.
    ruaccent_by_occurrence: dict[tuple[int, int], str] = {}
    for row in paired.get("combined_tokens", []):
        if "segment_index" in row and "word_index" in row:
            ruaccent_by_occurrence[(int(row["segment_index"]), int(row["word_index"]))] = str(
                row.get("ruaccent_merged_output", "")
            )
    # Backward-compatible fallback for an older paired report.
    if not ruaccent_by_occurrence:
        for row in paired.get("changes", []):
            if "segment_index" not in row or "word_index" not in row:
                continue
            if row.get("type") in {"STRESS", "STRESS_AND_YO", "YO"}:
                ruaccent_by_occurrence[(int(row["segment_index"]), int(row["word_index"]))] = str(row.get("after", ""))

    occurrence_rows: list[list[Any]] = []
    aggregate: dict[str, dict[str, Any]] = {}
    counts = Counter()
    for token in tokens:
        source_word = token.get("source_word")
        output_word = str(token.get("ruvoice_output", ""))
        if source_word in (None, "null"):
            source_word = output_word
        source_word = str(source_word)
        key = norm(source_word)
        if not CYR.fullmatch(key):
            continue
        segment_index = int(token.get("segment_index", -1))
        word_index = int(token.get("word_index", -1))
        ruaccent_word = ruaccent_by_occurrence.get((segment_index, word_index), output_word)
        base_position = token.get("ruvoice_stress_vowel_index")
        base_position = None if base_position in (None, "null") else int(base_position)
        ruaccent_position = acute_position(ruaccent_word)
        system_positions = system.get(key, set())
        aot_positions = aot.get(key, {})
        wikt_positions = wikt.get(key, {})
        status, reason = verdict(
            key, base_position, ruaccent_position, aot_positions, wikt_positions, system_positions
        )
        context = context_by_segment.get(segment_index, "")
        counts[status] += 1
        if key not in aggregate:
            aggregate[key] = {
                "frequency": 0, "base_positions": Counter(), "ruaccent_positions": Counter(),
                "statuses": Counter(), "source_forms": Counter(), "contexts": [],
                "aot": aot_positions, "wikt": wikt_positions, "system": system_positions,
            }
        item = aggregate[key]
        item["frequency"] += 1
        item["base_positions"][base_position if base_position is not None else "UNMARKED"] += 1
        item["ruaccent_positions"][ruaccent_position if ruaccent_position is not None else "UNMARKED"] += 1
        item["statuses"][status] += 1
        item["source_forms"][output_word] += 1
        if context and len(item["contexts"]) < 4:
            item["contexts"].append(context)

        occurrence_rows.append([
            status, source_word, output_word, ruaccent_word,
            "" if base_position is None else base_position,
            "" if ruaccent_position is None else ruaccent_position,
            variants_text(aot_positions), variants_text(wikt_positions),
            variants_text(system_positions), token.get("segment_index", ""),
            token.get("word_index", ""), token.get("chapter", ""),
            token.get("paragraph", ""), context,
            reason,
        ])

    # Rank unique words by severity and how often they appear.
    priority_order = {
        "BOTH_DIFFER_FROM_AOT_WIKT": 0,
        "BUILTIN_DICTIONARY_CONFLICTS_WITH_AOT_WIKT": 1,
        "RUVOICE_DIFFERS_RUACCENT_AND_BOTH_DICTS_AGREE": 1,
        "SHARED_VARIANTS_BUT_BASELINE_OUTSIDE": 2,
        "SINGLE_SOURCE_DIFFERS_FROM_BOTH": 3,
        "RUACCENT_DIFFERS_RUVOICE_AND_BOTH_DICTS_AGREE": 4,
        "AOT_WIKT_DISAGREE": 5,
        "SINGLE_SOURCE_MULTIPLE_VARIANTS": 6,
        "BUILTIN_DIFFERS_OR_AMBIGUOUS": 7,
        "NO_INDEPENDENT_REFERENCE": 8,
        "FUNCTION_WORD_CONTEXT_REQUIRED": 9,
        "MONOSYLLABLE_NOT_SCORED": 10,
        "BOTH_MATCH_AOT_WIKT": 11,
        "BASELINE_ONE_OF_SHARED_VARIANTS": 12,
        "SINGLE_SOURCE_SUPPORTS_RUVOICE": 13,
        "SINGLE_SOURCE_SUPPORTS_RUACCENT": 14,
        "BUILTIN_SUPPORTS_RUVOICE_ONLY": 15,
    }
    unique_rows: list[list[Any]] = []
    for key, item in aggregate.items():
        top_status = min(item["statuses"], key=lambda st: priority_order.get(st, 99))
        base_summary = ",".join(f"{k}:{v}" for k, v in item["base_positions"].most_common())
        ruaccent_summary = ",".join(f"{k}:{v}" for k, v in item["ruaccent_positions"].most_common())
        unique_rows.append([
            top_status, key, item["frequency"], base_summary, ruaccent_summary,
            variants_text(item["aot"]), variants_text(item["wikt"]), variants_text(item["system"]),
            ";".join(f"{k}:{v}" for k, v in item["statuses"].most_common()),
            " || ".join(item["contexts"]),
        ])
    unique_rows.sort(key=lambda row: (
        priority_order.get(row[0], 99), -int(row[2]), row[1]
    ))
    occurrence_rows.sort(key=lambda row: (
        priority_order.get(row[0], 99), row[1], int(row[9]), int(row[10])
    ))

    total = sum(item["frequency"] for item in aggregate.values())
    scored = {
        "BOTH_MATCH_AOT_WIKT", "BASELINE_ONE_OF_SHARED_VARIANTS",
        "RUVOICE_DIFFERS_RUACCENT_AND_BOTH_DICTS_AGREE",
        "RUACCENT_DIFFERS_RUVOICE_AND_BOTH_DICTS_AGREE",
        "BOTH_DIFFER_FROM_AOT_WIKT", "AOT_WIKT_DISAGREE",
        "SINGLE_SOURCE_SUPPORTS_RUVOICE", "SINGLE_SOURCE_SUPPORTS_RUACCENT",
        "SINGLE_SOURCE_DIFFERS_FROM_BOTH", "SINGLE_SOURCE_MULTIPLE_VARIANTS",
        "SHARED_VARIANTS_BUT_BASELINE_OUTSIDE",
    }
    scored_count = sum(counts[s] for s in scored)
    baseline_agree = counts["BOTH_MATCH_AOT_WIKT"] + counts["BASELINE_ONE_OF_SHARED_VARIANTS"] + counts["SINGLE_SOURCE_SUPPORTS_RUVOICE"]
    ruaccent_agree = counts["BOTH_MATCH_AOT_WIKT"] + counts["BASELINE_ONE_OF_SHARED_VARIANTS"] + counts["SINGLE_SOURCE_SUPPORTS_RUACCENT"]
    summary = {
        "book": paired.get("book_file"),
        "tokens_from_ruvoice": len(tokens),
        "valid_russian_occurrences": total,
        "unique_wordforms": len(aggregate),
        "aot_forms_found": len(aot),
        "wiktionary_forms_found": len(wikt),
        "word_occurrences_with_some_independent_reference": sum(counts[s] for s in scored),
        "occurrences_in_strict_aot_wikt_single_stress_consensus": (
            counts["BOTH_MATCH_AOT_WIKT"] +
            counts["BUILTIN_DICTIONARY_CONFLICTS_WITH_AOT_WIKT"] +
            counts["RUVOICE_DIFFERS_RUACCENT_AND_BOTH_DICTS_AGREE"] +
            counts["RUACCENT_DIFFERS_RUVOICE_AND_BOTH_DICTS_AGREE"] +
            counts["BOTH_DIFFER_FROM_AOT_WIKT"]
        ),
        "ruvoice_matches_two_source_consensus_and_variants": counts["BOTH_MATCH_AOT_WIKT"] + counts["BASELINE_ONE_OF_SHARED_VARIANTS"],
        "ruvoice_suspected_mismatches_against_two_sources": counts["RUVOICE_DIFFERS_RUACCENT_AND_BOTH_DICTS_AGREE"] + counts["BUILTIN_DICTIONARY_CONFLICTS_WITH_AOT_WIKT"] + counts["SHARED_VARIANTS_BUT_BASELINE_OUTSIDE"],
        "ruaccent_matches_two_source_consensus_and_variants": (counts["BOTH_MATCH_AOT_WIKT"] + counts["BASELINE_ONE_OF_SHARED_VARIANTS"] + counts["BUILTIN_DICTIONARY_CONFLICTS_WITH_AOT_WIKT"] + counts["RUVOICE_DIFFERS_RUACCENT_AND_BOTH_DICTS_AGREE"]),
        "ruaccent_suspected_mismatches_against_two_sources": counts["RUACCENT_DIFFERS_RUVOICE_AND_BOTH_DICTS_AGREE"] + counts["BOTH_DIFFER_FROM_AOT_WIKT"],
        "unscored_function_word_occurrences": counts["FUNCTION_WORD_CONTEXT_REQUIRED"],
        "unscored_monosyllable_occurrences": counts["MONOSYLLABLE_NOT_SCORED"],
        "no_independent_reference_occurrences": counts["NO_INDEPENDENT_REFERENCE"],
        "status_counts": dict(counts),
        "warning": "This is a dictionary/model agreement audit, not a gold accuracy score. AOT/Wiktionary variants may be incomplete; context, homographs and phrase stress still require review.",
        "full_word_context_is_in_temporary_artifact_only": True,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "WholeBook_RuVoice_AllOccurrences.tsv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow([
            "status", "source_form", "ruvoice_output", "ruaccent_output",
            "ruvoice_stress_vowel_index", "ruaccent_stress_vowel_index",
            "aot_stress_positions", "wiktionary_stress_positions",
            "built_in_stress_positions", "segment_index", "word_index",
            "chapter", "paragraph", "context", "reason",
        ])
        writer.writerows(occurrence_rows)

    with (args.output_dir / "WholeBook_RuVoice_UniqueWords.tsv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow([
            "priority_status", "word", "book_frequency",
            "ruvoice_position_counts", "ruaccent_position_counts",
            "aot_positions", "wiktionary_positions", "built_in_positions",
            "occurrence_status_counts", "sample_contexts",
        ])
        writer.writerows(unique_rows)

    (args.output_dir / "WholeBook_RuVoice_Quality_Summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("WHOLE_BOOK_RUVOICE_QUALITY=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    print("ALL_OCCURRENCES_TSV=" + str(args.output_dir / "WholeBook_RuVoice_AllOccurrences.tsv"))
    print("UNIQUE_WORDS_TSV=" + str(args.output_dir / "WholeBook_RuVoice_UniqueWords.tsv"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
