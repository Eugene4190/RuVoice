package ru.kost.ruvoice.text

private fun expect(name: String, actual: String, expected: String) {
    check(actual == expected) { "$name: expected=<$expected> actual=<$actual>" }
    println("PASS $name: $actual")
}

fun main() {
    // Move an automatically inserted stress from the first syllable to the last.
    expect(
        "replace automatic stress",
        StressCorrectionMerger.merge(
            original = "замок",
            ruVoice = "з+амок",
            prediction = IndependentStressPrediction("замо\u0301к", listOf(StressDecision.STRESSED)),
        ),
        "зам+ок",
    )
    // Explicit NO_STRESS from the context classifier removes an automatic RuVoice mark.
    expect(
        "remove false stress",
        StressCorrectionMerger.merge(
            original = "все",
            ruVoice = "вс+е",
            prediction = IndependentStressPrediction("все", listOf(StressDecision.UNSTRESSED)),
        ),
        "все",
    )
    // Contextual YO can restore Ё or roll back an automatic but rejected Ё.
    expect(
        "restore yo",
        StressCorrectionMerger.merge(
            original = "все",
            ruVoice = "все",
            prediction = IndependentStressPrediction(
                "всё", listOf(StressDecision.UNKNOWN), listOf(YoDecision.RESTORE_YO)
            ),
        ),
        "всё",
    )
    expect(
        "rollback false yo",
        StressCorrectionMerger.merge(
            original = "все",
            ruVoice = "всё",
            prediction = IndependentStressPrediction(
                "все", listOf(StressDecision.UNKNOWN), listOf(YoDecision.KEEP_E)
            ),
        ),
        "все",
    )
    expect(
        "restore only predicted yo position",
        StressCorrectionMerger.merge(
            original = "ее",
            ruVoice = "ёе",
            prediction = IndependentStressPrediction(
                "её", listOf(StressDecision.UNKNOWN), listOf(YoDecision.RESTORE_YO)
            ),
        ),
        "её",
    )
    expect(
        "unknown yo keeps current decision",
        StressCorrectionMerger.merge(
            original = "все",
            ruVoice = "всё",
            prediction = IndependentStressPrediction(
                "все", listOf(StressDecision.UNKNOWN), listOf(YoDecision.UNKNOWN)
            ),
        ),
        "всё",
    )
    // Explicit source Ё and user-dictionary entries remain authoritative.
    expect(
        "preserve explicit yo",
        StressCorrectionMerger.merge(
            original = "всё",
            ruVoice = "всё",
            prediction = IndependentStressPrediction("все", listOf(StressDecision.UNKNOWN)),
        ),
        "всё",
    )
    expect(
        "protect user dictionary",
        StressCorrectionMerger.merge(
            original = "замок",
            ruVoice = "з+амок",
            prediction = IndependentStressPrediction("замо\u0301к", listOf(StressDecision.STRESSED)),
            userDictionaryKeys = setOf("замок"),
        ),
        "з+амок",
    )
    expect(
        "preserve explicit source stress",
        StressCorrectionMerger.merge(
            original = "з+амок",
            ruVoice = "з+амок",
            prediction = IndependentStressPrediction("замо\u0301к", listOf(StressDecision.STRESSED)),
        ),
        "з+амок",
    )
    expect(
        "protect hyphenated user dictionary compound",
        StressCorrectionMerger.merge(
            original = "по-моему",
            ruVoice = "по-моему",
            prediction = IndependentStressPrediction("по-мо́ему", listOf(StressDecision.UNKNOWN, StressDecision.STRESSED)),
            userDictionaryKeys = setOf("по-моему"),
        ),
        "по-моему",
    )
    expect(
        "explicit stress protects complete hyphenated compound",
        StressCorrectionMerger.merge(
            original = "по-мо+ему",
            ruVoice = "по-мо+ему",
            prediction = IndependentStressPrediction("по-мо́ему", listOf(StressDecision.UNKNOWN, StressDecision.STRESSED)),
        ),
        "по-мо+ему",
    )
    // A token spelling mismatch is skipped, while aligned following words can still be corrected.
    expect(
        "unaligned token safely skipped",
        StressCorrectionMerger.merge(
            original = "замок лес",
            ruVoice = "з+амок лес",
            prediction = IndependentStressPrediction(
                "забор ле\u0301с",
                listOf(StressDecision.STRESSED, StressDecision.STRESSED),
            ),
        ),
        "з+амок л+ес",
    )
    check(!RuAccentDecisionPolicy.canUseWordOnlyFallback(isKnownOmograph = true, hasResolvedOmograph = false))
    check(RuAccentDecisionPolicy.canUseWordOnlyFallback(isKnownOmograph = true, hasResolvedOmograph = true))
    check(RuAccentDecisionPolicy.canUseWordOnlyFallback(isKnownOmograph = false, hasResolvedOmograph = false))
    println("PASS unresolved known omograph disables context-free fallback")
    check(RuAccentDecisionPolicy.shouldUseCharAccentFallback("слово", "слово", false, 2))
    check(!RuAccentDecisionPolicy.shouldUseCharAccentFallback("сл+ово", "слово", false, 2))
    check(!RuAccentDecisionPolicy.shouldUseCharAccentFallback("о", "о", false, 1))
    check(!RuAccentDecisionPolicy.shouldUseCharAccentFallback("слово", "слово", true, 2))
    println("PASS char model fallback matches RUAccent dictionary semantics")
    check(RuAccentDecisionPolicy.resolveYoDecision("ёлка", "ёлка", "NO_YO", 0.99f, 0.65f) == YoDecision.RESTORE_YO)
    check(RuAccentDecisionPolicy.resolveYoDecision("елка", "ёлка", "YO", 0.99f, 0.65f) == YoDecision.RESTORE_YO)
    check(RuAccentDecisionPolicy.resolveYoDecision("елка", "ёлка", "NO_YO", 0.99f, 0.65f) == YoDecision.KEEP_E)
    check(RuAccentDecisionPolicy.resolveYoDecision(null, "ёлка", "YO", 0.99f, 0.65f) == YoDecision.RESTORE_YO)
    check(RuAccentDecisionPolicy.resolveYoDecision(null, "ёлка", "NO_YO", 0.99f, 0.65f) == YoDecision.KEEP_E)
    check(RuAccentDecisionPolicy.resolveYoDecision(null, null, "YO", 0.99f, 0.65f) == YoDecision.UNKNOWN)
    check(RuAccentDecisionPolicy.resolveYoDecision("елка", "ёлка", "YO", 0.50f, 0.65f) == YoDecision.KEEP_E)
    println("PASS fixed ё dictionary and contextual yo-homograph precedence")
    val fixedYo = RuAccentYoDictionaryPolicy.resolve("желтый", "жёлтый", null, "NO_YO", 0.99f, 0.65f)
    check(fixedYo.word == "жёлтый" && fixedYo.decision == YoDecision.RESTORE_YO)
    println("PASS fixed yo_words mapping survives NO_YO")
    val contextualYo = RuAccentYoDictionaryPolicy.resolve("все", null, "всё", "YO", 0.99f, 0.65f)
    check(contextualYo.word == "всё" && contextualYo.decision == YoDecision.RESTORE_YO)
    println("PASS confident yo_homographs mapping is applied")
    val contextualE = RuAccentYoDictionaryPolicy.resolve("все", null, "всё", "NO_YO", 0.99f, 0.65f)
    check(contextualE.word == "все" && contextualE.decision == YoDecision.KEEP_E)
    println("PASS NO_YO retains the e homograph")
    val uncertainYo = RuAccentYoDictionaryPolicy.resolve("все", null, "всё", "YO", 0.50f, 0.65f)
    check(uncertainYo.word == "все" && uncertainYo.decision == YoDecision.UNKNOWN)
    println("PASS low-confidence yo prediction does not rewrite")
    val noCandidate = RuAccentYoDictionaryPolicy.resolve("все", null, null, "YO", 0.99f, 0.65f)
    check(noCandidate.word == "все" && noCandidate.decision == YoDecision.UNKNOWN)
    println("PASS model cannot invent a yo form without dictionary entry")
    val upperYo = RuAccentYoDictionaryPolicy.resolve("ВСЕ", null, "всё", "YO", 0.99f, 0.65f)
    check(upperYo.word == "ВСЁ")
    val explicitYo = RuAccentYoDictionaryPolicy.resolve("Ёлка", "ёлка", "елка", "NO_YO", 0.99f, 0.65f)
    check(explicitYo.word == "Ёлка" && explicitYo.decision == YoDecision.UNKNOWN)
    println("PASS capitalization and author-written ё are preserved")
    check(RuAccentYoDictionaryPolicy.isValidEntry("желтый", "жёлтый"))
    check(!RuAccentYoDictionaryPolicy.isValidEntry("желтый", "жёлтая"))
    check(RuAccentYoDictionaryPolicy.validateDictionary("yo_words", mapOf("желтый" to "жёлтый")).size == 1)
    var invalidDictionaryRejected = false
    try { RuAccentYoDictionaryPolicy.validateDictionary("yo_words", mapOf("желтый" to 42)) }
    catch (_: IllegalArgumentException) { invalidDictionaryRejected = true }
    check(invalidDictionaryRejected)
    println("PASS ё dictionaries validate their JSON mapping schema")
    check(RuAccentInputSafety.unsafeWordsJoinedByDroppedSeparators("дом😀лес", listOf(0 until 3, 5 until 8)) == setOf(0, 1))
    check(RuAccentInputSafety.unsafeWordsJoinedByDroppedSeparators("дом—лес", listOf(0 until 3, 4 until 7)).isEmpty())
    check(RuAccentInputSafety.unsafeWordsJoinedByDroppedSeparators("дом лес", listOf(0 until 3, 4 until 7)).isEmpty())
    check(RuAccentInputSafety.unsafeWordsJoinedByDroppedSeparators("дом\u0307", listOf(0 until 3)) == setOf(0))
    check(RuAccentInputSafety.unsafeWordsJoinedByDroppedSeparators("\u0307дом", listOf(1 until 4)) == setOf(0))
    check(RuAccentInputSafety.unsafeWordsJoinedByDroppedSeparators("é\u200Dдом", listOf(2 until 5)) == setOf(0))
    check(RuAccentInputSafety.unsafeWordsJoinedByDroppedSeparators("дом\u200Dé", listOf(0 until 3)) == setOf(0))
    println("PASS dropped-character join and combining-mark edge protection")
    expect("same-length normalisation", RuAccentInputSafety.normalizeSameLength("дом😀лес"), "дом  лес")
    // Two tokens in a hyphenated compound are independently aligned.
    expect(
        "hyphen word alignment",
        StressCorrectionMerger.merge(
            original = "по-моему",
            ruVoice = "по-моему",
            prediction = IndependentStressPrediction("по-мо́ему", listOf(StressDecision.UNKNOWN, StressDecision.STRESSED)),
        ),
        "по-м+оему",
    )
}
