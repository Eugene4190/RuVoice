package ru.kost.ruvoice.text

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RuAccentDownloadPolicyTest {
    @Test fun appendsOnlyWhenContentRangeMatchesThePartialFile() {
        val plan = RuAccentDownloadPolicy.plan(600, 206, "bytes 600-999/1000", 400)
        assertEquals(RuAccentDownloadPolicy.Action.APPEND, plan.action)
        assertEquals(1000L, plan.expectedTotalBytes)
        assertEquals(400L, plan.responseBytes)
    }

    @Test fun restartsWhenServerIgnoresRangeOrRejectsOffset() {
        assertEquals(
            RuAccentDownloadPolicy.Action.RESTART_FROM_ZERO,
            RuAccentDownloadPolicy.plan(600, 200, null, 1000).action,
        )
        assertEquals(
            RuAccentDownloadPolicy.Action.RETRY_FROM_ZERO,
            RuAccentDownloadPolicy.plan(600, 416, null, 0).action,
        )
    }

    @Test fun rejectsWrongContentRangeAndLength() {
        assertFalse(runCatching { RuAccentDownloadPolicy.plan(600, 206, "bytes 500-999/1000", 500) }.isSuccess)
        assertFalse(runCatching { RuAccentDownloadPolicy.plan(600, 206, "bytes 600-999/1000", 399) }.isSuccess)
        assertTrue(runCatching { RuAccentDownloadPolicy.plan(0, 200, null, 1000) }.isSuccess)
    }
}
