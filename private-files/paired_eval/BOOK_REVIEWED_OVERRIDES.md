# Book-specific reviewed stress overlay

This file contains twenty book-specific corrections selected after a full production
RuVoice pass over `8.Iskusstvo..epub`.

| Book form | Previous RuVoice output | Reviewed output | Reason |
|---|---|---|---|
| несчастлив | несча́стлив | несчастли́в | Short masculine form of `несчастливый` |
| отнята | о́тнята | отнята́ | Short feminine form of `отнятый`; preferred dictionary paradigm uses final stress |
| шумы | шумы́ | шу́мы | Nominative plural of the noun `шум` in this book context |
| двадцать | unmarked in two number-expanded passages | два́дцать | Numeral form; both independent sources give first-syllable stress |
| десять | деся́ть | де́сять | Number expansion of 10 in the range 10–20; AOT and Wiktionary agree on first-syllable stress |
| издревле (`издр+евле`) | и́здревле | издре́вле | Two occurrences; normatively only издре́вле (the initial-stress variant is explicitly marked nonrecommended in modern dictionaries) |
| утолщилась (`утолщ+илась`) | уто́лщилась | утолщи́лась | Two occurrences; the paradigm of `утолщи́ться` and RUAccent agree on the vowel и |

The existing `утра́м` in the phrase `по утра́м` is deliberately left unchanged: this is a normative adverbial variant, distinct from isolated dative `у́трам`.


The standard is also confirmed by [Викисловарь](https://ru.wiktionary.org/wiki/издревле) and [Словарь трудностей русского языка (Эскова)](https://mgmtmo.ru/edumat/OD/rus/Eskova_dictionary_difficulties.pdf): initial-stress `и́здревле` is labelled non-recommended/incorrect.

These are an experimental, book-only supplement. They are not added to
`Системный.txt`, the APK, or the cumulative accepted dictionary. The evaluation
workflow checks every overlay entry against the existing system dictionary and
runs the full EPUB again with this overlay loaded by the production `Stress`
pipeline.


A separate phrase-level correction is applied through the production homograph phrase table, not the word dictionary:

| Phrase | Previous output | Reviewed output | Reason |
|---|---|---|---|
| Сети значений | Сети́ значений | Се́ти значений | Nominative plural in this phrase; the prepositional form сети́ remains valid elsewhere |

The whole-book runner keeps an untouched Silero phrase table for the baseline pass, then compares it with the reviewed phrase table and the twenty-word overlay. The comparison therefore isolates the effect of these RuVoice-specific changes from the independent RUAccent pass.



The form `маше` is intentionally not a word-level overlay entry: the production system replacement `папье-маше = папье-маш+е` already supplies the correct stress in the book context. The redundant per-word override was replaced by `средами`.

## Ten additional corrections from the full-book disagreement review

| Book form | Previous output | Reviewed output | Evidence |
|---|---|---|---|
| арбайт | арба́йт | а́рбайт | German *Arbeit* has first-syllable stress; the book quotes “Arbeit macht frei” |
| средами | среда́ми | сре́дами | Instrumental plural of `среда` in the sense of substance/environment; the normative stress is on the root vowel е |
| сапинс | сапи́нс | са́пинс | The phrase is *Homo sapiens*; Russian Wiktionary marks `са́пиенс` |
| взаимовымогательства | взаимовымо́гательства | взаимовымога́тельства | Compound based on `вымога́тельство` |
| взаимовымогающим | взаимовымо́гающим | взаимовымога́ющим | Compound participle based on `вымога́ющий` / `вымога́ть` |
| внутриличностных | внутрилично́стных | внутрили́чностных | Compound with `ли́чностный` |
| неприспособление | неприспосо́бление | неприспособле́ние | `не-` + `приспособле́ние` |
| нетелесного | нете́лесного | нетеле́сного | `не-` + `теле́сного` |
| религиообразовании | религиообразо́вании | религиообразова́нии | Compound with `образова́ние` |
| самосуществования | самосущество́вания | самосуществова́ния | Compound with `существова́ние` |

Reference lexemes: [гомо сапиенс](https://ru.wiktionary.org/wiki/гомо_сапиенс), [вымогательство](https://ru.wiktionary.org/wiki/вымогательство), [вымогать](https://ru.wiktionary.org/wiki/вымогать), [личностный](https://ru.wiktionary.org/wiki/личностный), [приспособление](https://ru.wiktionary.org/wiki/приспособление), [телесный](https://ru.wiktionary.org/wiki/телесный), [образование](https://ru.wiktionary.org/wiki/образование), [существование](https://ru.wiktionary.org/wiki/существование), [среда (Грамота)](https://gramota.ru/meta/sreda), and [German Arbeit](https://www.duden.de/rechtschreibung/Arbeit).

The remaining author-specific neologisms and disputed proper-name pronunciations are not auto-corrected; the RUAccent difference alone is not evidence.


## Three further context-checked corrections from the full-book review

| Book form | Previous output | Reviewed output | Reason |
|---|---|---|---|
| биополя | биопо́ля | биополя́ | In the sentence “поля («биополя», как его не слишком правильно называют…)” this is nominative plural, not genitive singular. The plural form selects final stress; Wiktionary records both morphological stress positions, so context decides. |
| призывного | призывно́го | призы́вного | “Призывного очарования” means beckoning/attractive, from adjective призы́вный; it is not the military adjective призывно́й. |
| челюстей | челюсте́й | че́люстей | Genitive plural of че́люсть; standard stress remains on the first syllable in this form. |

Additional book-only text normalizations are kept in the phrase replacement list rather than the stress dictionary:
- дальнейшиекаскады → дальнейшие каскады
- совершитьлогический → совершить логический

The form `челюстей` is deliberately not overridden: the reference paradigm records both `че́люстей` and `челюсте́й`, so the existing RuVoice pronunciation is retained.

These decisions are scoped to the exact reference EPUB and are not added to the global system dictionary or personal cumulative master.


## Three further context-checked corrections from the full-book audit

| Book form | Previous output | Reviewed output | Reason |
|---|---|---|---|
| биополя | биопо́ля | биополя́ | Nominative plural in the exact sentence; the word's paradigm has `биополя́` for nominative plural and genitive singular `биопо́ля`. |
| призывного | призывно́го | призы́вного | The phrase “призывного очарования” means attractive/calling, from `призы́вный`, not military `призывно́й`. |
| челюстей | челюсте́й | че́люстей | Genitive plural of `че́люсть`; the accepted literary stress remains on the first syllable. |
| рефлекторное | рефлекто́рное | рефле́кторное | In “рефлекторное отторжение” the intended meaning is reflex/involuntary, not a device made with a reflector. Gramota distinguishes `рефле́кторный` (from рефлекс) from `рефлекто́рный` (from рефлектор). |


The form `челюстей` is deliberately NOT overridden: the reference paradigm records both `че́люстей` and `челюсте́й`, so the existing RuVoice pronunciation is retained.
