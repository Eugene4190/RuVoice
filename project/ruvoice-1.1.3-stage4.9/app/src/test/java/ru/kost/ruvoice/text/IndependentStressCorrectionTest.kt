package ru.kost.ruvoice.text

import org.junit.Assert.assertEquals
import org.junit.Test

class IndependentStressCorrectionTest {
    @Test fun int8ModelManifestIsPinnedAndUnique() {
        assertEquals(16, RuAccentInt8ModelManifest.files.size)
        assertEquals(RuAccentInt8ModelManifest.files.size, RuAccentInt8ModelManifest.files.toSet().size)
        assertEquals(
            "https://huggingface.co/TigreGotico/stressonnx-models/resolve/cb1594ddf81928e678a3a7ee7a22415e6e3a218f/ru_ruaccent/nn_stress_usage/model.int8.onnx",
            RuAccentInt8ModelManifest.downloadUrl("nn_stress_usage/model.int8.onnx"),
        )
    }

    @Test fun stripsOnlyStressMarkersAndKeepsLiteralPlusSigns() {
        assertEquals("замок C++ A+B C+а", StressInputSanitizer.stripMarkers("з+амок C++ A+B C+а"))
        assertEquals("привет", StressInputSanitizer.stripMarkers("приве\u0301т"))
    }

    @Test fun literalLatinPlusBeforeCyrillicVowelIsNotTreatedAsStress() {
        val source = "C+а замок"
        val current = "C+а з+амок"
        val merged = StressCorrectionMerger.merge(
            original = source,
            ruVoice = current,
            independent = "C+а замо\u0301к",
        )
        assertEquals("C+а зам+ок", merged)
    }

    @Test fun independentPredictionCanReplaceAutomaticStress() {
        val merged = StressCorrectionMerger.merge(
            original = "Старинный замок стоял на горе.",
            ruVoice = "Стар+инный зам+ок сто+ял на гор+е.",
            independent = "Стари\u0301нный за\u0301мок стоя\u0301л на горе\u0301.",
        )
        assertEquals("Стар+инный з+амок сто+ял на гор+е.", merged)
    }

    @Test fun independentPredictionCanCorrectYoAndStressTogether() {
        val merged = StressCorrectionMerger.merge(
            original = "дверной замок надёжен",
            ruVoice = "дверн+ой з+амок над+ёжен",
            independent = "дверно\u0301й замо\u0301к надё\u0301жен",
        )
        assertEquals("дверн+ой зам+ок над+ёжен", merged)
    }

    @Test fun noStressDecisionKeepsSileroFallbackOnPolysyllabicWords() {
        val prediction = IndependentStressPrediction(
            text = "это долгий путь и",
            decisions = listOf(
                StressDecision.UNSTRESSED,
                StressDecision.UNSTRESSED,
                StressDecision.UNSTRESSED,
                StressDecision.UNSTRESSED,
            ),
        )
        val merged = StressCorrectionMerger.merge(
            original = "это долгий путь и",
            ruVoice = "+это до+лгий п+уть +и",
            prediction = prediction,
        )
        assertEquals("+это до+лгий путь и", merged)
    }

    @Test fun noStressDecisionRemovesOnlyMonosyllabicAutomaticMark() {
        val prediction = IndependentStressPrediction(
            text = "это и",
            decisions = listOf(StressDecision.UNSTRESSED, StressDecision.UNSTRESSED),
        )
        val merged = StressCorrectionMerger.merge(
            original = "это и",
            ruVoice = "+это +и",
            prediction = prediction,
        )
        assertEquals("+это и", merged)
    }

    @Test fun unknownDecisionDoesNotEraseExistingMark() {
        val prediction = IndependentStressPrediction(
            text = "редкое имя",
            decisions = listOf(StressDecision.UNKNOWN, StressDecision.UNKNOWN),
        )
        val merged = StressCorrectionMerger.merge(
            original = "редкое имя",
            ruVoice = "р+едкое им+я",
            prediction = prediction,
        )
        assertEquals("р+едкое им+я", merged)
    }

    @Test fun independentPredictionCanUndoAutomaticYoRestoration() {
        val merged = StressCorrectionMerger.merge(
            original = "все люди пришли",
            ruVoice = "всё люди пришл+и",
            independent = "все люди пришли",
        )
        assertEquals("все люди пришл+и", merged)
    }

    @Test fun explicitUserStressIsNeverOverwritten() {
        val merged = StressCorrectionMerger.merge(
            original = "з+амок стоит",
            ruVoice = "з+амок сто+ит",
            independent = "замо\u0301к стои\u0301т",
        )
        assertEquals("з+амок сто+ит", merged)
    }

    @Test fun explicitYoInOriginalIsPreserved() {
        val merged = StressCorrectionMerger.merge(
            original = "всё получилось",
            ruVoice = "всё получ+илось",
            independent = "все получи\u0301лось",
        )
        assertEquals("всё получ+илось", merged)
    }

    @Test fun userDictionaryWordsAreProtected() {
        val merged = StressCorrectionMerger.merge(
            original = "имя и замок",
            ruVoice = "им+я и з+амок",
            independent = "и\u0301мя и замо\u0301к",
            userDictionaryKeys = setOf("имя"),
        )
        assertEquals("им+я и зам+ок", merged)
    }

    @Test fun tokenCountMismatchFailsClosed() {
        val current = "з+амок и дверь"
        assertEquals(
            current,
            StressCorrectionMerger.merge(
                original = "замок и дверь",
                ruVoice = current,
                independent = "замо\u0301к дверь",
            ),
        )
    }

    @Test fun punctuationAndWhitespaceArePreserved() {
        val merged = StressCorrectionMerger.merge(
            original = "«Замок» — это замок!",
            ruVoice = "«Зам+ок» — это з+амок!",
            independent = "«За\u0301мок» — это замо\u0301к!",
        )
        assertEquals("«З+амок» — это зам+ок!", merged)
    }
}
