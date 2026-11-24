# Book-specific reviewed stress overlay

This file contains four case-specific corrections selected after a full production
RuVoice pass over `8.Iskusstvo..epub`.

| Book form | Previous RuVoice output | Reviewed output | Reason |
|---|---|---|---|
| утрам | утра́м | у́трам | Dative plural of `утро`; normative stress remains on the root |
| несчастлив | несча́стлив | несчастли́в | Short masculine form of `несчастливый` |
| отнята | о́тнята | отнята́ | Short feminine form of `отнятый`; preferred dictionary paradigm uses final stress |
| шумы | шумы́ | шу́мы | Nominative plural of the noun `шум` in this book context |

These are an experimental, book-only supplement. They are not added to
`Системный.txt`, the APK, or the cumulative accepted dictionary. The evaluation
workflow checks every overlay entry against the existing system dictionary and
runs the full EPUB again with this overlay loaded by the production `Stress`
pipeline.
