# Exported dictionaries

TXT files in this folder use the official RuVoice user stress dictionary format:
one line per entry, as: word stressed+word

- `RuVoice_Stage4.9_ExistingFixes.txt`: snapshot of the checked-in Stage 4.9 fix list. It may duplicate entries already present in an APK built from Stage 4.9.
- `RuVoice_AuditedOverrides.txt`: two manually reviewed general overrides for «Трёхгорке» and «Трёхгорку».
- `RuVoice_AutoStress.txt`: **experimental global source pool, not approved for import**. It contains 4,587 unique entries: 1,924 Stage 4.9 snapshot rows, 2 curated overrides and 2,661 automatic consensus candidates. The book-first builder filters this pool against the actual words in each supplied book and the full built-in dictionary.

The automatic entries come from the official upstream process: Silero disagrees, while AOT and Wiktionary agree. The upstream filters for names, ё-related ambiguity, homographs and existing exceptions are applied. This is a high-confidence automatic candidate set, not a manually gold-verified dictionary. Review the provenance audit at `../reports/RuVoice_AutoStress_accepted.tsv` and the rejected/withheld rows at `../reports/RuVoice_AutoStress_review.tsv`.

Do **not** import `RuVoice_AutoStress.txt` as a whole. For each book, use `build_book_dictionary.py`. Only `Book_Approved_Additions.txt` (or the cumulative `RuVoice_Accumulated_Approved.txt`) contains approved rows intended for import into a separate RuVoice → Dictionaries → **Stress** list.

The new 2,661 automatic entries were compared with the full built-in Stage 4.9 stress dictionary: nine already exist with the same stress, 2,652 are absent, and no different-stress collisions were found (including е/ё-normalized keys). See `../reports/RuVoice_AutoStress_system-conflict-audit.md`.

The earlier book scan found five additional automatic forms in «Искусство» (seven occurrences) compared with the Stage 4.9 snapshot; this was a diagnostic comparison, not yet a book-specific approved export. The new book-first builder now performs this intersection directly against the full built-in dictionary and the approved cumulative list.

No generated file modifies the APK or the built-in system dictionary. Observation counts and dictionary-source agreement are not calibrated probabilities and do not provide a whole-book accuracy score. Book candidates must be checked before approval.

Do not commit source dumps or temporary corpora here.
