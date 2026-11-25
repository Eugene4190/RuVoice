# Intermediate checkpoint — 2026-11-25

Checkpoint branch: `stress-dictionary-pipeline`
Checkpoint code revision before this note: `d11c2c7923c0989109c39025af9ea9b0b52fbe29`
Pull request: #1 (Draft, not merged)
Base `main` revision: `e0f89575d872461282f719f3a04709d5436f4b45`

## What is saved

All work below is committed on the checkpoint branch; no changes have been merged to `main`.

1. Full-book paired evaluator:
   - Runs production RuVoice, production RUAccent correction and a reviewed-overlay comparison across EPUB fragments.
   - Saves token-level alignment, chapter/paragraph and sentence context.
2. Whole-book reference audit:
   - Joins every token occurrence to AOT and Russian Wiktionary stress variants.
   - Distinguishes source agreement, source disagreement, contextual exceptions and missing references.
3. Book stress-difference audit:
   - Saves all model differences with occurrence coordinates and short context.
   - Generates a conservative AOT/Wiktionary consensus candidate file. This is intentionally not treated as complete or as a gold accuracy score.
4. New automatic correction tier:
   - Emits an importable word-level rule only when independent models agree across every occurrence and a dictionary source supports the same single stress position.
   - Keeps repeated out-of-dictionary (OOV) model consensus separate as a review queue, never silently importing it.
   - Has synthetic tests for agreement, mixed variants, context exceptions and repeat occurrences.
5. Third-model whole-book pass:
   - Adds an independent character-level Russian stress predictor.
   - Aligns its predictions against the production RuVoice and RUAccent outputs by segment and word index.
   - Outputs per-occurrence results, disagreement groups, confirmed candidates and a separate OOV review list.

## Verified at checkpoint time

- Python dictionary/workflow test suite: passed on `d11c2c7` (GitHub Actions run 45698615939).
- Kotlin Full/Lite stress-merge JVM tests: passed on `d11c2c7` (run 45698615961).
- Windows portable tool build and synthetic EPUB-upload-to-ZIP smoke test: passed on `d11c2c7` (run 45698615899).
- Android APK packaging run 45698615921 failed during Android SDK NDK package installation (corrupt/incomplete package download); the Android app build was not verified by that run.
- Full real-book paired evaluation run 45698604839 was still running at step 16, “Run the real baseline and merged pipelines over every EPUB fragment”. It had not yet produced the new third-model report at checkpoint time.

## Existing full-book baseline diagnostic (earlier completed run)

An earlier completed report for the EPUB recorded 64,559 token occurrences and 14,199 distinct wordforms. It identified 129 RuVoice/RUAccent change occurrences for contextual review, while the two strict dictionary sources supported only a small subset as unambiguous corrections. These figures describe that earlier two-model/reference audit, not the new three-model output and not a count of all actual mispronunciations.

## Known limitations / do not claim complete

- The third-model inference has not yet been validated on the full book at this checkpoint.
- Model agreement is evidence, not ground truth; rare author-created words may still need context review.
- Repeated OOV consensus is a candidate queue, not an import-ready dictionary.
- The existing local Windows user workflow is not yet wired to consume and package the new whole-book audit artifacts.
- No user listening test or real-phone playback test has been performed for these new changes.

## Resume point

1. Finish or inspect the in-progress real-book paired evaluation (run 45698604839).
2. Run the third-model audit against the saved paired JSON and whole-book quality TSV.
3. Inspect actual counts and high-frequency disagreement groups; manually verify ambiguous/contextual cases.
4. Integrate only justified book-scoped corrections and OOV review candidates into the Windows ZIP workflow.
5. Re-run all relevant tests and package the final book-specific import files.

Do not merge PR #1 or describe this checkpoint as a finished correction tool until those steps are complete.
