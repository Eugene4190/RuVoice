package ru.kost.ruvoice.text

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileInputStream
import java.util.Locale
import java.util.zip.GZIPInputStream
import kotlin.math.exp

/**
 * Локальный Kotlin-порт пайплайна RUAccent int8. Архитектура и выравнивание токенов
 * сверены с TigreGotico/stressonnx (Apache-2.0); исходные веса и словари RUAccent
 * распространяются авторами RUAccent под MIT. См. licenses/THIRD_PARTY_NOTICES.md.
 *
 * Полный локальный порт пайплайна RUAccent int8:
 * 1) STRESS/NO_STRESS по контексту;
 * 2) е/ё и ё-омографы;
 * 3) контекстный NLI-выбор варианта омографа;
 * 4) словарь или символьная RoFormer-модель для остальных многосложных слов.
 *
 * Модели загружаются лениво при первом вызове correct(). Сеть этому классу не нужна.
 */
internal class RuAccentOnnxCorrector(private val root: File) : IndependentStressCorrector, AutoCloseable {
    private val env = OrtEnvironment.getEnvironment()

    init { HfTokenizer.ensureNativeLoaded() }
    // Python's RUAccent tokenizer treats all Unicode separator characters as whitespace.
    // Java's default \s is ASCII-only unless UNICODE_CHARACTER_CLASS is enabled.
    private val pipelineTokenRegex = Regex("[\\p{L}\\p{N}_\\u0301]+|[^\\s\\p{Z}\\u0085\\u2028\\u2029\\u001c-\\u001f\\p{L}\\p{N}_\\u0301]+")
    private val wordRegex = Regex("[\\p{L}\\u0301]+")
    private val vowels = "аеёиоуыэюя"
    private val acute = '\u0301'

    private var loaded = false
    private var closed = false
    // A broken/mismatched model must not trigger four failed session creations on every TTS chunk.
    // Refreshing the corrector constructs a new instance and permits another load attempt.
    private var loadFailure: Throwable? = null

    private lateinit var stressSession: OrtSession
    private lateinit var yoSession: OrtSession
    private lateinit var omographSession: OrtSession
    private lateinit var accentSession: OrtSession
    // ONNX Runtime requires SessionOptions to outlive every session created from it.
    private var sessionOptions: OrtSession.SessionOptions? = null
    private lateinit var stressTokenizer: HfTokenizer
    private lateinit var yoTokenizer: HfTokenizer
    private lateinit var omographTokenizer: HfTokenizer
    private lateinit var stressLabels: Map<Int, String>
    private lateinit var yoLabels: Map<Int, String>
    private lateinit var accentLabels: Map<Int, String>
    private lateinit var accentVocab: Map<String, Int>
    private lateinit var omographs: JSONObject
    private lateinit var yoWords: JSONObject
    private lateinit var yoHomographs: JSONObject
    private lateinit var accents: JSONObject

    private data class Span(val start: Int, val end: Int, val text: String)
    private data class LabelPrediction(val label: String, val confidence: Float)
    private data class EncodedLogits(val rows: Array<FloatArray>)

    /**
     * Loads all four ONNX sessions and performs one tiny local inference after model installation.
     * Call only from a background thread: on a phone this first pass can take noticeable time.
     */
    @Synchronized
    internal fun warmUp(): Boolean {
        val result = correct("Старый замок стоял у берёзы, а рядом росли сосны.")
        return result != null && loaded && !closed
    }

    @Synchronized
    override fun correct(sentence: String): IndependentStressPrediction? {
        if (closed || loadFailure != null) return null
        return try {
            ensureLoaded()
            predict(sentence)
        } catch (error: Throwable) {
            // Disable this optional layer for the process after a runtime/model failure.
            // Stress.apply will use the original RuVoice result; do not retry broken ONNX
            // sessions on every following sentence.
            closePartialResources()
            loadFailure = error
            throw error
        }
    }

    private fun ensureLoaded() {
        if (loaded) return
        loadFailure?.let { throw IllegalStateException("RUAccent-модель ранее не загрузилась", it) }
        require(root.isDirectory) { "Папка RUAccent не найдена" }

        val options = OrtSession.SessionOptions().apply {
            setIntraOpNumThreads(2)
            setInterOpNumThreads(1)
            setExecutionMode(OrtSession.SessionOptions.ExecutionMode.SEQUENTIAL)
        }
        sessionOptions = options
        try {
            stressSession = env.createSession(File(root, "nn_stress_usage/model.int8.onnx").absolutePath, options)
            yoSession = env.createSession(File(root, "nn_yo_homograph/model.onnx").absolutePath, options)
            omographSession = env.createSession(File(root, "nn_omograph/model.int8.onnx").absolutePath, options)
            accentSession = env.createSession(File(root, "nn_accent/model.onnx").absolutePath, options)

            stressTokenizer = HfTokenizer(File(root, "nn_stress_usage/tokenizer.json").readBytes())
            yoTokenizer = HfTokenizer(File(root, "nn_yo_homograph/tokenizer.json").readBytes())
            omographTokenizer = HfTokenizer(File(root, "nn_omograph/tokenizer.json").readBytes())

            stressLabels = readLabels(File(root, "nn_stress_usage/config.json"))
            yoLabels = readLabels(File(root, "nn_yo_homograph/config.json"))
            accentLabels = readLabels(File(root, "nn_accent/config.json"))
            check("STRESS" in stressLabels.values && "NO_STRESS" in stressLabels.values) {
                "Неизвестные метки модели nn_stress_usage"
            }
            check("YO" in yoLabels.values) { "Неизвестные метки модели nn_yo_homograph" }
            check("STRESS_PRIMARY" in accentLabels.values) { "Неизвестные метки модели nn_accent" }
            accentVocab = RuAccentCharAccentPolicy.parseVocab(
                File(root, "nn_accent/vocab.txt").readLines(Charsets.UTF_8)
            )

            omographs = readGzipJson(File(root, "dictionary/omographs.json.gz"))
            yoWords = readYoDictionary(File(root, "dictionary/yo_words.json.gz"), "yo_words")
            yoHomographs = readYoDictionary(File(root, "dictionary/yo_homographs.json.gz"), "yo_homographs")
            accents = readGzipJson(File(root, "dictionary/accents_nn.json.gz"))
            // Те же специальные записи, что в оригинальном RUAccent.
            if (!omographs.has("коса")) omographs.put("коса", JSONArray(listOf("к+оса", "кос+а")))
            accents.put("о", "+о").put("О", "+О")
            loaded = true
        } catch (error: Throwable) {
            closePartialResources()
            loadFailure = error
            throw error
        }
    }

    private fun predict(input: String): IndependentStressPrediction {
        // RUAccent нормализует копию входа. Заменяем неподдерживаемые символы пробелами,
        // а не удаляем их: UTF-16 offsets остаются выровнены с исходным предложением.
        val modelText = normalizeSameLength(input)
        val pipelineSpans = pipelineTokenSpans(modelText)
        val wordSpans = wordRegex.findAll(input).map { Span(it.range.first, it.range.last + 1, it.value) }.toList()
        if (wordSpans.isEmpty()) return IndependentStressPrediction(input, emptyList())
        // If normalisation would delete a visible non-space separator between two words,
        // upstream RUAccent joins them and refuses to mark either fragment. Keep that safety rule.
        val unsafeJoinedWords = RuAccentInputSafety.unsafeWordsJoinedByDroppedSeparators(
            input, wordSpans.map { it.start until it.end }
        )

        val stressPredictions = classifyWords(modelText, pipelineSpans, stressSession, stressTokenizer, stressLabels)
        val yoModelText = lowercaseSameLength(modelText)
        val yoPredictions = if ('е' in yoModelText) {
            // Upstream RUAccent lowercases the full sentence before the DistilBERT ё pass.
            // Lowercasing Russian preserves UTF-16 offsets, so the same spans remain valid.
            classifyWords(yoModelText, pipelineSpans, yoSession, yoTokenizer, yoLabels)
        } else emptyList()

        // RUAccent сначала восстанавливает «ё», а затем оценивает омографы на одном
        // неизменяемом снимке этого контекста. Все NLI-решения ниже используют именно его.
        val yoContext = StringBuilder(modelText)
        for (wordIndex in wordSpans.indices.reversed()) {
            if (wordIndex in unsafeJoinedWords) continue
            val span = wordSpans[wordIndex]
            val modelWord = modelText.substring(span.start, span.end)
            val lowerWord = modelWord.lowercase(Locale.ROOT)
            if (lowerWord.none { it in 'а'..'я' || it == 'ё' } ||
                lowerWord.any { !(it in 'а'..'я' || it == 'ё' || it == acute) }) continue
            val pipelineIndex = pipelineSpans.indexOfFirst { span.start >= it.start && span.start < it.end }
            if (pipelineIndex < 0 || pipelineSpans[pipelineIndex].text != modelWord) continue
            val restored = resolveYoWord(modelWord, lowerWord, yoPredictions.getOrNull(pipelineIndex)).word
            if (restored.length == span.end - span.start) {
                yoContext.replace(span.start, span.end, restored.lowercase(Locale.ROOT))
            }
        }
        val omographContext = yoContext.toString()

        // Работаем со словами отдельно, но возвращаем предложение с исходной пунктуацией и пробелами.
        val output = StringBuilder(input)
        val decisions = ArrayList<StressDecision>(wordSpans.size)
        val yoDecisions = ArrayList<YoDecision>(wordSpans.size)
        val yoDecisionSources = ArrayList<YoDecisionSource>(wordSpans.size)
        for (wordIndex in wordSpans.indices.reversed()) {
            val span = wordSpans[wordIndex]
            val sourceWord = input.substring(span.start, span.end)
            if (wordIndex in unsafeJoinedWords) {
                decisions.add(0, StressDecision.UNKNOWN)
                yoDecisions.add(0, YoDecision.UNKNOWN)
                yoDecisionSources.add(0, YoDecisionSource.UNKNOWN)
                continue
            }
            val modelWord = modelText.substring(span.start, span.end)
            val lowerModelWord = modelWord.lowercase(Locale.ROOT)
            val cyrillic = lowerModelWord.any { it in 'а'..'я' || it == 'ё' } &&
                lowerModelWord.all { it in 'а'..'я' || it == 'ё' || it == acute }
            if (!cyrillic) {
                decisions.add(0, StressDecision.UNKNOWN)
                yoDecisions.add(0, YoDecision.UNKNOWN)
                yoDecisionSources.add(0, YoDecisionSource.UNKNOWN)
                continue
            }
            val pipelineIndex = pipelineSpans.indexOfFirst { span.start >= it.start && span.start < it.end }
            // Only alter tokens the models saw as exactly this complete word. Mixed tokens
            // such as "дом5", script mixtures and unsupported symbols are left untouched.
            if (pipelineIndex < 0 || pipelineSpans[pipelineIndex].text != modelWord) {
                decisions.add(0, StressDecision.UNKNOWN)
                yoDecisions.add(0, YoDecision.UNKNOWN)
                yoDecisionSources.add(0, YoDecisionSource.UNKNOWN)
                continue
            }
            val usage = stressPredictions.getOrNull(pipelineIndex)
            val yo = yoPredictions.getOrNull(pipelineIndex)

            // 1. Словарные и контекстные правила «ё» — тот же результат, который использован
            // для контекстного снимка NLI выше.
            val yoResolution = resolveYoWord(sourceWord, lowerModelWord, yo)
            var rendered = yoResolution.word
            yoDecisions.add(0, yoResolution.decision)
            yoDecisionSources.add(0, yoResolution.source)

            // 2. Контекстный NLI-омограф. Все кандидаты видят один и тот же yoContext snapshot.
            val lowerAfterYo = rendered.lowercase(Locale.ROOT)
            val omographVariants = omographVariants(lowerAfterYo)
            val isKnownOmograph = omographVariants.size >= 2
            var hasResolvedOmograph = false
            if (isKnownOmograph) {
                val chosen = chooseOmograph(omographContext, span, omographVariants)
                if (chosen != null) {
                    rendered = plusToAcute(sourceWord = rendered, markedTarget = chosen)
                    hasResolvedOmograph = rendered.contains(acute)
                }
            }

            // 3. Стресс-usage. Слова с явно написанной ё в RUAccent принудительно относятся к STRESS.
            val sourceHasYo = sourceWord.any { it == 'ё' || it == 'Ё' }
            val effectiveUsage = if (sourceHasYo) LabelPrediction("STRESS", 1f) else usage
            var decision = StressDecision.UNKNOWN
            val isPoAdverbPart = pipelineIndex >= 2 &&
                pipelineSpans[pipelineIndex - 1].text == "-" &&
                pipelineSpans[pipelineIndex - 2].text.equals("по", ignoreCase = true) &&
                lowerModelWord in PO_ADVERBS
            val isHyphenEnclitic = pipelineIndex > 0 &&
                pipelineSpans[pipelineIndex - 1].text == "-" &&
                lowerModelWord in UNSTRESSED_HYPHEN_CLITICS

            when {
                hasResolvedOmograph -> decision = StressDecision.STRESSED
                !RuAccentDecisionPolicy.canUseWordOnlyFallback(isKnownOmograph, hasResolvedOmograph) -> {
                    decision = StressDecision.UNKNOWN // unresolved NLI: never guess from a word-only fallback
                }
                isPoAdverbPart -> {
                    rendered = plusToAcute(rendered, PO_ADVERBS.getValue(lowerModelWord))
                    decision = StressDecision.STRESSED
                }
                isHyphenEnclitic -> decision = StressDecision.UNSTRESSED
                else -> when {
                    effectiveUsage?.label == "NO_STRESS" && effectiveUsage.confidence >= STRESS_CONFIDENCE -> {
                        decision = StressDecision.UNSTRESSED
                    }
                    effectiveUsage?.label == "STRESS" && effectiveUsage.confidence >= STRESS_CONFIDENCE -> {
                        // Upstream RUAccent runs the char model whenever the dictionary result
                        // is identical to the unmarked word (including a present identity entry).
                        // A non-identity dictionary form is converted from '+' to combining acute.
                        val dictionaryAccent = accents.optString(lowerAfterYo, lowerAfterYo)
                        if (RuAccentDecisionPolicy.shouldUseCharAccentFallback(
                                dictionaryAccent = dictionaryAccent,
                                plainWord = lowerAfterYo,
                                hasPunctuation = false,
                                vowelCount = countVowels(lowerAfterYo),
                            )) {
                            val charAccent = predictCharAccent(rendered)
                            if (charAccent != null) rendered = charAccent
                        } else if (dictionaryAccent != lowerAfterYo) {
                            rendered = plusToAcute(rendered, dictionaryAccent)
                        }
                        decision = if (rendered.contains(acute)) StressDecision.STRESSED else StressDecision.UNKNOWN
                    }
                }
            }
            decisions.add(0, decision)
            output.replace(span.start, span.end, rendered)
        }
        return IndependentStressPrediction(output.toString(), decisions, yoDecisions, yoDecisionSources)
    }

    private fun resolveYoWord(
        sourceWord: String,
        lowerWord: String,
        prediction: LabelPrediction?,
    ): YoDictionaryResolution = RuAccentYoDictionaryPolicy.resolve(
        sourceWord = sourceWord,
        fixedWord = yoWords.optString(lowerWord, "").ifEmpty { null },
        homographWord = yoHomographs.optString(lowerWord, "").ifEmpty { null },
        modelLabel = prediction?.label,
        modelConfidence = prediction?.confidence ?: 0f,
        confidenceThreshold = YO_CONFIDENCE,
    )

    /** Сегменты RUAccent: runs букв/цифр/combining marks и runs пунктуации, без пробелов. */
    private fun pipelineTokenSpans(text: String): List<Span> = pipelineTokenRegex.findAll(text)
        .map { Span(it.range.first, it.range.last + 1, it.value) }
        .toList()

    private fun classifyWords(
        text: String,
        spans: List<Span>,
        session: OrtSession,
        tokenizer: HfTokenizer,
        labels: Map<Int, String>,
    ): List<LabelPrediction?> {
        if (spans.isEmpty()) return emptyList()
        val predictions = arrayOfNulls<LabelPrediction>(spans.size)

        fun classifyRange(from: Int, until: Int) {
            if (from >= until) return
            val globalStart = spans[from].start
            val globalEnd = spans[until - 1].end
            val chunkText = text.substring(globalStart, globalEnd)
            val encoded = tokenizer.encode(chunkText)
            // The source models have a 512-token context. Split oversized sentences at
            // token boundaries, retaining the exact word-to-offset mapping for each half.
            if (encoded.ids.size > MODEL_MAX_TOKENS) {
                if (until - from <= 1) return // a single pathological token is safer as UNKNOWN
                val middle = from + (until - from) / 2
                classifyRange(from, middle)
                classifyRange(middle, until)
                return
            }
            if (encoded.ids.isEmpty()) return
            val logits = runTokenLogits(session, encoded)
            val localSpans = spans.subList(from, until).map {
                Span(it.start - globalStart, it.end - globalStart, it.text)
            }
            val sums = Array(localSpans.size) { FloatArray(logits.rows.firstOrNull()?.size ?: 0) }
            val counts = IntArray(localSpans.size)
            for (tokenIndex in encoded.ids.indices) {
                if (encoded.specialMask.getOrElse(tokenIndex) { true }) continue
                val offset = encoded.offsets.getOrNull(tokenIndex) ?: continue
                val spanIndex = localSpans.indexOfFirst { offset.first >= it.start && offset.first < it.end }
                if (spanIndex < 0 || tokenIndex >= logits.rows.size) continue
                val probs = softmax(logits.rows[tokenIndex])
                for (labelIndex in probs.indices) sums[spanIndex][labelIndex] += probs[labelIndex]
                counts[spanIndex]++
            }
            for (index in localSpans.indices) {
                if (counts[index] == 0 || sums[index].isEmpty()) continue
                val avg = FloatArray(sums[index].size) { sums[index][it] / counts[index] }
                val best = avg.indices.maxByOrNull { avg[it] } ?: continue
                val label = labels[best] ?: continue
                predictions[from + index] = LabelPrediction(label, avg[best])
            }
        }

        classifyRange(0, spans.size)
        return predictions.toList()
    }

    private fun chooseOmograph(sentence: String, target: Span, candidates: List<String>): String? {
        val contextSpans = pipelineTokenSpans(sentence).filter { it.text.isNotBlank() }
        val targetIndex = contextSpans.indexOfFirst { target.start >= it.start && target.start < it.end }
        if (targetIndex < 0) return null

        // Shrink the context window exactly as the reference implementation does until
        // the NLI pair fits the BERT/RoBERTa 512-token limit.
        val contextWords = contextSpans.map { it.text.lowercase(Locale.ROOT) }
        var radius = OMOGRAPH_CONTEXT_WORDS
        lateinit var encodedByCandidate: List<Pair<String, HfEncoding>>
        while (true) {
            val preparedContext = RuAccentOmographContext.buildMarkedWindow(
                words = contextWords,
                targetIndex = targetIndex,
                radius = radius,
            ) ?: return null
            val encoded = candidates.map { it to omographTokenizer.encodePair(preparedContext, it) }
            if (encoded.all { it.second.ids.size <= MODEL_MAX_TOKENS }) {
                encodedByCandidate = encoded
                break
            }
            if (radius == 0) return null
            radius /= 2
        }

        val scores = encodedByCandidate.mapNotNull { (candidate, encoded) ->
            val logits = runSequenceLogits(omographSession, encoded)
            if (logits.size < 2) null else candidate to softmax(logits)[1]
        }.sortedByDescending { it.second }
        val best = scores.firstOrNull() ?: return null
        val runnerUp = scores.getOrNull(1)?.second ?: 0f
        // A small score margin prevents near-ties from rewriting a known RuVoice reading.
        if (best.second < OMOGRAPH_MIN_ENTAILMENT || best.second - runnerUp < OMOGRAPH_MIN_MARGIN) return null
        return best.first
    }

    private fun predictCharAccent(word: String): String? {
        val ids = RuAccentCharAccentPolicy.buildInputIds(word, accentVocab)
        val logits = runTokenLogits(
            accentSession,
            ids,
            LongArray(ids.size) { 0L },
            LongArray(ids.size) { 1L },
        )
        return RuAccentCharAccentPolicy.markWord(
            word = word,
            logitsByPosition = logits.rows,
            id2label = accentLabels,
            minConfidence = CHAR_STRESS_CONFIDENCE,
        )
    }

    private fun runTokenLogits(session: OrtSession, encoding: HfEncoding): EncodedLogits =
        runTokenLogits(session, encoding.ids, encoding.typeIds, encoding.attentionMask)

    private fun runTokenLogits(
        session: OrtSession,
        ids: LongArray,
        typeIds: LongArray,
        attentionMask: LongArray,
    ): EncodedLogits {
        val tensors = LinkedHashMap<String, OnnxTensor>()
        try {
            val inputs = session.inputNames
            if ("input_ids" in inputs) tensors["input_ids"] = OnnxTensor.createTensor(env, arrayOf(ids))
            if ("attention_mask" in inputs) tensors["attention_mask"] = OnnxTensor.createTensor(env, arrayOf(attentionMask))
            if ("token_type_ids" in inputs) tensors["token_type_ids"] = OnnxTensor.createTensor(env, arrayOf(typeIds))
            check(tensors.isNotEmpty()) { "У модели нет известных входов" }
            session.run(tensors).use { result ->
                val output = result.get(0) as? OnnxTensor ?: error("ONNX вернула не Tensor")
                val flat = flattenNumbers(output.value)
                check(flat.isNotEmpty() && ids.isNotEmpty() && flat.size % ids.size == 0) {
                    "Неожиданная форма выхода модели: ${flat.size} значений на ${ids.size} токенов"
                }
                val labels = flat.size / ids.size
                return EncodedLogits(Array(ids.size) { row -> FloatArray(labels) { col -> flat[row * labels + col] } })
            }
        } finally {
            tensors.values.forEach { runCatching { it.close() } }
        }
    }

    /** Sequence-classification output (the NLI omograph model is [batch, 2], not token logits). */
    private fun runSequenceLogits(session: OrtSession, encoding: HfEncoding): FloatArray {
        val tensors = LinkedHashMap<String, OnnxTensor>()
        try {
            val inputs = session.inputNames
            if ("input_ids" in inputs) tensors["input_ids"] = OnnxTensor.createTensor(env, arrayOf(encoding.ids))
            if ("attention_mask" in inputs) tensors["attention_mask"] = OnnxTensor.createTensor(env, arrayOf(encoding.attentionMask))
            if ("token_type_ids" in inputs) tensors["token_type_ids"] = OnnxTensor.createTensor(env, arrayOf(encoding.typeIds))
            check(tensors.isNotEmpty()) { "У NLI-модели нет известных входов" }
            session.run(tensors).use { result ->
                val output = result.get(0) as? OnnxTensor ?: error("NLI вернула не Tensor")
                val flat = flattenNumbers(output.value)
                check(flat.size >= 2) { "Некорректный выход NLI: ${flat.size} значений" }
                return flat
            }
        } finally {
            tensors.values.forEach { runCatching { it.close() } }
        }
    }

    private fun flattenNumbers(value: Any): FloatArray {
        val values = ArrayList<Float>()
        fun visit(item: Any?) {
            when {
                item == null -> Unit
                item is Number -> values += item.toFloat()
                item.javaClass.isArray -> {
                    val length = java.lang.reflect.Array.getLength(item)
                    for (i in 0 until length) visit(java.lang.reflect.Array.get(item, i))
                }
                else -> error("Неизвестный тип ONNX-выхода: ${item.javaClass.name}")
            }
        }
        visit(value)
        return values.toFloatArray()
    }

    private fun softmax(logits: FloatArray): FloatArray {
        if (logits.isEmpty()) return FloatArray(0)
        val max = logits.maxOrNull() ?: 0f
        val exps = FloatArray(logits.size) { exp((logits[it] - max).toDouble()).toFloat() }
        val sum = exps.sum().coerceAtLeast(1e-20f)
        return FloatArray(exps.size) { exps[it] / sum }
    }

    private fun plusToAcute(sourceWord: String, markedTarget: String): String {
        val output = StringBuilder(sourceWord.length + 2)
        var sourceIndex = 0
        var plusPending = false
        for (ch in markedTarget) {
            if (ch == '+') {
                plusPending = true
                continue
            }
            val sourceChar = sourceWord.getOrNull(sourceIndex) ?: ch
            output.append(sourceChar)
            if (plusPending && sourceChar.lowercaseChar() in vowels) output.append(acute)
            plusPending = false
            sourceIndex++
        }
        return output.toString()
    }

    private fun transferCase(source: String, target: String): String {
        if (source.length != target.length) return target
        return target.mapIndexed { index, c -> if (source[index].isUpperCase()) c.uppercaseChar() else c.lowercaseChar() }.joinToString("")
    }

    private fun omographVariants(word: String): List<String> {
        val value = omographs.opt(word) ?: return emptyList()
        if (value !is JSONArray) return emptyList()
        return (0 until value.length()).mapNotNull { index -> value.optString(index).takeIf { it.isNotBlank() } }
    }

    private fun normalizeSameLength(text: String): String = RuAccentInputSafety.normalizeSameLength(text)

    /** Lowercase only when UTF-16 length is preserved, keeping offsets valid for tokenizer spans. */
    private fun lowercaseSameLength(text: String): String = buildString(text.length) {
        for (char in text) {
            val lowered = char.toString().lowercase(Locale.ROOT)
            append(if (lowered.length == 1) lowered else char.toString())
        }
    }

    private fun countVowels(word: String): Int = word.count { it.lowercaseChar() in vowels }

    private fun readLabels(file: File): Map<Int, String> {
        val source = JSONObject(file.readText(Charsets.UTF_8)).getJSONObject("id2label")
        val result = HashMap<Int, String>()
        val keys = source.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            key.toIntOrNull()?.let { result[it] = source.getString(key) }
        }
        return result
    }

    private fun readYoDictionary(file: File, dictionaryName: String): JSONObject {
        val dictionary = readGzipJson(file)
        val entries = LinkedHashMap<String, Any?>()
        val keys = dictionary.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            entries[key] = dictionary.opt(key)
        }
        RuAccentYoDictionaryPolicy.validateDictionary(dictionaryName, entries)
        return dictionary
    }

    private fun readGzipJson(file: File): JSONObject =
        GZIPInputStream(FileInputStream(file)).bufferedReader(Charsets.UTF_8).use { JSONObject(it.readText()) }

    private fun closePartialResources() {
        if (::stressSession.isInitialized) runCatching { stressSession.close() }
        if (::yoSession.isInitialized) runCatching { yoSession.close() }
        if (::omographSession.isInitialized) runCatching { omographSession.close() }
        if (::accentSession.isInitialized) runCatching { accentSession.close() }
        if (::stressTokenizer.isInitialized) runCatching { stressTokenizer.close() }
        if (::yoTokenizer.isInitialized) runCatching { yoTokenizer.close() }
        if (::omographTokenizer.isInitialized) runCatching { omographTokenizer.close() }
        // Sessions must close before their shared SessionOptions; see ONNX Runtime Java API.
        sessionOptions?.let { options -> runCatching { options.close() } }
        sessionOptions = null
        loaded = false
    }

    @Synchronized
    override fun close() {
        if (closed) return
        closed = true
        closePartialResources()
    }

    private companion object {
        const val STRESS_CONFIDENCE = 0.60f
        const val YO_CONFIDENCE = 0.65f
        const val CHAR_STRESS_CONFIDENCE = RuAccentCharAccentPolicy.DEFAULT_MIN_CONFIDENCE
        const val OMOGRAPH_CONTEXT_WORDS = 64
        const val OMOGRAPH_MIN_ENTAILMENT = 0.55f
        const val OMOGRAPH_MIN_MARGIN = 0.08f
        const val MODEL_MAX_TOKENS = 512
        val PO_ADVERBS = mapOf("моему" to "м+оему", "твоему" to "тв+оему")
        val UNSTRESSED_HYPHEN_CLITICS = setOf("то", "нибудь", "либо", "таки", "ка")
    }
}
