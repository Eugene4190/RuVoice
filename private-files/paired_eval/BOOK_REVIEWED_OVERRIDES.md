# Book-specific reviewed stress overlay

This file contains five case-specific corrections selected after a full production
RuVoice pass over `8.Iskusstvo..epub`.

| Book form | Previous RuVoice output | Reviewed output | Reason |
|---|---|---|---|
| утрам | утра́м | у́трам | Dative plural of `утро`; normative stress remains on the root |
| несчастлив | несча́стлив | несчастли́в | Short masculine form of `несчастливый` |
| отнята | о́тнята | отнята́ | Short feminine form of `отнятый`; preferred dictionary paradigm uses final stress |
| шумы | шумы́ | шу́мы | Nominative plural of the noun `шум` in this book context |
| двадцать | unmarked in two number-expanded passages | два́дцать | Numeral form; both independent sources give first-syllable stress |

These are an experimental, book-only supplement. They are not added to
`Системный.txt`, the APK, or the cumulative accepted dictionary. The evaluation
workflow checks every overlay entry against the existing system dictionary and
runs the full EPUB again with this overlay loaded by the production `Stress`
pipeline.


A separate phrase-level correction is applied through the production homograph phrase table, not the word dictionary:

| Phrase | Previous output | Reviewed output | Reason |
|---|---|---|---|
| Сети значений | Сети́ значений | Се́ти значений | Nominative plural in this phrase; the prepositional form сети́ remains valid elsewhere |

The whole-book runner keeps an untouched Silero phrase table for the baseline pass, then compares it with the reviewed phrase table and the five-word overlay. The comparison therefore isolates the effect of these RuVoice-specific changes from the independent RUAccent pass.
