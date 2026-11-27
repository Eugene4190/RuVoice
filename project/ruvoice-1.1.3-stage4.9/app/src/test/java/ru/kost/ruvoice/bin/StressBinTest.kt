package ru.kost.ruvoice.bin

import java.nio.ByteBuffer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class StressBinTest {
    @Test
    fun writesProductionJsonTablesAndRestoresYoWithTheDesktopJsonRuntime() {
        val json = """
            {
              "exceptions": { "слово": [1, 2] },
              "homodict": {},
              "bert": { "vocab": {} },
              "phrases": {},
              "gram": {}
            }
        """.trimIndent()

        val bytes = StressBin.write(json, sequenceOf("ёж"))
        val decoded = StressBin.File(ByteBuffer.wrap(bytes))

        val exceptionTable = decoded.table("exceptions")
        assertEquals(1, exceptionTable.size)
        val value = exceptionTable.find("слово")
        assertTrue("The exception entry must be indexed", value >= 0)
        assertEquals(1, exceptionTable.int(value))
        assertEquals(2, exceptionTable.int(value, 1))
        assertEquals("ёж", StressBin.yoRestore(decoded.table("yo"), "еж"))
    }
}
