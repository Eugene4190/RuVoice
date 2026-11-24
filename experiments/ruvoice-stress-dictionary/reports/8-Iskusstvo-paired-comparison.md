# Paired comparison: original RuVoice vs production RUAccent merge

Run: [GitHub Actions #45463289467](https://github.com/Eugene4190/RuVoice/actions/runs/45463289467)  
Commit tested: `383f842835e61e32928b044306a468116e2fa4c0`  
Result: **success** (production Gradle/JVM inference completed over the complete EPUB).

The comparison used the production `Pipeline.accent + Stress` path:
- baseline: original Silero + current system dictionary, without the independent RUAccent corrector;
- merged: same production path with the RUAccent ONNX corrector and protected grammar/BERT merge.

## Whole-book counts

| Metric | Result |
|---|---:|
| EPUB paragraphs | 2,472 |
| Inference segments | 4,850 |
| Word tokens compared | 65,109 |
| Segments whose output changed | 3,656 |
| Tokens whose output changed | 9,654 |
| Stress-position/output changes | 9,654 |
| Stress marks removed | 9,513 |
| Stress marks moved to another vowel | 141 |
| Stress marks added | 0 |
| Spelling changes involving е/ё | 1 |
| Lexical/alignment mismatches | 0 |
| Segment alignment mismatches | 0 |

The 9,513 removed marks need interpretation, not a quality claim. Of these, 9,442 were on one-vowel (monosyllabic) tokens. The remaining 71 multisyllabic removals were concentrated in clitic-like/function forms: `нибудь` (52), `таки` (12), and `либо` (7).

The 141 movement events represent 71 unique written-word pairs. Most frequent were:
- `одновреме́нно → одновре́менно` — 31 occurrences;
- `эгре́горами → эгрего́рами` — 10 occurrences;
- `созда́ли → со́здали` — 6 occurrences;
- `навсе́го → на́всего` — 5 occurrences.

These are examples of changed predictions, **not** automatically verified corrections. They need to be judged against normative sources and context before being turned into dictionary overrides.

## Hand-reviewed regression checks

- **Stress:** 5 / 5 reviewed book-specific regression cases passed.
  - `снято`: both baseline and merged pass.
  - `шелка`: merged chooses the accepted plural reading.
  - `одновременно`: merged moves the mark to the reviewed position.
  - `создали` and `создана`: merged chooses reviewed stress positions.
- **Ё spelling:** 29 / 29 reviewed book-specific regression cases passed.

## RUAccent decisions

- Stressed decisions: 45,711
- Unstressed decisions: 13,138
- Unknown decisions: 6,985

## Interpretation and limits

This is a paired output comparison, not a whole-book accuracy benchmark. The EPUB has no complete gold stress annotation, so the 9,654 changed tokens cannot be labelled “corrected” as a group. The zero lexical/alignment mismatches confirms that the corrector preserved token alignment and lexical forms in this run. The reviewed regression cases are a small, explicitly curated gold set, not a substitute for a full annotated corpus.

The JSON artifact is retained in the Actions run; this Markdown report deliberately stores only aggregate counts and a short word list, not book excerpts or paragraph contexts.

## Limited normative spot-check of changed forms

A few high-frequency changes were checked against independent normative references. This does not establish that the surrounding book usage is correct:

- `одновреме́нно → одновре́менно`: Gramota's metadictionary lists both as variants. This is an allowed variant, not proof that the new form is uniquely correct in the book: https://gramota.ru/meta/odnovremenno
- `созда́ли → со́здали`: Gramota calls `сОздали` exemplary and `создАли` conversational, while explicitly stating that both are normative: https://gramota.ru/spravka/vopros/308981
- `создана́ → со́здана`: Gramota's reference answer records both variants as correct for this form: https://gramota.ru/spravka/vopros/205625
- `лека́рства → ле́карства`: Gramota distinguishes the stress by meaning: `лека́рство` as a medicinal substance and `ле́карство` in the older sense “occupation of a healer”. Without the exact sentence we cannot decide which meaning applies: https://gramota.ru/poisk?mode=slovari&query=лекарство
- `эгре́гор → эгрего́р`: Wiktionary records the stress on `е` and also notes a variant on `о`; that is a lexical variant check, not a full verification of every inflected form: https://ru.wiktionary.org/wiki/эгрегор

The detailed 71-pair, occurrence-count list is in `8-Iskusstvo-stress-movements-review.tsv`. Every row remains marked `UNREVIEWED_NOT_GOLD` until the exact context and applicable sense are reviewed. No rows from this comparison were silently promoted into the importable user dictionary.
