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
