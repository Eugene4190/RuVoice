package ru.kost.ruvoice.text

import org.w3c.dom.Node
import java.io.ByteArrayInputStream
import java.io.File
import java.io.StringReader
import java.net.URLDecoder
import java.nio.file.Files
import java.util.Locale
import java.util.zip.ZipFile
import javax.xml.parsers.DocumentBuilderFactory
import org.xml.sax.InputSource
import org.json.JSONArray
import org.json.JSONObject

private const val ACUTE = '\u0301'
private const val VOWELS = "аеёиоуыэюя"
private val wordRegex = Regex("[\\p{L}\\u0301]+")
private val functionWords = setOf(
    "а", "и", "но", "да", "или", "ли", "не", "ни", "бы", "же", "в", "во", "на", "над",
    "под", "с", "со", "к", "ко", "у", "о", "об", "от", "до", "из", "за", "по", "при",
    "для", "без", "через", "перед", "после", "между", "около", "вокруг", "как", "что",
    "чтобы", "если", "когда", "где", "кто", "то", "это", "вот", "там", "тут", "уже"
)
private val reviewHomographs = setOf(
    "замок", "мука", "белки", "орган", "атлас", "плачу", "стоит", "стрелки", "стекла",
    "окна", "руки", "слова", "леса", "берега", "лица", "головы", "воды", "дома", "полка",
    "крепость", "дух", "дали", "села", "село", "поля", "глаза", "ноги", "яйца", "города",
    "средства", "дороги", "чудеса", "трусы", "мосты", "кружки", "лавки", "пары"
)

private data class Paragraph(val chapter: String, val number: Int, val text: String)
private data class Segment(val chapter: String, val paragraph: Int, val part: Int, val text: String)

private fun localName(node: Node): String =
    (node.localName ?: node.nodeName.substringAfter(':')).lowercase(Locale.ROOT)

private fun secureDocument(bytes: ByteArray): org.w3c.dom.Document {
    val factory = DocumentBuilderFactory.newInstance()
    factory.isNamespaceAware = true
    factory.isXIncludeAware = false
    factory.setExpandEntityReferences(false)
    runCatching { factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true) }
    runCatching { factory.setFeature("http://xml.org/sax/features/external-general-entities", false) }
    runCatching { factory.setFeature("http://xml.org/sax/features/external-parameter-entities", false) }
    return factory.newDocumentBuilder().parse(ByteArrayInputStream(bytes))
}

private fun childElements(node: Node): List<Node> {
    val result = ArrayList<Node>()
    val children = node.childNodes
    for (i in 0 until children.length) {
        val child = children.item(i)
        if (child.nodeType == Node.ELEMENT_NODE) result += child
    }
    return result
}

private fun elementsByLocalName(document: org.w3c.dom.Document, wanted: String): List<Node> {
    val result = ArrayList<Node>()
    fun visit(node: Node) {
        if (node.nodeType == Node.ELEMENT_NODE && localName(node) == wanted) result += node
        val children = node.childNodes
        for (i in 0 until children.length) visit(children.item(i))
    }
    visit(document.documentElement)
    return result
}

private fun attribute(node: Node, name: String): String =
    node.attributes?.getNamedItem(name)?.nodeValue.orEmpty()

private fun normalizeZipPath(path: String): String {
    val parts = ArrayDeque<String>()
    for (part in path.replace('\\', '/').split('/')) {
        when (part) {
            "", "." -> Unit
            ".." -> if (parts.isNotEmpty()) parts.removeLast()
            else -> parts.addLast(part)
        }
    }
    return parts.joinToString("/")
}

private fun resolveHref(baseFile: String, href: String): String {
    val raw = href.substringBefore('#').substringBefore('?')
    val decoded = URLDecoder.decode(raw.replace("+", "%2B"), "UTF-8")
    val base = baseFile.substringBeforeLast('/', "")
    return normalizeZipPath(if (base.isEmpty()) decoded else base + "/" + decoded)
}

private fun extractBlocksFromXhtml(bytes: ByteArray): List<String> {
    val doc = secureDocument(bytes)
    val result = ArrayList<String>()
    val current = StringBuilder()
    val blocks = setOf("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "br", "tr", "td", "th")
    val ignored = setOf("head", "script", "style", "svg", "math", "noscript")
    fun flush() {
        val text = current.toString().replace(Regex("\\s+"), " ").trim()
        current.setLength(0)
        val letters = text.count { it.isLetter() }
        val cyrillic = text.count { it in 'а'..'я' || it in 'А'..'Я' || it == 'ё' || it == 'Ё' }
        if (text.length >= 30 && letters >= 20 && cyrillic >= letters * 0.45) result += text
    }
    fun visit(node: Node, inIgnored: Boolean = false) {
        if (node.nodeType == Node.TEXT_NODE || node.nodeType == Node.CDATA_SECTION_NODE) {
            if (!inIgnored) current.append(node.nodeValue).append(' ')
            return
        }
        if (node.nodeType != Node.ELEMENT_NODE && node.nodeType != Node.DOCUMENT_NODE) return
        val tag = if (node.nodeType == Node.ELEMENT_NODE) localName(node) else ""
        val ignore = inIgnored || tag in ignored
        if (tag in blocks) flush()
        val children = node.childNodes
        for (i in 0 until children.length) visit(children.item(i), ignore)
        if (tag in blocks) flush()
    }
    visit(doc.documentElement)
    flush()
    return result
}

private fun epubParagraphs(epub: File): List<Paragraph> {
    ZipFile(epub).use { zip ->
        val container = zip.getEntry("META-INF/container.xml")
            ?: error("В EPUB отсутствует META-INF/container.xml")
        val containerDoc = secureDocument(zip.getInputStream(container).use { it.readBytes() })
        val opfPath = elementsByLocalName(containerDoc, "rootfile").firstOrNull()
            ?.let { attribute(it, "full-path") }
            ?.takeIf { it.isNotBlank() }
            ?: error("В EPUB не найден путь к OPF")
        val opfEntry = zip.getEntry(opfPath) ?: error("Не найден OPF-файл: " + opfPath)
        val opfDoc = secureDocument(zip.getInputStream(opfEntry).use { it.readBytes() })
        val manifest = elementsByLocalName(opfDoc, "item")
            .associateBy({ attribute(it, "id") }, { it })
        val ordered = elementsByLocalName(opfDoc, "itemref").mapNotNull { itemref ->
            val id = attribute(itemref, "idref")
            val item = manifest[id] ?: return@mapNotNull null
            val media = attribute(item, "media-type")
            val href = attribute(item, "href")
            if (media.contains("xhtml") || href.endsWith(".xhtml", true) || href.endsWith(".html", true)) {
                resolveHref(opfPath, href)
            } else null
        }.distinct()
        val fallback = zip.entries().asSequence()
            .map { it.name }
            .filter { (it.endsWith(".xhtml", true) || it.endsWith(".html", true)) && !it.substringAfterLast('/').contains("nav", true) }
            .sorted()
            .toList()
        val chapterFiles = if (ordered.isNotEmpty()) ordered else fallback
        require(chapterFiles.isNotEmpty()) { "В EPUB не найдены XHTML/HTML главы" }

        val paragraphs = ArrayList<Paragraph>()
        var failures = 0
        for ((chapterIndex, path) in chapterFiles.withIndex()) {
            val entry = zip.getEntry(path) ?: continue
            val extracted = try {
                extractBlocksFromXhtml(zip.getInputStream(entry).use { it.readBytes() })
            } catch (error: Throwable) {
                failures++
                emptyList()
            }
            for ((paragraphIndex, text) in extracted.withIndex()) {
                paragraphs += Paragraph(path.substringAfterLast('/'), paragraphIndex + 1, text)
            }
        }
        println("EPUB_SPINE_CHAPTERS=" + chapterFiles.size + " PARAGRAPHS=" + paragraphs.size + " PARSE_FAILURES=" + failures)
        require(paragraphs.isNotEmpty()) { "Не удалось извлечь русские абзацы из EPUB" }
        return paragraphs
    }
}

private fun splitLongSentence(text: String, limit: Int = 320): List<String> {
    if (text.length <= limit) return listOf(text)
    val result = ArrayList<String>()
    var rest = text.trim()
    while (rest.length > limit) {
        var cut = rest.lastIndexOf(' ', limit)
        if (cut < limit / 2) cut = rest.indexOf(' ', limit).takeIf { it in 1..(limit + 80) } ?: limit
        result += rest.substring(0, cut).trim()
        rest = rest.substring(cut).trim()
    }
    if (rest.isNotEmpty()) result += rest
    return result
}

private fun makeSegments(paragraphs: List<Paragraph>): List<Segment> {
    val result = ArrayList<Segment>()
    for (paragraph in paragraphs) {
        val iterator = java.text.BreakIterator.getSentenceInstance(Locale("ru"))
        iterator.setText(paragraph.text)
        var start = iterator.first()
        var part = 0
        while (true) {
            val end = iterator.next()
            if (end == java.text.BreakIterator.DONE) break
            val sentence = paragraph.text.substring(start, end).trim()
            start = end
            if (sentence.length < 25) continue
            for (piece in splitLongSentence(sentence)) {
                if (piece.length < 25) continue
                part++
                result += Segment(paragraph.chapter, paragraph.number, part, piece)
            }
        }
    }
    return result
}

private fun plain(word: String): String =
    word.replace(ACUTE.toString(), "").lowercase(Locale.ROOT)

private fun stressPosition(word: String): Int? {
    var vowelIndex = 0
    val lower = word.lowercase(Locale.ROOT)
    for (index in lower.indices) {
        if (lower[index] in VOWELS) {
            if (index + 1 < lower.length && lower[index + 1] == ACUTE) return vowelIndex
            vowelIndex++
        }
    }
    return null
}

private fun shortContext(text: String, match: MatchResult, radius: Int = 54): String {
    val from = (match.range.first - radius).coerceAtLeast(0)
    val to = (match.range.last + radius + 1).coerceAtMost(text.length)
    return text.substring(from, to).replace(Regex("\\s+"), " ").trim()
}

fun main(args: Array<String>) {
    require(args.size >= 1) { "Usage: <book.epub> [report.json]" }
    val epub = File(args[0]).absoluteFile
    require(epub.isFile && epub.length() > 0) { "EPUB не найден или пуст: " + epub }
    val reportFile = args.getOrNull(1)?.let { File(it).absoluteFile }
    val modelRoot = Files.createTempDirectory("ruvoice-real-book-ruaccent").toFile()
    val downloader = RuAccentHttpDownloader(connectTimeoutMillis = 30_000, readTimeoutMillis = 120_000)

    try {
        println("BOOK_FILE=" + epub.name + " BYTES=" + epub.length())
        println("MODEL_REVISION=" + RuAccentInt8ModelManifest.revision)
        var downloaded = 0L
        for ((index, relative) in RuAccentInt8ModelManifest.files.withIndex()) {
            val destination = File(modelRoot, relative)
            destination.parentFile?.mkdirs()
            downloader.download(RuAccentInt8ModelManifest.downloadUrl(relative), destination) { bytes ->
                if (bytes == 0L) System.err.println("Downloading model " + (index + 1) + "/" + RuAccentInt8ModelManifest.files.size + ": " + relative)
            }
            check(destination.isFile && destination.length() > 0) { "Не скачана модель: " + relative }
            downloaded += destination.length()
        }
        println("MODEL_FILES=" + RuAccentInt8ModelManifest.files.size + " MODEL_BYTES=" + downloaded)

        val paragraphs = epubParagraphs(epub)
        val segments = makeSegments(paragraphs)
        require(segments.isNotEmpty()) { "Не найдены предложения для анализа" }
        println("TEXT_SEGMENTS=" + segments.size)

        val corrector = RuAccentOnnxCorrector(modelRoot)
        try {
            check(corrector.warmUp()) { "RUAccent ONNX warm-up не прошёл" }
            println("ONNX_WARMUP=PASS")

            var words = 0
            var stressed = 0
            var unstressed = 0
            var unknown = 0
            var markedWords = 0
            var newlyMarkedStress = 0
            var changedStress = 0
            var restoredYo = 0
            var keptYo = 0
            var alignmentErrors = 0
            var lexicalChanges = 0
            var functionWordMarked = 0
            var originalYoWords = 0
            var changedSegments = 0
            var segmentsWithNoStress = 0
            val homographSamples = JSONArray()
            val functionSamples = JSONArray()
            val stressSamples = JSONArray()
            val seenHomograph = HashSet<String>()

            for ((segmentIndex, segment) in segments.withIndex()) {
                val prediction = corrector.correct(segment.text)
                    ?: error("RUAccent вернул null на фрагменте " + segmentIndex)
                val sourceWords = wordRegex.findAll(segment.text).toList()
                val outputWords = wordRegex.findAll(prediction.text).toList()
                if (sourceWords.size != outputWords.size || prediction.decisions.size != sourceWords.size) {
                    alignmentErrors++
                    continue
                }
                var segmentChanged = false
                var segmentHasStress = false
                for (wordIndex in sourceWords.indices) {
                    val sourceWord = sourceWords[wordIndex].value
                    val outputWord = outputWords[wordIndex].value
                    val normalizedSource = plain(sourceWord)
                    val normalizedOutput = plain(outputWord)
                    words++
                    when (prediction.decisions.getOrNull(wordIndex) ?: StressDecision.UNKNOWN) {
                        StressDecision.STRESSED -> stressed++
                        StressDecision.UNSTRESSED -> unstressed++
                        StressDecision.UNKNOWN -> unknown++
                    }
                    val sourceStress = stressPosition(sourceWord)
                    val outputStress = stressPosition(outputWord)
                    if (outputStress != null) {
                        markedWords++
                        segmentHasStress = true
                    }
                    if (sourceStress != outputStress) {
                        changedStress++
                        segmentChanged = true
                        if (sourceStress == null && outputStress != null) newlyMarkedStress++
                        if (stressSamples.length() < 30 && outputStress != null) {
                            stressSamples.put(JSONObject()
                                .put("chapter", segment.chapter)
                                .put("paragraph", segment.paragraph)
                                .put("source_word", sourceWord)
                                .put("ruaccent_word", outputWord)
                                .put("context", shortContext(segment.text, sourceWords[wordIndex], 40)))
                        }
                    }
                    if (normalizedSource.replace('ё', 'е') == normalizedOutput.replace('ё', 'е') && sourceWord.lowercase(Locale.ROOT).contains('е') &&
                        outputWord.lowercase(Locale.ROOT).contains('ё') &&
                        sourceWord.lowercase(Locale.ROOT) != outputWord.lowercase(Locale.ROOT)) {
                        restoredYo++
                        segmentChanged = true
                    }
                    if (sourceWord.lowercase(Locale.ROOT).contains('ё')) originalYoWords++
                    val yoDecision = prediction.yoDecisions.getOrNull(wordIndex)
                    if (yoDecision == YoDecision.KEEP_E) keptYo++

                    if (normalizedSource.replace('ё', 'е') != normalizedOutput.replace('ё', 'е')) {
                        // A spelling change other than е/ё violates the corrector contract.
                        lexicalChanges++
                        if (homographSamples.length() < 5) {
                            homographSamples.put(JSONObject().put("type", "LEXICAL_ALIGNMENT")
                                .put("chapter", segment.chapter).put("source_word", sourceWord).put("output_word", outputWord))
                        }
                    }
                    if (normalizedOutput in functionWords && outputStress != null) {
                        functionWordMarked++
                        if (functionSamples.length() < 25) {
                            functionSamples.put(JSONObject()
                                .put("chapter", segment.chapter)
                                .put("source_word", sourceWord)
                                .put("ruaccent_word", outputWord)
                                .put("context", shortContext(segment.text, sourceWords[wordIndex], 40)))
                        }
                    }
                    if (normalizedSource in reviewHomographs && homographSamples.length() < 50) {
                        val key = normalizedSource + ":" + segment.chapter + ":" + segment.paragraph
                        if (seenHomograph.add(key)) {
                            homographSamples.put(JSONObject()
                                .put("type", "HOMOGRAPH_REVIEW")
                                .put("chapter", segment.chapter)
                                .put("paragraph", segment.paragraph)
                                .put("source_word", sourceWord)
                                .put("ruaccent_word", outputWord)
                                .put("decision", prediction.decisions.getOrNull(wordIndex)?.name ?: "UNKNOWN")
                                .put("context", shortContext(segment.text, sourceWords[wordIndex], 50)))
                        }
                    }
                }
                if (segmentChanged) changedSegments++
                if (!segmentHasStress) segmentsWithNoStress++
            }

            val summary = JSONObject()
                .put("book_file", epub.name)
                .put("model_revision", RuAccentInt8ModelManifest.revision)
                .put("model_files", RuAccentInt8ModelManifest.files.size)
                .put("model_bytes", downloaded)
                .put("paragraphs", paragraphs.size)
                .put("segments", segments.size)
                .put("words", words)
                .put("decisions_stressed", stressed)
                .put("decisions_unstressed", unstressed)
                .put("decisions_unknown", unknown)
                .put("words_with_acute_in_ruaccent_output", markedWords)
                .put("new_stress_marks_vs_unmarked_book", newlyMarkedStress)
                .put("stress_position_changes_vs_source", changedStress)
                .put("restored_yo_words", restoredYo)
                .put("kept_e_decisions", keptYo)
                .put("original_yo_words_seen", originalYoWords)
                .put("function_words_with_stress", functionWordMarked)
                .put("segments_changed", changedSegments)
                .put("segments_without_stress_mark", segmentsWithNoStress)
                .put("alignment_errors", alignmentErrors)
                .put("lexical_changes_other_than_yo", lexicalChanges)
                .put("accuracy_claim", "NOT_MEASURED: EPUB has no gold stress annotation; these are model outputs, not verified corrections.")
                .put("homograph_review_samples", homographSamples)
                .put("function_word_stress_samples", functionSamples)
                .put("stress_assignment_samples", stressSamples)

            if (reportFile != null) {
                reportFile.parentFile?.mkdirs()
                reportFile.writeText(summary.toString(2), Charsets.UTF_8)
                println("REPORT_FILE=" + reportFile.path + " REPORT_BYTES=" + reportFile.length())
            }

            println("BOOK_EVAL_SUMMARY paragraphs=" + paragraphs.size +
                " segments=" + segments.size + " words=" + words +
                " stressed=" + stressed + " unstressed=" + unstressed + " unknown=" + unknown)
            println("BOOK_EVAL_OUTPUT marked_words=" + markedWords +
                " new_stress_marks=" + newlyMarkedStress + " stress_position_changes=" + changedStress +
                " restored_yo=" + restoredYo + " kept_e_decisions=" + keptYo)
            println("BOOK_EVAL_SAFETY function_words_with_stress=" + functionWordMarked +
                " changed_segments=" + changedSegments + " segments_without_stress=" + segmentsWithNoStress +
                " alignment_errors=" + alignmentErrors + " lexical_changes=" + lexicalChanges)
            println("BOOK_EVAL_ACCURACY=NOT_MEASURED (нет эталонных ударений в EPUB)")
            println("BOOK_EVAL_HOMOGRAPH_SAMPLES_BEGIN")
            for (i in 0 until homographSamples.length()) {
                val item = homographSamples.getJSONObject(i)
                if (item.optString("type") == "HOMOGRAPH_REVIEW") {
                    println(item.optString("chapter") + " | " + item.optString("source_word") + " -> " +
                        item.optString("ruaccent_word") + " | " + item.optString("decision") + " | " +
                        item.optString("context"))
                }
            }
            println("BOOK_EVAL_HOMOGRAPH_SAMPLES_END")
            println("BOOK_EVAL_FUNCTION_WORD_SAMPLES_BEGIN")
            for (i in 0 until functionSamples.length()) {
                val item = functionSamples.getJSONObject(i)
                println(item.optString("chapter") + " | " + item.optString("source_word") + " -> " +
                    item.optString("ruaccent_word") + " | " + item.optString("context"))
            }
            println("BOOK_EVAL_FUNCTION_WORD_SAMPLES_END")
            check(alignmentErrors == 0 && lexicalChanges == 0) {
                "Ошибки контракта корректора: alignment=" + alignmentErrors + ", lexical_changes=" + lexicalChanges
            }
        } finally {
            corrector.close()
        }
    } finally {
        modelRoot.deleteRecursively()
    }
}
