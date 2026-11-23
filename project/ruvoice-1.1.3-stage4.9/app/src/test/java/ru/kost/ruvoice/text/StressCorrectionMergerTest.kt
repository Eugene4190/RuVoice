package ru.kost.ruvoice.text

import org.junit.Assert.assertEquals
import org.junit.Test

class StressCorrectionMergerTest {
    @Test fun `independent stress may replace an automatic RuVoice stress`() {
        val result = StressCorrectionMerger.merge(
            original = "замок",
            ruVoice = "з+амок",
            prediction = IndependentStressPrediction("замо\u0301к", listOf(StressDecision.STRESSED)),
        )
        assertEquals("зам+ок", result)
    }

    @Test fun `NO_STRESS removes a wrong automatic stress`() {
        val result = StressCorrectionMerger.merge(
            original = "все",
            ruVoice = "вс+е",
            prediction = IndependentStressPrediction("все", listOf(StressDecision.UNSTRESSED)),
        )
        assertEquals("все", result)
    }

    @Test fun `contextual model restores yo`() {
        val result = StressCorrectionMerger.merge(
            original = "все",
            ruVoice = "все",
            prediction = IndependentStressPrediction(
                "всё", listOf(StressDecision.UNKNOWN), listOf(YoDecision.RESTORE_YO)
            ),
        )
        assertEquals("всё", result)
    }

    @Test fun `contextual model can roll back false yo`() {
        val result = StressCorrectionMerger.merge(
            original = "все",
            ruVoice = "всё",
            prediction = IndependentStressPrediction(
                "все", listOf(StressDecision.UNKNOWN), listOf(YoDecision.KEEP_E)
            ),
        )
        assertEquals("все", result)
    }

    @Test fun `restore yo changes only positions returned by the model`() {
        val result = StressCorrectionMerger.merge(
            original = "ее",
            ruVoice = "ёе",
            prediction = IndependentStressPrediction(
                "её", listOf(StressDecision.UNKNOWN), listOf(YoDecision.RESTORE_YO)
            ),
        )
        assertEquals("её", result)
    }

    @Test fun `unknown yo decision preserves RuVoice automatic yo`() {
        val result = StressCorrectionMerger.merge(
            original = "все",
            ruVoice = "всё",
            prediction = IndependentStressPrediction(
                "все", listOf(StressDecision.UNKNOWN), listOf(YoDecision.UNKNOWN)
            ),
        )
        assertEquals("всё", result)
    }

    @Test fun `explicit source yo remains untouched`() {
        val result = StressCorrectionMerger.merge(
            original = "всё",
            ruVoice = "всё",
            prediction = IndependentStressPrediction("все", listOf(StressDecision.UNKNOWN)),
        )
        assertEquals("всё", result)
    }

    @Test fun `user dictionary words are protected`() {
        val result = StressCorrectionMerger.merge(
            original = "замок",
            ruVoice = "з+амок",
            prediction = IndependentStressPrediction("замо\u0301к", listOf(StressDecision.STRESSED)),
            userDictionaryKeys = setOf("замок"),
        )
        assertEquals("з+амок", result)
    }

    @Test fun `hyphenated user dictionary entry protects every component`() {
        val result = StressCorrectionMerger.merge(
            original = "по-моему",
            ruVoice = "по-моему",
            prediction = IndependentStressPrediction(
                "по-мо\u0301ему",
                listOf(StressDecision.UNKNOWN, StressDecision.STRESSED),
            ),
            userDictionaryKeys = setOf("по-моему"),
        )
        assertEquals("по-моему", result)
    }

    @Test fun `explicit stress on one hyphen component protects the compound`() {
        val result = StressCorrectionMerger.merge(
            original = "по-мо+ему",
            ruVoice = "по-мо+ему",
            prediction = IndependentStressPrediction(
                "по-мо\u0301ему",
                listOf(StressDecision.UNKNOWN, StressDecision.STRESSED),
            ),
        )
        assertEquals("по-мо+ему", result)
    }

    @Test fun `explicit input stress is protected`() {
        val result = StressCorrectionMerger.merge(
            original = "з+амок",
            ruVoice = "з+амок",
            prediction = IndependentStressPrediction("замо\u0301к", listOf(StressDecision.STRESSED)),
        )
        assertEquals("з+амок", result)
    }

    @Test fun `hyphenated word components remain aligned`() {
        val result = StressCorrectionMerger.merge(
            original = "по-моему",
            ruVoice = "по-моему",
            prediction = IndependentStressPrediction(
                "по-мо\u0301ему",
                listOf(StressDecision.UNKNOWN, StressDecision.STRESSED),
            ),
        )
        assertEquals("по-м+оему", result)
    }

    @Test fun `unaligned model token cannot rewrite another word`() {
        val result = StressCorrectionMerger.merge(
            original = "замок лес",
            ruVoice = "з+амок лес",
            prediction = IndependentStressPrediction(
                "забор ле́с",
                listOf(StressDecision.STRESSED, StressDecision.STRESSED),
            ),
        )
        assertEquals("з+амок л+ес", result)
    }

    @Test fun `service stress markers are stripped before independent inference`() {
        assertEquals("замок", StressInputSanitizer.stripMarkers("зам+ок"))
        assertEquals("всё", StressInputSanitizer.stripMarkers("всё"))
        assertEquals("C+а", StressInputSanitizer.stripMarkers("C+а"))
    }
    @Test fun `unresolved known omograph cannot use word-only fallback`() {
        assertEquals(false, RuAccentDecisionPolicy.canUseWordOnlyFallback(true, false))
        assertEquals(true, RuAccentDecisionPolicy.canUseWordOnlyFallback(true, true))
        assertEquals(true, RuAccentDecisionPolicy.canUseWordOnlyFallback(false, false))
    }


    @Test fun `dictionary identity entry still allows the upstream char accent fallback`() {
        assertEquals(true, RuAccentDecisionPolicy.shouldUseCharAccentFallback("слово", "слово", false, 2))
        assertEquals(false, RuAccentDecisionPolicy.shouldUseCharAccentFallback("сл+ово", "слово", false, 2))
        assertEquals(false, RuAccentDecisionPolicy.shouldUseCharAccentFallback("о", "о", false, 1))
        assertEquals(false, RuAccentDecisionPolicy.shouldUseCharAccentFallback("слово", "слово", true, 2))
    }

    @Test fun `fixed yo dictionary wins over NO_YO model output`() {
        assertEquals(
            YoDecision.RESTORE_YO,
            RuAccentDecisionPolicy.resolveYoDecision("ёлка", "ёлка", "NO_YO", 0.99f, 0.65f),
        )
    }

    @Test fun `confident yo homograph may override fixed e dictionary`() {
        assertEquals(
            YoDecision.RESTORE_YO,
            RuAccentDecisionPolicy.resolveYoDecision("елка", "ёлка", "YO", 0.99f, 0.65f),
        )
        assertEquals(
            YoDecision.KEEP_E,
            RuAccentDecisionPolicy.resolveYoDecision("елка", "ёлка", "NO_YO", 0.99f, 0.65f),
        )
    }

    @Test fun `yo_words fixed mapping survives a confident NO_YO prediction`() {
        val result = RuAccentYoDictionaryPolicy.resolve(
            sourceWord = "желтый", fixedWord = "жёлтый", homographWord = null,
            modelLabel = "NO_YO", modelConfidence = 0.99f, confidenceThreshold = 0.65f,
        )
        assertEquals("жёлтый", result.word)
        assertEquals(YoDecision.RESTORE_YO, result.decision)
    }

    @Test fun `confident YO homograph overrides the fixed yo candidate`() {
        val result = RuAccentYoDictionaryPolicy.resolve(
            sourceWord = "все", fixedWord = "всё", homographWord = "всё",
            modelLabel = "YO", modelConfidence = 0.99f, confidenceThreshold = 0.65f,
        )
        assertEquals("всё", result.word)
        assertEquals(YoDecision.RESTORE_YO, result.decision)
    }

    @Test fun `confident NO_YO keeps the e homograph alternative`() {
        val result = RuAccentYoDictionaryPolicy.resolve(
            sourceWord = "все", fixedWord = null, homographWord = "всё",
            modelLabel = "NO_YO", modelConfidence = 0.99f, confidenceThreshold = 0.65f,
        )
        assertEquals("все", result.word)
        assertEquals(YoDecision.KEEP_E, result.decision)
    }

    @Test fun `low confidence homograph prediction does not override fixed mapping`() {
        val result = RuAccentYoDictionaryPolicy.resolve(
            sourceWord = "все", fixedWord = null, homographWord = "всё",
            modelLabel = "YO", modelConfidence = 0.50f, confidenceThreshold = 0.65f,
        )
        assertEquals("все", result.word)
        assertEquals(YoDecision.UNKNOWN, result.decision)
    }

    @Test fun `model cannot invent yo without a dictionary candidate`() {
        val result = RuAccentYoDictionaryPolicy.resolve(
            sourceWord = "все", fixedWord = null, homographWord = null,
            modelLabel = "YO", modelConfidence = 0.99f, confidenceThreshold = 0.65f,
        )
        assertEquals("все", result.word)
        assertEquals(YoDecision.UNKNOWN, result.decision)
    }

    @Test fun `yo dictionary policy preserves uppercase and explicit author yo`() {
        val uppercase = RuAccentYoDictionaryPolicy.resolve(
            sourceWord = "ВСЕ", fixedWord = null, homographWord = "всё",
            modelLabel = "YO", modelConfidence = 0.99f, confidenceThreshold = 0.65f,
        )
        assertEquals("ВСЁ", uppercase.word)
        val explicit = RuAccentYoDictionaryPolicy.resolve(
            sourceWord = "Ёлка", fixedWord = "ёлка", homographWord = "елка",
            modelLabel = "NO_YO", modelConfidence = 0.99f, confidenceThreshold = 0.65f,
        )
        assertEquals("Ёлка", explicit.word)
        assertEquals(YoDecision.UNKNOWN, explicit.decision)
    }

    @Test fun `yo dictionaries accept only same-word e yo mappings`() {
        assertEquals(true, RuAccentYoDictionaryPolicy.isValidEntry("желтый", "жёлтый"))
        assertEquals(true, RuAccentYoDictionaryPolicy.isValidEntry("все", "всё"))
        assertEquals(false, RuAccentYoDictionaryPolicy.isValidEntry("желтый", "жёлтая"))
        assertEquals(false, RuAccentYoDictionaryPolicy.isValidEntry("все", "всегда"))
        assertEquals(false, RuAccentYoDictionaryPolicy.isValidEntry("", "ё"))
        val dictionary = RuAccentYoDictionaryPolicy.validateDictionary(
            "yo_words", mapOf("желтый" to "жёлтый", "береза" to "берёза")
        )
        assertEquals(2, dictionary.size)
        try {
            RuAccentYoDictionaryPolicy.validateDictionary("yo_words", mapOf("желтый" to 42))
            throw AssertionError("Non-string dictionary value should be rejected")
        } catch (expected: IllegalArgumentException) {
            // expected
        }
    }

    @Test fun `unsupported combining mark at a word edge keeps word untouched`() {
        assertEquals(setOf(0), RuAccentInputSafety.unsafeWordsJoinedByDroppedSeparators("дом\u0307", listOf(0 until 3)))
        assertEquals(setOf(0), RuAccentInputSafety.unsafeWordsJoinedByDroppedSeparators("\u0307дом", listOf(1 until 4)))
        assertEquals(setOf(0), RuAccentInputSafety.unsafeWordsJoinedByDroppedSeparators("é\u200Dдом", listOf(2 until 5)))
        assertEquals(setOf(0), RuAccentInputSafety.unsafeWordsJoinedByDroppedSeparators("дом\u200Dé", listOf(0 until 3)))
    }

    @Test fun `dropped visible separator prevents joined fragments from being rewritten`() {
        val emojiRanges = listOf(0 until 3, 5 until 8)
        val punctuationRanges = listOf(0 until 3, 4 until 7)
        val spacedRanges = listOf(0 until 3, 4 until 7)
        assertEquals(setOf(0, 1), RuAccentInputSafety.unsafeWordsJoinedByDroppedSeparators("дом😀лес", emojiRanges))
        assertEquals(emptySet<Int>(), RuAccentInputSafety.unsafeWordsJoinedByDroppedSeparators("дом—лес", punctuationRanges))
        assertEquals(emptySet<Int>(), RuAccentInputSafety.unsafeWordsJoinedByDroppedSeparators("дом лес", spacedRanges))
    }

}
