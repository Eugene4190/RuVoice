# Blind human linguist review packet

Date: 2026-11-25  
Branch: `stress-dictionary-pipeline`

## Purpose and independence

This packet is for an **independent human pronunciation review**. It intentionally omits the current proposed stress labels, accepted variants and AI second-pass decisions. It also contains no RuVoice or RUAccent predictions.

For each item, annotate the exact displayed surface form in the supplied sentence and grammatical/sense context. Do not infer a form's stress only from a related infinitive or another homograph. Where a current normative variant depends on register or dictionary edition, state that distinction explicitly.

Use the response template `data/gold/second_linguist_response_template.tsv`. A decision should be backed by a named lexicographic source (edition, entry and URL/page) or a recording/independent pronunciation judgement. If uncertain, record `UNCERTAIN`; do not guess.

## Part A — gold-set candidates P001–P010

| ID | Exact surface | Lemma | Part of speech / morphology | Sense | Context sentence |
|---|---|---|---|---|---|
| P001 | красивее | красивый | adjective, comparative, invariable | appearance | Этот вариант красивее предыдущего. |
| P002 | поняла | понять | perfective verb, past, feminine, singular | understanding | Она поняла инструкцию после объяснения. |
| P003 | приняла | принять | perfective verb, past, feminine, singular | decision | Комиссия приняла решение единогласно. |
| P004 | взяла | взять | perfective verb, past, feminine, singular | taking | Она взяла книгу со стола. |
| P005 | договор | договор | noun, masculine, nominative, singular | agreement | Договор вступил в силу после подписания. |
| P006 | балуется | баловаться | imperfective verb, present, 3rd person, singular | playful behavior | Ребёнок балуется во время урока. |
| P007 | берег | берег | noun, masculine, nominative, singular | river/lake shore | Берег реки был пуст после ночного шторма. |
| P008 | берёг | беречь | perfective verb, past, masculine, singular | preserved/kept | Он берёг старые письма, которые достались ему от отца. |
| P009 | пахта | пахта | noun, feminine, nominative, singular | dairy by-product | После сбивания масла на производстве осталась пахта. |
| P010 | пахта | пахта | noun, feminine, nominative, singular | raw cotton (cotton fibre) | Пахта поступила на текстильную фабрику для переработки. |

### Questions for each P-item

1. Place the primary-stress marker immediately before the stressed vowel in the exact form (project notation, e.g. `сл+ово`).
2. List any additional forms that are genuinely accepted in the stated context; distinguish equal variants from less-preferred or register-limited forms.
3. State whether the sentence selects a lexical homograph or a morphological form whose stress differs from a related form.
4. Cite the dictionary/edition and the exact entry or page. For contested cases, state the dictionary edition/date and register.
5. Record `UNCERTAIN` if the evidence is insufficient.

## Part B — separate pronunciation review for the hybrid family

These 16 exact forms are **not part of the gold seed**. They are currently blocked from all approved/global dictionary exports. The review is to establish whether the author's intended hybrid/jargon word has a defensible pronunciation in its real usage context, not to make a general rule for all Russian compounds.

| ID | Exact surface | Morphological note |
|---|---|---|
| RWT001 | четырёхбедрумна | short adjective, feminine singular |
| RWT002 | четырёхбедрумная | adjective, feminine nominative singular |
| RWT003 | четырёхбедрумно | short adjective, neuter singular |
| RWT004 | четырёхбедрумного | adjective, masculine/neuter genitive singular |
| RWT005 | четырёхбедрумное | adjective, neuter nominative/accusative singular |
| RWT006 | четырёхбедрумной | adjective, feminine genitive/dative/prepositional singular |
| RWT007 | четырёхбедрумном | adjective, masculine/neuter prepositional singular |
| RWT008 | четырёхбедрумному | adjective, masculine/neuter dative singular |
| RWT009 | четырёхбедрумною | adjective, feminine instrumental singular, variant ending |
| RWT010 | четырёхбедрумную | adjective, feminine accusative singular |
| RWT011 | четырёхбедрумны | short adjective, plural |
| RWT012 | четырёхбедрумные | adjective, plural nominative/accusative |
| RWT013 | четырёхбедрумный | adjective, masculine nominative singular |
| RWT014 | четырёхбедрумным | adjective, masculine/neuter instrumental singular; also plural dative |
| RWT015 | четырёхбедрумными | adjective, plural instrumental |
| RWT016 | четырёхбедрумных | adjective, plural genitive/prepositional; also animate accusative |

**Required before a positive decision:** obtain the original sentence(s) from the source book, identify the author's intended meaning/register, and preferably obtain a reading/recording from a competent Russian speaker. Assess the exact e/ё spelling and vowel quality separately from stress placement. A reading of the isolated word list alone is not sufficient evidence of the author's intended pronunciation.

Record for each RWT item: heard/selected stress, any alternative, vowel quality (if relevant), exact sentence and source location, whether the decision generalizes across the paradigm, recording/source reference, date and reviewer code. Keep the item withheld if no context/recording or sufficiently strong independent lexicographic source is available.

## Independence declaration

The reviewer should complete the packet without looking at the first-pass labels, AI second-pass report, model predictions or candidate TSV's provisional marked forms. After the blind response is returned, compare decisions and document disagreements. Only then may a candidate be considered for adjudication; no row is promoted automatically by majority vote.
