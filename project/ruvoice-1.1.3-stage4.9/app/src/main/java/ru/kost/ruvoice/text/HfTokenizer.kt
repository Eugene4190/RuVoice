package ru.kost.ruvoice.text

/** Результат FastTokenizer: offsets — UTF-16 позиции, как у java.lang.String. */
internal data class HfEncoding(
    val ids: LongArray,
    val typeIds: LongArray,
    val attentionMask: LongArray,
    val offsets: Array<IntRange?>,
    val specialMask: BooleanArray,
)

/**
 * Hugging Face tokenizer.json через Rust tokenizers.
 * Не использует Python/Transformers и работает локально после установки модели.
 */
internal class HfTokenizer(tokenizerJson: ByteArray) : AutoCloseable {
    private var handle: Long = nativeCreate(tokenizerJson)

    init { check(handle != 0L) { "Не удалось открыть tokenizer.json" } }

    fun encode(text: String): HfEncoding = decode(nativeEncode(requireHandle(), text))

    fun encodePair(first: String, second: String): HfEncoding =
        decode(nativeEncodePair(requireHandle(), first, second))

    private fun requireHandle(): Long = checkNotNull(handle.takeIf { it != 0L }) {
        "Токенизатор уже закрыт"
    }

    private fun decode(flat: IntArray?): HfEncoding {
        requireNotNull(flat) { "Ошибка токенизации" }
        require(flat.size % COLUMNS == 0) { "Повреждён ответ токенизатора" }
        val count = flat.size / COLUMNS
        val ids = LongArray(count)
        val typeIds = LongArray(count)
        val mask = LongArray(count)
        val offsets = arrayOfNulls<IntRange>(count)
        val special = BooleanArray(count)
        for (i in 0 until count) {
            val p = i * COLUMNS
            ids[i] = flat[p].toLong()
            typeIds[i] = flat[p + 1].toLong()
            mask[i] = flat[p + 2].toLong()
            val start = flat[p + 3]
            val end = flat[p + 4]
            offsets[i] = if (start >= 0 && end > start) start until end else null
            special[i] = flat[p + 5] != 0
        }
        return HfEncoding(ids, typeIds, mask, offsets, special)
    }

    @Synchronized override fun close() {
        if (handle != 0L) {
            nativeDispose(handle)
            handle = 0L
        }
    }

    companion object {
        const val COLUMNS = 6
        init { System.loadLibrary("ruvoice_tokenizers") }

        /** Force the JNI library to load while activating the feature, not on the first book sentence. */
        @JvmStatic fun ensureNativeLoaded() = Unit

        @JvmStatic private external fun nativeCreate(tokenizerJson: ByteArray): Long
        @JvmStatic private external fun nativeEncode(handle: Long, text: String): IntArray?
        @JvmStatic private external fun nativeEncodePair(handle: Long, first: String, second: String): IntArray?
        @JvmStatic private external fun nativeDispose(handle: Long)
    }
}
