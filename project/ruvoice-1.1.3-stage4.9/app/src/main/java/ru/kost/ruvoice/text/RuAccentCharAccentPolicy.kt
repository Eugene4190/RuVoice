package ru.kost.ruvoice.text

import java.util.Locale
import kotlin.math.exp

/** Pure Kotlin implementation of RUAccent's character-level nn_accent decoding contract. */
internal object RuAccentCharAccentPolicy {
    const val UNK_ID = 1L
    const val BOS_ID = 2L
    const val EOS_ID = 3L
    const val DEFAULT_MIN_CONFIDENCE = 0.55f

    private const val ACUTE = '\u0301'
    private const val VOWELS = "аеёиоуыэюя"

    /** RUAccent hard-codes the special IDs; they are not inferred from token spellings. */
    fun buildInputIds(word: String, charVocab: Map<String, Int>): LongArray {
        require(word.length >= 2 && word.none { it.isWhitespace() }) {
            "nn_accent fallback expects one word with at least two characters"
        }
        val lower = word.lowercase(Locale.ROOT)
        return LongArray(lower.length + 2).also { ids ->
            ids[0] = BOS_ID
            for (index in lower.indices) {
                ids[index + 1] = (charVocab[lower[index].toString()]?.toLong() ?: UNK_ID)
            }
            ids[ids.lastIndex] = EOS_ID
        }
    }

    /**
     * Selects one primary-stress vowel from per-character logits and inserts U+0301
     * after it. Returns null when no vowel crosses the reference confidence threshold.
     */
    fun markWord(
        word: String,
        logitsByPosition: Array<FloatArray>,
        id2label: Map<Int, String>,
        minConfidence: Float = DEFAULT_MIN_CONFIDENCE,
    ): String? {
        require(minConfidence in 0f..1f) { "minConfidence must be in [0, 1]" }
        val lower = word.lowercase(Locale.ROOT)
        require(logitsByPosition.size == lower.length + 2) {
            "Expected ${lower.length + 2} char-logit rows (BOS + chars + EOS), got ${logitsByPosition.size}"
        }
        var bestPosition = -1
        var bestConfidence = 0f
        for (position in lower.indices) {
            val char = lower[position]
            if (char !in VOWELS) continue
            val logits = logitsByPosition[position + 1]
            require(logits.isNotEmpty() && logits.size == id2label.size) {
                "Char-logit class count ${logits.size} does not match id2label ${id2label.size}"
            }
            val probabilities = softmax(logits)
            val labelIndex = probabilities.indices.maxByOrNull { probabilities[it] } ?: continue
            val label = id2label[labelIndex] ?: continue
            val confidence = probabilities[labelIndex]
            if (label == "STRESS_PRIMARY" && confidence >= minConfidence && confidence > bestConfidence) {
                bestConfidence = confidence
                bestPosition = position
            }
        }
        if (bestPosition < 0) return null
        return word.substring(0, bestPosition + 1) + ACUTE + word.substring(bestPosition + 1)
    }

    private fun softmax(logits: FloatArray): FloatArray {
        require(logits.isNotEmpty() && logits.all { it.isFinite() }) { "Invalid char logits" }
        val max = logits.maxOrNull() ?: 0f
        val exponentials = FloatArray(logits.size) { exp((logits[it] - max).toDouble()).toFloat() }
        val total = exponentials.sum().coerceAtLeast(1e-20f)
        return FloatArray(logits.size) { exponentials[it] / total }
    }
}
