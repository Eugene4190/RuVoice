# Linguistic review: четырёхбедрум… conflict family

Date: 2026-11-25  
Branch: `stress-dictionary-pipeline`  
Scope: the 16 exact forms in the `четырёхбедрум…` family listed in `reports/system-dictionary-conflict-review.md`.

## Executive decision

**Do not select either stress pattern for the global/system dictionary yet. Keep all 16 exact forms withheld.** The evidence found establishes the word family as a Russian-English hybrid/colloquial emigrant formation, but does not establish a codified Russian stress norm for `четырёхбедрумный` or its inflectional forms.

The English source `bedroom` has primary stress on the first syllable (`/ˈbed.ruːm/`) in both UK and US pronunciation. This is a directional phonetic clue in favour of first-component stress in a direct borrowing. It is **not sufficient evidence** to impose that stress on a Russian hybrid adjective: language-contact research documents adaptation and competing Russian derivatives, and the exact form is not established as neutral literary vocabulary.

No production dictionary, global curated list, APK asset, or `main` file was changed.

## What the project files show

- `tools/lib_names.txt`, lines 5663–5678, contains 16 hand-curated forms in this family. Its header describes these as book-library words absent from AOT/Wiktionary and manually reviewed; the list is a project candidate source, not a published normative pronunciation authority.
- The system-dictionary audit identifies 3 exact keys with the same marker position but different `е/э` phonetic spellings, and 13 keys with a genuine stress-position split: `четырёхбедр+ум…` versus `четырёхб+эдрум…`.
- Those 16 forms remain blocked by the parser's duplicate-key conflict handling. This report does not remove that block.

## Lexicographic and linguistic evidence

### Russian usage and word-formation

1. David R. Andrews, “Пять подходов к лингвистическому анализу языка русских эмигрантов в США”, *Славяноведение*, 1997, № 2, pp. 19–20. The example discusses `bedroom` borrowed as `бедрум` and a derivative `двухбедренный`. Andrews notes that forms such as `однобедрумный` and `двухбедрумный` do occur, while derivatives in `-бедренный` are more widespread. This is evidence for an emigrant hybrid and competing derivational shapes, **not** for either stress placement in `четырёхбедрумный`.  
   Source: https://inslav.ru/sites/default/files/slav-1997-2.pdf (printed p. 20).

2. Е. А. Земская, “Язык русского зарубежья: Итоги и перспективы исследования”, *Русский язык в научном освещении*, 2001, № 1, p. 123. In a discussion of hybrid word formation in the speech of later emigration waves, Zemskaya lists `бедрумный` among adjectives formed from foreign-language bases using Russian morphology. This confirms the sociolinguistic/word-formation status; it gives no accentuation for the exact four-bedroom forms.  
   Source: https://rjano.ruslang.ru/sites/default/files/journals/2001/2001-1.pdf (printed p. 123).

### English source pronunciation

Cambridge gives UK and US `bedroom` as `/ˈbed.ruːm/`; Oxford gives `/ˈbedruːm/` and `/ˈbedrʊm/`. Both mark primary stress on the first syllable.  
Sources:
- https://dictionary.cambridge.org/pronunciation/english/bedroom
- https://www.oxfordlearnersdictionaries.com/definition/english/bedroom_1

This supports the original English stress pattern but does not determine how the Russian-language hybrid adjective is stressed after adaptation and derivation.

## Classification of the 16 exact forms

| Subgroup | Count | Conflict | Decision |
|---|---:|---|---|
| `четырёхбедрумна`, `четырёхбедрумно`, `четырёхбедрумны` | 3 | Same stress-marker position; `е/э` spelling/phonetic representation differs | Not a stress-position conflict, but the phonetic representation is unverified; withhold |
| Remaining forms (`…ная`, `…ного`, `…ное`, `…ной`, `…ном`, `…ному`, `…ною`, `…ную`, `…ные`, `…ный`, `…ным`, `…ными`, `…ных`) | 13 | Different marker positions: in the `-ум-` part vs at the beginning of the `bedroom` base | Genuine accentuation conflict; withhold |

## Recommended handling

1. Keep all 16 exact keys in conflict/review state. Do not choose a winner by model vote, source order, frequency, or by directly copying English stress.
2. Do not promote the family into `RuVoice_Accumulated_Approved.txt`, `reviewed_overrides.txt`, or global production assets.
3. If the exact word appears in a particular book and must be voiced, treat it as a **book-specific** item. Require the exact sentence, intended meaning/register, and preferably a recording or independent pronunciation judgement for that usage.
4. If the authorial meaning is simply “a home with four bedrooms” and the style permits normalization, use an established Russian equivalent such as `четырёхспальный` or `дом/квартира с четырьмя спальнями`; do not silently rewrite a deliberately marked slang word in a literary text.
5. Keep the three `е/э` cases separate from the 13 stress-position cases in all future conflict counts.

## What this review does not claim

- It does not establish a normative Russian stress for `четырёхбедрумный`.
- It does not prove that `четырёхб+эдрумный` is the speaker's actual pronunciation in the source book, even though it aligns with the English source stress.
- It does not prove that `четырёхбедр+умный` is correct merely because it appears in the curated book-library list.
- It does not clear the 16-key conflict or change any dictionary data.

**Disposition:** all 16 remain withheld pending exact-context review and an independent Russian pronunciation judgement. The audit now has a supported reason for withholding them rather than an unresolved raw duplicate alone.


## Additional direct Wiktionary evidence found (2026-11-25)

A direct Russian Wiktionary article for [`четырёхбедрумный`](https://ru.wiktionary.org/wiki/четырёхбедрумный) changes the evidence balance and should be considered alongside the academic usage studies above:

- The article's full declension table marks the family consistently as `четырёхбе́друмный`, `четырёхбе́друмная`, `четырёхбе́друмно`, etc. Its IPA gives primary stress on `бед-`: `[t͡ɕɪtɨˌrʲɵɣˈbɛdrʊmnɨɪ̯]`.
- The page history shows the form with stress on `бе́д-` already in the original entry dated 2016-07-11; the current version was last edited 2024-11-02. The stress placement is therefore not a one-day or recent edit.
- The entry explicitly labels the word `неол.`, `жарг.`; it has no usage example, no bibliography, and is flagged as needing work on pronunciation and related information. It is a direct lexicographic attestation, but not a fully sourced normative pronunciation authority.

### Revised assessment

There is now a **best-supported provisional candidate** for the exact hybrid: stress the first syllable of the borrowed base, `четырёхбе́друм-` (project notation `четырёхб+едрум-`). This agrees with the Wiktionary paradigm and with the English source `bedroom` primary stress. It does not support the competing `четырёхбедр+ум-` pattern in the 13 forms.

For the three same-position spellings, Wiktionary uses `е` (`бедрум`), not hard `э`; this is the spelling to prefer in a provisional candidate. The exact sound is transcribed with /ɛ/ in the current IPA, which is not itself a reason to respell the word with `э` in Russian.

**Disposition remains WITHHOLD from the global/approved dictionary pending a human Russian pronunciation review.** The new Wiktionary evidence is strong enough to nominate `четырёхб+едрум…` as the provisional stress pattern for a book-specific candidate, but the article's own quality flags and lack of example/audio prevent calling the norm independently verified. Do not silently export it. Obtain an independent reading of the exact book sentence or a recording before promotion.

### Provenance discrepancy

The header in `tools/lib_names.txt` describes its candidates as absent from AOT/Wiktionary. Yet a Russian Wiktionary article for the exact lemma has existed since 2016. This indicates a coverage/provenance gap in the source-scan or candidate-generation process. Do not treat the header's “not in Wiktionary” statement as proven for this lemma; record the direct article URL whenever this family is reviewed.
