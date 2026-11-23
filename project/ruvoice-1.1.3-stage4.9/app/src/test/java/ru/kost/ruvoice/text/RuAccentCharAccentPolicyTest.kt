package ru.kost.ruvoice.text

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class RuAccentCharAccentPolicyTest {
    private val vocab = mapOf("к" to 10, "о" to 11, "р" to 12, "в" to 13, "а" to 14)
    private val labels = mapOf(0 to "O", 1 to "STRESS_PRIMARY", 2 to "STRESS_SECONDARY")

    @Test fun inputUsesFixedReferenceSpecialTokenIds() {
        assertEquals(
            listOf(2L, 10L, 11L, 12L, 11L, 13L, 14L, 3L),
            RuAccentCharAccentPolicy.buildInputIds("корова", vocab).toList(),
        )
        assertEquals(1L, RuAccentCharAccentPolicy.buildInputIds("цирк", vocab)[1])
    }

    @Test fun rejectsSingleCharacterFallbackInput() {
        org.junit.Assert.assertThrows(IllegalArgumentException::class.java) {
            RuAccentCharAccentPolicy.buildInputIds("я", vocab)
        }
    }

    @Test fun selectsHighestConfidencePrimaryStressOnlyOnVowels() {
        val rows = Array(8) { floatArrayOf(0f, -2f, -3f) }
        rows[2] = floatArrayOf(0f, 2f, -2f)
        rows[4] = floatArrayOf(0f, 5f, -2f)
        rows[3] = floatArrayOf(0f, 8f, -2f) // consonant
        assertEquals("коро\u0301ва", RuAccentCharAccentPolicy.markWord("корова", rows, labels))
    }

    @Test fun lowConfidenceDoesNotProduceStress() {
        val rows = Array(8) { floatArrayOf(0f, -2f, -3f) }
        rows[2] = floatArrayOf(0f, 0.1f, -2f)
        assertNull(RuAccentCharAccentPolicy.markWord("корова", rows, labels))
    }

    @Test fun preservesSourceCapitalization() {
        val rows = Array(8) { floatArrayOf(0f, -2f, -3f) }
        rows[4] = floatArrayOf(0f, 5f, -2f)
        assertEquals("КОРО\u0301ВА", RuAccentCharAccentPolicy.markWord("КОРОВА", rows, labels))
    }
}
