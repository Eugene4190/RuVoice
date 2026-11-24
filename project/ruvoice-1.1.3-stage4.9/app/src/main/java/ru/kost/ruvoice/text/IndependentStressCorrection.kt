package ru.kost.ruvoice.text

import java.util.Locale

/**
 * Независимый анализатор русского произношения.
 *
 * Контракт: возвращает исходную фразу без изменения слов и пунктуации, добавляя только
 * U+0301 после ударных гласных и восстанавливая е → ё. Реализация должна работать локально.
 * null означает, что модель временно недоступна или не смогла обработать фразу.
 */
enum class StressDecision {
    /** Модель уверенно определила ударное слово и вернула позицию в [IndependentStressPrediction.text]. */
    STRESSED,
    /** RUAccent leaves the token unmarked. The hybrid keeps Silero's existing mark on polysyllabic fallback words. */
    UNSTRESSED,
    /** Слово не распознано, находится вне словаря/контекста или прогноз неуверенный. */
    UNKNOWN,
}

/** Отдельное решение для «е/ё»: отсутствие «ё» в выводе не всегда означает уверенное «е». */
enum class YoDecision {
    RESTORE_YO,
    KEEP_E,
    UNKNOWN,
}

/** Прогноз модели и решения по ударению/«ё» для каждого слова в том же порядке, что в тексте. */
data class IndependentStressPrediction(
    val text: String,
    val decisions: List<StressDecision>,
    val yoDecisions: List<YoDecision> = emptyList(),
)

fun interface IndependentStressCorrector {
    fun correct(sentence: String): IndependentStressPrediction?
}

/** A homograph with an unresolved contextual NLI result must not fall back to a context-free accent. */
internal data class YoDictionaryResolution(
    val word: String,
    val decision: YoDecision,
)

/**
 * Applies the two RUAccent ё dictionaries with the same precedence as the reference pipeline:
 * fixed yo_words first, then a confident contextual yo_homographs override.
 */
internal object RuAccentYoDictionaryPolicy {
    private fun canonical(value: String): String = value.lowercase(Locale.ROOT).replace('ё', 'е')

    /** Dictionary values may differ from their keys only by е/ё substitutions. */
    fun isValidEntry(key: String, value: String): Boolean {
        if (key.isBlank() || value.isBlank() || key.length != value.length) return false
        val keyCanonical = canonical(key)
        val valueCanonical = canonical(value)
        return keyCanonical == valueCanonical && key.indices.all { index ->
            val left = key[index].lowercaseChar()
            val right = value[index].lowercaseChar()
            left == right || (left in "её" && right in "её")
        }
    }

    /** Validate the whole gzip-JSON dictionary before using any of its entries. */
    fun validateDictionary(dictionaryName: String, entries: Map<String, Any?>): Map<String, String> {
        require(entries.isNotEmpty()) { "$dictionaryName: пустой словарь" }
        val result = LinkedHashMap<String, String>(entries.size)
        for ((key, rawValue) in entries) {
            require(rawValue is String) { "$dictionaryName: значение для '$key' должно быть строкой" }
            require(isValidEntry(key, rawValue)) {
                "$dictionaryName: некорректная пара е/ё для '$key' -> '$rawValue'"
            }
            result[key] = rawValue
        }
        return result
    }

    fun resolve(
        sourceWord: String,
        fixedWord: String?,
        homographWord: String?,
        modelLabel: String?,
        modelConfidence: Float,
        confidenceThreshold: Float,
    ): YoDictionaryResolution {
        // An author's explicit ё is not a dictionary/model correction target.
        if (sourceWord.any { it == 'ё' || it == 'Ё' }) {
            return YoDictionaryResolution(sourceWord, YoDecision.UNKNOWN)
        }

        val safeFixed = fixedWord?.takeIf { isValidEntry(sourceWord, it) }
        val safeHomograph = homographWord?.takeIf { isValidEntry(sourceWord, it) }
        var selected = safeFixed ?: sourceWord
        val confidentYoHomograph = modelLabel == "YO" &&
            modelConfidence >= confidenceThreshold && safeHomograph != null
        if (confidentYoHomograph) selected = safeHomograph!!

        val decision = RuAccentDecisionPolicy.resolveYoDecision(
            fixedWord = safeFixed,
            homographWord = safeHomograph,
            modelLabel = modelLabel,
            modelConfidence = modelConfidence,
            confidenceThreshold = confidenceThreshold,
        )
        return YoDictionaryResolution(transferCase(sourceWord, selected), decision)
    }

    private fun transferCase(source: String, target: String): String {
        if (source.length != target.length) return source
        return target.mapIndexed { index, char ->
            if (source[index].isUpperCase()) char.uppercaseChar() else char.lowercaseChar()
        }.joinToString("")
    }
}

internal object RuAccentDecisionPolicy {
    fun canUseWordOnlyFallback(isKnownOmograph: Boolean, hasResolvedOmograph: Boolean): Boolean =
        !isKnownOmograph || hasResolvedOmograph

    /** RUAccent uses the char model when the dictionary result is the plain word itself. */
    fun shouldUseCharAccentFallback(
        dictionaryAccent: String,
        plainWord: String,
        hasPunctuation: Boolean,
        vowelCount: Int,
    ): Boolean = dictionaryAccent == plainWord && !hasPunctuation && vowelCount > 1

    /** Preserve RUAccent's precedence: fixed yo_words, then a confident YO homograph override. */
    fun resolveYoDecision(
        fixedWord: String?,
        homographWord: String?,
        modelLabel: String?,
        modelConfidence: Float,
        confidenceThreshold: Float,
    ): YoDecision {
        val confident = modelConfidence >= confidenceThreshold
        if (modelLabel == "YO" && confident && !homographWord.isNullOrEmpty()) {
            return if (homographWord.any { it == 'ё' || it == 'Ё' }) YoDecision.RESTORE_YO else YoDecision.KEEP_E
        }
        if (!fixedWord.isNullOrEmpty()) {
            return if (fixedWord.any { it == 'ё' || it == 'Ё' }) YoDecision.RESTORE_YO else YoDecision.KEEP_E
        }
        if (confident && !homographWord.isNullOrEmpty()) {
            return when (modelLabel) {
                "NO_YO" -> YoDecision.KEEP_E
                else -> YoDecision.UNKNOWN
            }
        }
        return YoDecision.UNKNOWN
    }
}


/** Удаляет только служебную разметку RuVoice перед передачей исходного текста независимой модели. */
internal object StressInputSanitizer {
    private const val ACUTE = '\u0301'
    private const val PLUS = '+'
    private const val VOWELS = "аеёиоуыэюяАЕЁИОУЫЭЮЯ"

    private fun isRussianLetter(c: Char): Boolean = c in 'А'..'Я' || c in 'а'..'я' || c == 'Ё' || c == 'ё'

    fun stripMarkers(text: String): String {
        val out = StringBuilder(text.length)
        for (i in text.indices) {
            val ch = text[i]
            when {
                ch == PLUS && i + 1 < text.length && text[i + 1] in VOWELS &&
                    (i == 0 || !text[i - 1].isLetterOrDigit() || isRussianLetter(text[i - 1])) -> Unit
                ch == ACUTE && i > 0 && text[i - 1] in VOWELS -> Unit
                else -> out.append(ch)
            }
        }
        return out.toString()
    }
}

/**
 * Сливает независимый прогноз с результатом штатного конвейера RuVoice.
 *
 * Независимая модель может переопределить автоматически поставленное RuVoice ударение и
 * автоматически восстановленную «ё». Явная разметка во входном тексте и слова пользовательского
 * словаря защищены. Если токены двух результатов не совпали, соответствующее слово не меняется.
 *
 * Предсказания модели должны быть размечены combining acute accent (U+0301), как stressonnx.
 */
internal object StressCorrectionMerger {
    private const val ACUTE = '\u0301'
    private const val PLUS = '+'
    private const val VOWELS = "аеёиоуыэюяАЕЁИОУЫЭЮЯ"
    private val wordRegex = Regex("[\\p{L}+\\u0301]+")

    private data class ParsedWord(
        val base: String,
        val stressed: Set<Int>,
        val yo: Set<Int>,
    )

    /** Convenience overload: unmarked words in a plain string are UNKNOWN, not NO_STRESS. */
    fun merge(
        original: String,
        ruVoice: String,
        independent: String,
        userDictionaryKeys: Set<String> = emptySet(),
        protectedStressIndices: Set<Int> = emptySet(),
    ): String {
        val sourceWords = wordRegex.findAll(original).map { it.value }.toList()
        val currentWords = wordRegex.findAll(ruVoice).map { it.value }.toList()
        val predictedWords = wordRegex.findAll(independent).map { it.value }.toList()
        val decisions = predictedWords.map { token ->
            if (ACUTE in token) StressDecision.STRESSED else StressDecision.UNKNOWN
        }
        val yoDecisions = if (sourceWords.size == currentWords.size && sourceWords.size == predictedWords.size) {
            sourceWords.indices.map { index ->
                val sourceHasYo = sourceWords[index].any { it == 'ё' || it == 'Ё' }
                val currentHasYo = currentWords[index].any { it == 'ё' || it == 'Ё' }
                val predictedHasYo = predictedWords[index].any { it == 'ё' || it == 'Ё' }
                when {
                    sourceHasYo -> YoDecision.UNKNOWN
                    predictedHasYo && !currentHasYo -> YoDecision.RESTORE_YO
                    currentHasYo && !predictedHasYo -> YoDecision.KEEP_E
                    else -> YoDecision.UNKNOWN
                }
            }
        } else emptyList()
        return merge(
            original, ruVoice,
            IndependentStressPrediction(independent, decisions, yoDecisions),
            userDictionaryKeys, protectedStressIndices,
        )
    }

    fun merge(
        original: String,
        ruVoice: String,
        prediction: IndependentStressPrediction,
        userDictionaryKeys: Set<String> = emptySet(),
        protectedStressIndices: Set<Int> = emptySet(),
    ): String {
        val src = wordRegex.findAll(original).toList()
        val current = wordRegex.findAll(ruVoice).toList()
        val predicted = wordRegex.findAll(prediction.text).toList()
        if (src.isEmpty() || src.size != current.size || src.size != predicted.size) return ruVoice

        val protectedKeys = userDictionaryKeys.mapTo(HashSet()) { normalizeKey(it) }
        val protectedTokenIndices = protectedCompoundComponents(original, src, protectedKeys)
        // Explicit stress on one component is an explicit instruction for the complete hyphenated
        // form (e.g. an author's "по-мо+ему" must not be partly rewritten).
        for (i in src.indices) {
            if (hasExplicitStressMarker(src[i].value)) {
                protectedTokenIndices += i
                var left = i
                while (left > 0 && original.substring(src[left - 1].range.last + 1, src[left].range.first).contains('-')) {
                    left--
                    protectedTokenIndices += left
                }
                var right = i
                while (right < src.lastIndex && original.substring(src[right].range.last + 1, src[right + 1].range.first).contains('-')) {
                    right++
                    protectedTokenIndices += right
                }
            }
        }
        val replacements = ArrayList<Pair<IntRange, String>>()

        for (i in src.indices) {
            val sourceToken = src[i].value
            val currentToken = current[i].value
            val predictedToken = predicted[i].value
            val sourceParsed = parse(sourceToken)
            val currentParsed = parse(currentToken)
            val predictedParsed = parse(predictedToken)

            // Строгое сопоставление по буквам (ё/е считаются одной графемой). При сдвиге токенов
            // или нормализации незнакомого слова лучше оставить RuVoice, чем применить чужую позицию.
            val sourceKey = normalizeKey(sourceParsed.base)
            if (sourceKey != normalizeKey(currentParsed.base) || sourceKey != normalizeKey(predictedParsed.base)) continue
            // Надёжное грамматическое решение штатного RuVoice (gramPass) имеет приоритет над
            // конфликтующим нейросетевым омографом. Иначе RUAccent может перезаписать, например,
            // вин. мн. «в р+уки» формой род. ед. «руки́».
            if (sourceKey in protectedKeys || i in protectedTokenIndices || i in protectedStressIndices) continue
            // Явно заданное ударение в исходном тексте — инструкция пользователя, а не прогноз RuVoice.
            if (hasExplicitStressMarker(sourceToken)) continue

            val mergedBase = StringBuilder(currentParsed.base)
            // Ё из оригинала сохраняем. Для остальных е/ё принимаем контекстное решение модели,
            // в том числе возвращаем ё → е, если независимая модель отклонила автоматическую ё RuVoice.
            val originalYo = sourceParsed.yo
            val currentYo = currentParsed.yo
            val yoDecision = prediction.yoDecisions.getOrNull(i)
                ?.takeIf { prediction.yoDecisions.size == src.size } ?: YoDecision.UNKNOWN
            for (p in mergedBase.indices) {
                val ch = mergedBase[p]
                if (ch != 'е' && ch != 'Е' && ch != 'ё' && ch != 'Ё') continue
                // Original author-written ё always wins. RESTORE_YO uses only the exact ё
                // positions predicted by the model; KEEP_E removes automatic ё; UNKNOWN preserves
                // RuVoice's current choice. Never turn every е in a word into ё at once.
                val useYo = p in originalYo || when (yoDecision) {
                    YoDecision.RESTORE_YO -> p in predictedParsed.yo
                    YoDecision.KEEP_E -> false
                    YoDecision.UNKNOWN -> p in currentYo
                }
                val replacement = when {
                    useYo && ch.isUpperCase() -> 'Ё'
                    useYo -> 'ё'
                    !useYo && (ch == 'ё' || ch == 'Ё') -> if (ch.isUpperCase()) 'Е' else 'е'
                    else -> ch
                }
                mergedBase.setCharAt(p, replacement)
            }

            // RUAccent STRESS задаёт/исправляет позицию. NO_STRESS означает, что сам RUAccent
            // оставляет токен без отметки, а не то, что нужно стирать Silero fallback:
            // для многосложного слова сохраняем штатное ударение, как в ruaccent-silero.
            // Односложные токены оставляем без плюса: их ударение однозначно и не требует
            // подсказки синтезатору. UNKNOWN всегда сохраняет исходный результат.
            // Без полного выравнивания decision-меток безопасно считаем все слова UNKNOWN.
            val decision = prediction.decisions.getOrNull(i)
                ?.takeIf { prediction.decisions.size == src.size } ?: StressDecision.UNKNOWN
            val selectedStress = when (decision) {
                // Если модель заявила STRESSED, но не указала позицию U+0301,
                // прогноз внутренне противоречив: не стираем и не переносим знак.
                StressDecision.STRESSED -> predictedParsed.stressed.ifEmpty { currentParsed.stressed }
                StressDecision.UNSTRESSED -> if (currentParsed.base.count { it.lowercaseChar() in VOWELS } >= 2) {
                    currentParsed.stressed
                } else emptySet()
                StressDecision.UNKNOWN -> currentParsed.stressed
            }
            val rendered = buildString(mergedBase.length + selectedStress.size) {
                for (p in mergedBase.indices) {
                    if (p in selectedStress) append(PLUS)
                    append(mergedBase[p])
                }
            }

            if (rendered != currentToken) replacements += current[i].range to rendered
        }

        if (replacements.isEmpty()) return ruVoice
        val result = StringBuilder(ruVoice)
        for ((range, replacement) in replacements.asReversed()) {
            result.replace(range.first, range.last + 1, replacement)
        }
        return result.toString()
    }


    /**
     * User dictionaries in RuVoice can contain a full hyphenated entry such as "по-моему".
     * The merger tokenizes components separately so it can align model decisions. Protect every
     * component when the joined source spelling matches one dictionary key.
     */
    private fun protectedCompoundComponents(
        original: String,
        words: List<MatchResult>,
        protectedKeys: Set<String>,
    ): MutableSet<Int> {
        val protected = HashSet<Int>()
        if (protectedKeys.isEmpty()) return protected
        for (start in words.indices) {
            var end = start
            while (end < words.size && end - start < MAX_COMPOUND_PARTS) {
                if (end > start) {
                    val gap = original.substring(words[end - 1].range.last + 1, words[end].range.first)
                    if (gap.none { it == '-' }) break
                }
                val phrase = original.substring(words[start].range.first, words[end].range.last + 1)
                if (normalizeKey(phrase) in protectedKeys) {
                    for (index in start..end) protected += index
                }
                end++
            }
        }
        return protected
    }

    private fun isStressMarkerAt(token: String, index: Int): Boolean =
        token[index] == PLUS && index + 1 < token.length && token[index + 1] in VOWELS &&
            (index == 0 || !token[index - 1].isLetterOrDigit() || isRussianLetter(token[index - 1]))

    private fun isRussianLetter(c: Char): Boolean =
        c in 'А'..'Я' || c in 'а'..'я' || c == 'Ё' || c == 'ё'

    private fun hasExplicitStressMarker(token: String): Boolean = token.indices.any { i ->
        token[i] == ACUTE || isStressMarkerAt(token, i)
    }

    private fun parse(token: String): ParsedWord {
        val base = StringBuilder(token.length)
        val stressed = LinkedHashSet<Int>()
        val yo = LinkedHashSet<Int>()
        var lastVowel = -1
        var plusPending = false
        for (index in token.indices) {
            val ch = token[index]
            when {
                isStressMarkerAt(token, index) -> plusPending = true
                ch == ACUTE -> if (lastVowel >= 0) stressed += lastVowel
                else -> {
                    val position = base.length
                    base.append(ch)
                    if (ch == 'ё' || ch == 'Ё') yo += position
                    if (ch in VOWELS) {
                        lastVowel = position
                        if (plusPending) stressed += position
                    }
                    plusPending = false
                }
            }
        }
        return ParsedWord(base.toString(), stressed, yo)
    }

    private fun normalizeKey(word: String): String = word
        .filter { it.isLetter() || it == '-' }
        .lowercase(Locale.ROOT)
        .replace('ё', 'е')

    private const val MAX_COMPOUND_PARTS = 8
}


/** Нормализация и защита от ложного выравнивания при удалении неподдерживаемых символов RUAccent. */
internal object RuAccentInputSafety {
    // Matches upstream RUAccent's normalization allow-list; straight apostrophe is intentionally dropped.
    private val allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789\t\n\r \u00A0абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ—.,!?:;\"“”‘’(){}[]«»„-\u0301"

    fun unsafeWordsJoinedByDroppedSeparators(input: String, words: List<IntRange>): Set<Int> {
        val unsafe = HashSet<Int>()
        for (index in 0 until words.lastIndex) {
            val gap = input.substring(words[index].last + 1, words[index + 1].first)
            // Upstream drops unsupported visible characters. If the entire gap disappears,
            // the two fragments become one model token and neither may safely receive a mark.
            if (gap.isNotEmpty() && gap.none { it.isWhitespace() } && gap.all { it !in allowed }) {
                unsafe += index
                unsafe += index + 1
            }
        }
        // A dropped letter/digit/combining mark attached to a word boundary means the model
        // saw only a fragment of the source word. Match RUAccent's _whole_words() edge check.
        for (index in words.indices) {
            val range = words[index]
            if (hasDroppedWordCharAtEdge(input, range.first - 1, step = -1)) unsafe += index
            if (hasDroppedWordCharAtEdge(input, range.last + 1, step = 1)) unsafe += index
        }
        return unsafe
    }

    /** RUAccent's _whole_words() skips dropped Cf format chars before checking the edge. */
    private fun hasDroppedWordCharAtEdge(input: String, start: Int, step: Int): Boolean {
        var position = start
        while (position in input.indices) {
            val char = input[position]
            if (char in allowed) return false
            if (isFormatChar(char) && char != '\u200b') {
                position += step
                continue
            }
            return isAttachedWordChar(char)
        }
        return false
    }

    private fun isFormatChar(char: Char): Boolean = Character.getType(char) == Character.FORMAT.toInt()

    private fun isAttachedWordChar(char: Char): Boolean =
        char.isLetterOrDigit() || Character.getType(char) in setOf(
            Character.NON_SPACING_MARK.toInt(),
            Character.COMBINING_SPACING_MARK.toInt(),
            Character.ENCLOSING_MARK.toInt(),
        )

    /** Replace unsupported characters with same-length spaces so model offsets stay aligned. */
    fun normalizeSameLength(text: String): String = buildString(text.length) {
        for (c in text) {
            val deletedWhitespace = c == '\u000b' || c == '\u000c' || c in '\u001c'..'\u001f' ||
                c == '\u0085' || c == '\u2028' || c == '\u2029'
            append(when {
                deletedWhitespace -> ' '
                c in allowed || c.isWhitespace() -> c
                else -> ' '
            })
        }
    }
}


/**
 * Форматирование диагностики для человека: внутренний маркер "+" превращается в знак ударения,
 * а сравнение показывает только слова, реально отличающиеся от результата штатного RuVoice.
 */
internal object StressDiagnosticFormatter {
    private val wordRegex = Regex("[\\p{L}+\\u0301]+")

    fun readable(text: String): String =
        wordRegex.replace(text) { match -> readableWord(match.value) }

    private fun readableWord(word: String): String {
        val marker = word.indexOf('+')
        if (marker < 0 || marker + 1 >= word.length) return word.replace("+", "")
        return word.substring(0, marker) + word[marker + 1] + '\u0301' +
            word.substring(marker + 2).replace("+", "")
    }

    fun differences(before: String, after: String): List<String> {
        val oldWords = wordRegex.findAll(before).toList()
        val newWords = wordRegex.findAll(after).toList()
        if (oldWords.size != newWords.size) return emptyList()
        return oldWords.indices.mapNotNull { index ->
            val oldWord = oldWords[index].value
            val newWord = newWords[index].value
            if (key(oldWord) != key(newWord)) return@mapNotNull null
            val oldDisplay = readableWord(oldWord)
            val newDisplay = readableWord(newWord)
            if (oldDisplay == newDisplay) null
            else "${plain(oldWord)}: $oldDisplay → $newDisplay"
        }
    }

    private fun plain(word: String): String =
        word.replace("+", "").replace("\u0301", "")

    private fun key(word: String): String =
        plain(word).lowercase(Locale.ROOT).replace('ё', 'е')
}
