# RuVoice — intermediate checkpoint (stop point)

Date: 2026-11-26  
Branch: `stress-dictionary-pipeline`  
Code snapshot at this checkpoint: `5a687e4f4f9af36734701ca8012d5c894c497314`  
Pull request: [#1](https://github.com/Eugene4190/RuVoice/pull/1) — open, Draft, not merged  
`main`: `e0f89575d872461282f719f3a04709d5436f4b45` (unchanged)

This note records the current state at the user's explicit request to stop. It is not a completion claim.

## Work now present on the branch

- The whole-book Kotlin audit now calls the original RuVoice `Pipeline.plan` for EPUB segmentation instead of relying on its own sentence splitter.
- It has fail-closed checks for segment/token alignment and full occurrence counts across the baseline, reviewed and merged streams.
- The baseline audit was separated from book-specific changes: `снято` was removed from the global system dictionary and kept in the book-only overlay.
- Workflow checks pin important v1.1.3 RuVoice assets to the upstream hashes and fetch the official `eyo_safe.txt` by its source-tree path.
- The occurrence audit now retains non-Russian/special tokens as well as Russian wordforms, and is intended to fail unless every production token has exactly one ledger row.
- The quality audit can export `Book_Importable_Stress_Overrides.txt`, with manual and automatically confirmed book-only entries kept separate in the report.
- A second full RuVoice pass was wired to accept only the conservative three-model confirmed override file. OOV consensus remains a separate review artifact.

## What CI verified at code snapshot 5a687e4

- Python stress-dictionary tools: **passed** — [run 45706113752](https://github.com/Eugene4190/RuVoice/actions/runs/45706113752).
- Windows portable EXE build plus synthetic EPUB upload → processing → ZIP download smoke test: **passed** — [run 45706113799](https://github.com/Eugene4190/RuVoice/actions/runs/45706113799).
- Kotlin stress-merge JVM tests: **passed** — [run 45706113892](https://github.com/Eugene4190/RuVoice/actions/runs/45706113892).
- Android APK build: still **in progress** at the last status check — [run 45706113740](https://github.com/Eugene4190/RuVoice/actions/runs/45706113740).
- Full uploaded-EPUB paired evaluation: **failed before processing the book**, while compiling the Kotlin test source — [run 45706103593](https://github.com/Eugene4190/RuVoice/actions/runs/45706103593).

## Exact blocker

The paired-evaluation compile error was:

```
UploadedEpubPairedEvaluation.kt:677:19
Unresolved reference 'pairedSha256'
```

The helper had been renamed to `pairedGitBlobSha`, but one call site still refers to the old helper name. The real whole-book baseline/overlay/third-model/final pass therefore has **not** completed on this snapshot. No final book dictionary artifact has been validated.

## Product status — not finished

The Windows EXE smoke test proves the local upload and ZIP packaging path works with a synthetic EPUB. It does **not** prove that the current Windows UI runs the complete full-book multi-model audit or emits the final high-confidence word list. The user's desired one-click workflow — upload a real book, receive a complete and dependable book-specific RuVoice import dictionary — is still unfinished.

No claim is made that every word can be guaranteed correct by automatic model consensus. Words with contextual ambiguity or insufficient independent evidence must remain explicitly unresolved rather than be guessed.

## Resume point (do not execute until the user asks)

1. Fix the stale `pairedSha256` call and rerun the full paired EPUB workflow.
2. Inspect the actual per-occurrence, dictionary-reference and third-model artifacts; verify the second full RuVoice pass and its before/after ledger.
3. Connect the validated final book-only dictionary/replacements to the Windows local tool, preserving append-only personal accumulation and duplicate protection.
4. Run the Windows real-EPUB end-to-end test and package a portable release.
5. Keep `main` untouched and PR #1 Draft until all of the above pass.

At the user's request, work stops at this checkpoint. Do not make further commits, start new workflows, merge the PR, or resume implementation without a new instruction.
