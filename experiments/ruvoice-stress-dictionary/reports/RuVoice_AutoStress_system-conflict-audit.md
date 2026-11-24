# Conflict audit: RuVoice_AutoStress vs built-in Stage 4.9 dictionary

Date: 2026-11-24  
Generated dictionary: `output/RuVoice_AutoStress.txt` (4,587 rows)  
Built-in source: `project/ruvoice-1.1.3-stage4.9/app/src/main/assets/dicts/stress/Системный.txt`

## Automatic additions vs built-in dictionary

The 2,661 entries classified as `aot_wiktionary_silero_consensus` in `RuVoice_AutoStress_accepted.tsv` were compared with the built-in system stress dictionary after applying the same strict row validation used by the book scanner.

| Comparison | Count |
|---|---:|
| New automatic entries | 2,661 |
| Already present with exactly the same stress | 9 |
| Not present in built-in system dictionary | 2,652 |
| Existing exact-key entries with different stress | 0 |
| Conflicts after e/ё key and stress normalization | 0 |

Therefore none of the new automatic entries would override an existing built-in entry with a different stress, based on the inspected Stage 4.9 asset.

## Existing conflicts in the built-in asset

The strict parser detects two valid conflicting keys already present in `Системный.txt`:

- `трёхгорке`: `тр+ёхгорке` vs `трёхг+орке`
- `трёхгорку`: `тр+ёхгорку` vs `трёхг+орку`

The combined user export contains the two manually reviewed curated overrides:
- `трёхгорке трёхг+орке`
- `трёхгорку трёхг+орку`

These overrides take effect only if the user imports/enables the exported list. The built-in `Системный.txt` was not edited.

A raw duplicate-key scan also found 16 malformed alternate rows for `четырёхбедрум...` forms where the alternate marked spelling uses `э` while the key uses `е`. The strict parser rejects those malformed rows, so they are not counted as valid dictionary conflicts and were not silently repaired.

## Interpretation

This is a dictionary-overlap and conflict check, not a stress-accuracy benchmark. The automatic candidates use the official upstream selection rule (Silero differs while AOT and Wiktionary agree), with the upstream exclusions applied. They are not manually gold-verified.
