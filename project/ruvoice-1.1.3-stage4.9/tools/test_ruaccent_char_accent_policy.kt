package ru.kost.ruvoice.text

/** No-Gradle test harness for the production nn_accent input/decoding helper. */
fun main() {
    val vocab = mapOf("к" to 10, "о" to 11, "р" to 12, "в" to 13, "а" to 14)
    val ids = RuAccentCharAccentPolicy.buildInputIds("корова", vocab)
    check(ids.toList() == listOf(2L, 10L, 11L, 12L, 11L, 13L, 14L, 3L)) {
        "Unexpected character-model input ids: ${ids.toList()}"
    }
    val unknown = RuAccentCharAccentPolicy.buildInputIds("циркуляция", vocab)
    check(unknown[1] == 1L) { "Unknown character must use UNK=1" }
    check(runCatching { RuAccentCharAccentPolicy.buildInputIds("я", vocab) }.isFailure) {
        "The OOV char-accent fallback must reject one-character words"
    }

    val labels = mapOf(0 to "O", 1 to "STRESS_PRIMARY", 2 to "STRESS_SECONDARY")
    fun logits(word: String): Array<FloatArray> = Array(word.length + 2) { floatArrayOf(0f, -2f, -3f) }
    val word = "корова"
    val rows = logits(word)
    rows[2] = floatArrayOf(0f, 2f, -2f) // first 'о'
    rows[4] = floatArrayOf(0f, 5f, -2f) // second 'о': higher confidence wins
    rows[3] = floatArrayOf(0f, 8f, -2f) // confident non-vowel, ignored
    check(RuAccentCharAccentPolicy.markWord(word, rows, labels) == "коро\u0301ва") {
        "Must mark the most confident vowel, not the non-vowel"
    }
    check(RuAccentCharAccentPolicy.markWord("КОРОВА", rows, labels) == "КОРО\u0301ВА") {
        "Original casing must be preserved"
    }

    val weak = logits(word)
    weak[2] = floatArrayOf(0f, 0.1f, -2f)
    check(RuAccentCharAccentPolicy.markWord(word, weak, labels) == null) {
        "Low-confidence stress must not be emitted"
    }
    check(runCatching { RuAccentCharAccentPolicy.markWord(word, arrayOf(floatArrayOf(0f)), labels) }.isFailure) {
        "Misaligned char logits must be rejected"
    }
    println("PASS production nn_accent special IDs / char alignment / vowel selection / confidence / minimum-length tests: 6/6")
}
