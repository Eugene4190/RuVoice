package ru.kost.ruvoice.text

/**
 * Pure context-window builder shared by the Android NLI resolver and its tests.
 * The marked token intentionally carries leading/trailing spaces: this mirrors
 * stressonnx RuAccentStressor._omograph_feed() before BPE tokenization.
 */
internal object RuAccentOmographContext {
    private const val WORD_MARKER_OPEN = "<w>"
    private const val WORD_MARKER_CLOSE = "</w>"
    private const val PUNCTUATION = "!\"#%&'()*,./:;<=>?@[\\]^_`{|}-"

    /** Returns null only when targetIndex cannot be represented in the selected window. */
    fun buildMarkedWindow(words: List<String>, targetIndex: Int, radius: Int): String? {
        if (words.isEmpty() || targetIndex !in words.indices || radius < 0) return null
        val size = radius * 2 + 1
        val left = maxOf(0, minOf(targetIndex - radius, words.size - size))
        val selected = words.subList(left, minOf(words.size, left + size)).toMutableList()
        val localIndex = targetIndex - left
        if (localIndex !in selected.indices) return null

        // Keep the padding spaces exactly as in the reference Python backend.
        selected[localIndex] = " $WORD_MARKER_OPEN${selected[localIndex]}$WORD_MARKER_CLOSE "
        return deleteSpacesBeforePunctuation(selected.joinToString(" "))
    }

    internal fun deleteSpacesBeforePunctuation(source: String): String {
        var result = source
        for (char in PUNCTUATION) {
            if (char == '-') result = result.replace(" -", "-").replace("- ", "-")
            result = result.replace(" $char", char.toString())
        }
        return result.replace("~", "-")
    }
}
