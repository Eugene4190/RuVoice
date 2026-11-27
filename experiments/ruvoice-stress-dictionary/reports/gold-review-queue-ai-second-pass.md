# AI second-pass linguistic review of the gold candidate queue

Date: 2026-11-25  
Reviewed branch: `stress-dictionary-pipeline`  
Reviewed HEAD: `eaa03d0783bd7293030b4b2954ba554d8e3774cd`  
Input: `data/gold/review_queue.tsv` (P001–P010)

## Status and scope

This is a fresh, form-by-form AI review of the ten queued candidates. It checks exact spelling, lexical identity, part of speech, inflection, sentence meaning, stress position and the status of normative alternatives. It does not use RuVoice or RUAccent outputs, model agreement, or automatic source voting as evidence of the norm.

**This report is not an independent human linguist's annotation.** It is a separate AI assessment and a useful preparation for that review, but it cannot be represented as the external second-linguist review required by the project. For that reason this report does not fill `second_reviewer`, `second_reviewed_on`, `second_decision` or `disagreement_notes` in the queue. Every row remains `AWAITING_SECOND_LINGUIST_REVIEW`; no row is promoted into `data/gold/seed.tsv` or included in gold metrics.

## Decisions

| ID | Exact form and context class | AI second-pass decision | Linguistic reasoning |
|---|---|---|---|
| P001 | `красивее`, comparative of `красивый` | CONFIRM — `крас+ивее` | The comparative is explicitly identified as `краси́вее` in the Gramota entry. The sentence uses the adjective in a comparison; the morphological label and stress marker are correct. |
| P002 | `поняла`, past feminine singular of `понять` | CONFIRM — `понял+а` | The inflection table gives `поняла́`. The proposed context and perfective past-tense analysis match the entry. |
| P003 | `приняла`, past feminine singular of `принять` | CONFIRM — `принял+а` | The entry explicitly lists `приняла́` among the stressed forms and in the past-tense table. The context and grammatical features are appropriate. |
| P004 | `взяла`, past feminine singular of `взять` | CONFIRM — `взял+а` | The entry explicitly identifies `взяла́`; the past feminine singular analysis and sentence are correct. |
| P005 | `договор`, masculine nominative singular | CONFIRM WITH REGISTER NOTE — primary `догов+ор`; accepted `д+оговор` only as a less-preferred conversational variant | The current Gramota meta-entry gives `догово́р` in the paradigm. The service answer says `до́говор` is not erroneous but is much less desirable and permissible in colloquial speech; exemplary literary speech should use `догово́р`. Keep the variant in `accepted_marked`, but do not treat it as equal to the primary form. The singular example is natural and sufficiently neutral for the preferred form. |
| P006 | `балуется`, present 3rd person singular of `баловаться` | CONFIRM THE FORM-SPECIFIC PRIMARY — `бал+уется`; keep the form-level scope explicit | Gramota's form-specific answer №232830 explicitly gives `балУется`. A newer answer №323862 says that the less-preferred pronunciation `бАловаться` is now admitted for the infinitive by the modern Large Orthoepic Dictionary. Do not automatically transfer an infinitive variant to this exact finite form. The candidate as written is supported; the second linguist should still check whether the current dictionary's variant notation has any consequence for the full accepted set of this particular inflection. |
| P007 | `берег`, noun, masculine nominative singular, shore | CONFIRM — `б+ерег` | The Large Orthoepic Dictionary gives the nominative singular noun as `бе́рег`. This exact form is not the past-tense verb `берёг`; the context clearly selects the noun. |
| P008 | `берёг`, masculine singular past tense of `беречь` | CONFIRM — `бер+ёг` | The inflectional entry for `беречь` explicitly gives `берёг`. The letter `ё` is part of the exact spelling and marks the stressed vowel; this is not an alias of the noun `берег`. |
| P009 | `пахта`, dairy-product sense | CONFIRM — `п+ахта` | Gramota answer №329839 explicitly defines `па́хта` as defatted dairy liquid and states that it is a different word from `пахта́`. The sentence selects the dairy-product sense. |
| P010 | `пахта`, cotton sense | CONFIRM — `пахт+а` | The same Gramota answer defines `пахта́` as cotton and distinguishes it from the dairy word. The textile-factory context selects the cotton sense. This is a separate lexical item, not a variant of P009. |

## Source checks

- P001: [Gramota, `красивый`](https://gramota.ru/meta/krasivyy) — comparative `краси́вее`.
- P002: [Gramota, `понять`](https://gramota.ru/meta/ponyat) — past feminine `поняла́`.
- P003: [Gramota, `принять`](https://gramota.ru/meta/prinyat) — past feminine `приняла́`.
- P004: [Gramota, `взять`](https://gramota.ru/meta/vzyat) — past feminine `взяла́`.
- P005: [Gramota, `договор`](https://gramota.ru/meta/dogovor); [service answer №321561](https://gramota.ru/spravka/vopros/321561) — preferred `догово́р`, less-preferred colloquial `до́говор`.
- P006: [Gramota, answer search for `баловаться`](https://gramota.ru/poisk?mode=spravka&query=%D0%B1%D0%B0%D0%BB%D0%BE%D0%B2%D0%B0%D1%82%D1%8C%D1%81%D1%8F) — answer №232830 explicitly gives `балУется`; newer answer №323862 addresses the admitted variant of the infinitive.
- P007–P008: [Gramota, Large Orthoepic Dictionary (PDF)](https://gramota.ru/storage/public/normdicts/orfoepicheskij_slovar.pdf) — `БÉРЕГ`; `БЕРÉЧЬ ... берёг`; also [Gramota, `беречь`](https://gramota.ru/meta/berech).
- P009–P010: [Gramota, answer №329839](https://gramota.ru/spravka/vopros/329839) — `па́хта` ‘defatted dairy liquid’ and `пахта́` ‘cotton’ are different words.

## Summary for the external second linguist

The proposed stress positions and contexts are supported for all ten rows in this AI pass. No direct disagreement was found for P001–P004 or P007–P010. P005 needs the normative label to preserve the distinction between preferred and colloquial use. P006 is correct for the specifically cited 3rd-person form, but its `accepted_marked` field should be checked against the modern dictionary's treatment of the infinitive variant rather than inferred from the infinitive.

Recommended action for the human second linguist: independently annotate all ten rows from the cited lexicographic sources (and any newer edition they consider authoritative), explicitly decide P005's register note and P006's accepted-form set, then record reviewer identity/date/decision and resolve any disagreement. Only the adjudicated results may be moved into the gold seed. Until then the queue and seed remain unchanged.


## Follow-up source recheck for P005 and P006 (2026-11-25)

A follow-up query of current Gramota references adds precision to the two entries that were flagged for register/paradigm care:

- **P005 (`договор`)**: Gramota's current Meta-dictionary entry gives the paradigm with preferred `догово́р`; reference answer №321561 explicitly says `до́говор` has been marked permissible in colloquial speech for decades, while the preferred form remains `догово́р` for exemplary literary speech. Keep `догов+ор` as `primary_marked` and `д+оговор` as accepted but less desirable/register-marked. Sources: https://gramota.ru/meta/dogovor and https://gramota.ru/spravka/vopros/321561.
- **P006 (`балуется`)**: reference answer №232830 directly gives `балУется`; answer №271909 also confirms `он балУется`. A separate, newer answer №323862 says the infinitive variant `бАловаться` is now allowed by the modern Large Orthoepic Dictionary. These claims concern different morphological forms. The newer infinitive variant does not, by itself, refute the form-specific `балУется` decision for 3sg present. The current Large Orthoepic Dictionary also lists both accentual infinitive types (`БÁЛОВАТЬСЯ` / `БАЛОВÁТЬСЯ`) but the exact finite form remains supported as `балУется` by the form-specific Gramota answers. Sources: https://gramota.ru/poisk?mode=spravka&query=%D0%B1%D0%B0%D0%BB%D0%BE%D0%B2%D0%B0%D1%82%D1%8C%D1%81%D1%8F and https://gramota.ru/storage/public/normdicts/orfoepicheskij_slovar.pdf.

No queue row is promoted: all P001–P010 remain awaiting an external second human linguist. This follow-up narrows the notes but does not replace that required review.
