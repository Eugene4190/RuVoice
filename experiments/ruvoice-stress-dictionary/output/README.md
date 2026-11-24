# Exported dictionaries

TXT files in this folder use the official RuVoice user stress dictionary format:
one line per entry, as: word stressed+word

- `RuVoice_Stage4.9_ExistingFixes.txt`: snapshot of the checked-in Stage 4.9 fix list. It may duplicate entries already present in an APK built from Stage 4.9.
- `RuVoice_AuditedOverrides.txt`: two manually reviewed general overrides for «Трёхгорке» and «Трёхгорку».
- `RuVoice_AutoStress.txt`: completed combined export from the full AOT + Wiktionary pipeline. It contains 4,587 unique entries: 1,924 existing Stage 4.9 fixes, 2 manually reviewed overrides, and 2,661 automatic consensus entries.

The automatic entries come from the official upstream process: Silero disagrees, while AOT and Wiktionary agree. The upstream filters for names, ё-related ambiguity, homographs and existing exceptions are applied. This is a high-confidence automatic candidate set, not a manually gold-verified dictionary. Review the provenance audit at `../reports/RuVoice_AutoStress_accepted.tsv` and the rejected/withheld rows at `../reports/RuVoice_AutoStress_review.tsv`.

To use the combined TXT, import it into a separate list in RuVoice → Dictionaries → **Stress**, enable that list, and do not import it into the replacements tab. When using the full combined export, do not also enable the Stage 4.9 snapshot or the audited override list separately; their contents are already included.

The generated TXT does not modify the APK or the built-in system dictionary. Reimporting it on an installation that already has the same entries may have no additional effect. Observation counts and dictionary-source agreement are not calibrated probabilities and do not provide a whole-book accuracy score.

Do not commit source dumps or temporary corpora here.
