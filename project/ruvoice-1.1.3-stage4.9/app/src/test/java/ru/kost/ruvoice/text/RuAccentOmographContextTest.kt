package ru.kost.ruvoice.text

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class RuAccentOmographContextTest {
    private val words = listOf("на", "двери", "висел", "замок", ",", "а", "на", "холме", "стоял", "замок", ".")

    @Test fun firstOccurrenceMatchesReferencePaddingAndPunctuation() {
        assertEquals(
            "на двери висел <w>замок</w> , а на холме стоял замок.",
            RuAccentOmographContext.buildMarkedWindow(words, targetIndex = 3, radius = 64),
        )
    }

    @Test fun secondOccurrenceIsMarkedWithoutChangingOtherWords() {
        assertEquals(
            "на двери висел замок, а на холме стоял <w>замок</w> .",
            RuAccentOmographContext.buildMarkedWindow(words, targetIndex = 9, radius = 64),
        )
    }

    @Test fun markedTargetKeepsReferencePaddingBeforeFollowingWord() {
        val adjacentWords = listOf("он", "поставил", "замок", "и", "ушел", ".")
        assertEquals(
            "он поставил <w>замок</w>  и ушел.",
            RuAccentOmographContext.buildMarkedWindow(adjacentWords, targetIndex = 2, radius = 64),
        )
    }

    @Test fun ordinaryTrailingPunctuationHasNoPaddingSpace() {
        val adjacentWords = listOf("он", "поставил", "замок", "и", "ушел", ".")
        assertEquals(
            "он поставил <w>замок</w>  и ушел.",
            RuAccentOmographContext.buildMarkedWindow(adjacentWords, targetIndex = 2, radius = 64),
        )
    }

    @Test fun overlongSentenceUsesSameCenteredWindowCalculation() {
        val longWords = List(160) { "слово" }.toMutableList().also { it[80] = "замок" }
        val actual = RuAccentOmographContext.buildMarkedWindow(longWords, targetIndex = 80, radius = 64)
        assertEquals(129, actual!!.split(' ').count { it.isNotEmpty() })
        assertEquals(1, Regex("<w>замок</w>").findAll(actual).count())
    }

    @Test fun invalidTargetPositionReturnsNull() {
        assertNull(RuAccentOmographContext.buildMarkedWindow(words, targetIndex = 99, radius = 64))
        assertNull(RuAccentOmographContext.buildMarkedWindow(emptyList(), targetIndex = 0, radius = 64))
    }
}
