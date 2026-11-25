# RuVoice pause checkpoint — 2026-11-26

## Stop point

The user explicitly requested: stop work now, record the intermediate state, and resume later.
No further source-code fixes, workflow dispatches, merges, or product work should be made until the user asks to continue.

Checkpoint created from working branch `stress-dictionary-pipeline`.

- Working branch HEAD before this checkpoint: `956dc72bcd82c066e2dc7bca0c43dbf4b3468cc0`
- Main branch/base: `e0f89575d872461282f719f3a04709d5436f4b45` (untouched)
- PR #1: https://github.com/Eugene4190/RuVoice/pull/1 (Draft; not merged)
- Existing earlier checkpoint: `docs/checkpoints/INTERMEDIATE_CHECKPOINT_2026-11-26.md`

This file is documentation only. It does not represent a successful product build.

## What is verified at this stop

1. Python stress-dictionary tools CI passed on branch HEAD `956dc72bcd82c066e2dc7bca0c43dbf4b3468cc0`:
   https://github.com/Eugene4190/RuVoice/actions/runs/45722315357

2. The full-book Kotlin paired evaluator compiles successfully in the latest Kotlin workflow before the desktop runtime assembly step. The evaluator and RUAccent bridge are staged in the Android test source set by CI.

3. The production RUAccent server / tokenizer JNI build succeeded in the whole-book workflow. Official RuVoice 1.1.3 model assets were downloaded and verified in that run.

4. The paired production evaluation did execute original RuVoice over the reference EPUB, but it did NOT finish a whole-book report. It stopped at segment index 25 because a reviewed output change was not recognized by the audit's phrase-overlay attribution:
   - baseline: `сети́`
   - reviewed: `се́ти`
   - source context: `Сети значений в потоке энергии сознания`
   The phrase is an explicitly reviewed book-only correction; it is also documented in `private-files/paired_eval/BOOK_REVIEWED_OVERRIDES.md` and `book_reviewed_replacements.txt`.

5. A code change exists in `private-files/paired_eval/UploadedEpubPairedEvaluation.kt` to match reviewed phrase changes against the original paragraph context (`segment.sourceContext`) and require phrase/word occurrence counts to line up. The latest whole-book run has not demonstrated that this fix works; the preceding failed run still reported the above mismatch. Do not assume the attribution bug is fixed.

## CI state at stop

- Latest Python run on `956dc72...`: success, run 45722315357.
- Kotlin run 45722307132 on `956dc72...`: failed in desktop runtime assembly because `:app:mockableAndroidJar` is not a task in this Android Gradle project. The full evaluator compilation step succeeded. Diagnostic step confirmed no mockable Android JAR was present in the bundle.
  https://github.com/Eugene4190/RuVoice/actions/runs/45722307132
- A second Kotlin run on the same SHA, run 45722315350, was still in progress at the last status read, at `Assemble and validate the desktop JVM runtime bundle`. Its final result was not checked after the stop request.
  https://github.com/Eugene4190/RuVoice/actions/runs/45722315350
- Last completed whole-book evaluation run on SHA `44396c3...` failed at the phrase-attribution check described above. Later branch changes have not been validated by a successful full-book run.
  https://github.com/Eugene4190/RuVoice/actions/runs/45721998502

Do not claim any of these workflows are cancelled. They were GitHub Actions runs already in flight/finished at the stop point; this pause involved making no new runs.

## Concrete engineering progress in the current continuation

- Fixed compile-scope defects in `UploadedEpubPairedEvaluation.kt`; the evaluator now compiles in CI.
- Added the real Kotlin evaluator and RUAccent bridge to the Android unit-test source set during CI.
- Fixed the local workflow's JVM entry point to use `UploadedEpubPairedEvaluationMain`, which wraps the actual JUnit production RuVoice test.
- Added a Gradle `assembleDesktopAuditRuntime` task to package production JVM classes and test/runtime dependencies.
- Removed resolution of the ambiguous Android compile classpath; use the unit-test runtime classpath.
- Added portable PyInstaller engine-root resolution: the runner can find an `engine` directory alongside the EXE or in the PyInstaller bundle.
- Added Python tests for the launcher and portable engine path; Python CI passed.
- Added a branch-only regression check for reviewed phrase attribution against the source paragraph. Not yet verified by a successful full-book report.
- Main branch remains untouched and PR remains Draft.

## What is NOT complete

- No successful end-to-end pass over the full reference EPUB.
- No 100% whole-book occurrence ledger has been generated from a successful run.
- AOT and complete Wiktionary checks have not completed for the book.
- Third independent character model has not completed a full-book audit.
- No final book-specific import ZIP has been produced/validated.
- Windows desktop runtime is not assembled: the mockable Android API JAR discovery/packaging step is still broken.
- No finished Windows portable package/EXE, no bundled JRE, no validated native RUAccent tokenizer DLL, no verified Silero/third-model workers in the final package, and no end-to-end Windows launch test.
- No measured full-book runtime benchmark exists. Do not make runtime/speed claims.

## Resume sequence (only after user asks to continue)

1. Inspect the final result of run 45722315350. Identify the actual AGP output/task for the mockable Android JAR; do not guess the task name.
2. Finish and validate `assembleDesktopAuditRuntime`, including the Kotlin main class, test class, RUAccent bridge, JUnit, JSON, and Android API runtime requirements.
3. Fix and re-run the source-context phrase attribution regression; require a successful full EPUB test rather than weakening/omitting the check.
4. Run AOT/Wiktionary whole-book comparison and the gated independent model; inspect proposed changes contextually.
5. Generate the import ZIP only after confirming 100% token/occurrence ledger coverage and exact counts.
6. Assemble Windows portable package and perform actual Windows launch/upload/ZIP import smoke tests.
7. Measure runtime on the reference EPUB before describing performance.

## Explicit stop instruction

At the end of this checkpoint, work is stopped. No further edits or workflow runs should be initiated until the user resumes the task.
