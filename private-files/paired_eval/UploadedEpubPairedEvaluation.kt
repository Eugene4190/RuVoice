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
import javax.swing.text.MutableAttributeSet
import javax.swing.text.html.HTML
import javax.swing.text.html.HTMLEditorKit
import javax.swing.text.html.parser.ParserDelegator
import org.xml.sax.InputSource
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Test
import java.nio.ByteBuffer
import ru.kost.ruvoice.Pipeline
import ru.kost.ruvoice.SileroData
import ru.kost.ruvoice.bin.StressBin

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
    runCatching { factory.setFeature("http://apache.org/xml/features/nonvalidating/load-external-dtd", false) }
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
    val doc = try {
        secureDocument(bytes)
    } catch (_: Throwable) {
        // Some commercial EPUBs use HTML named entities or a legacy XHTML doctype.
        // Fall back to the JDK HTML parser without fetching external DTDs.
        val fallback = ArrayList<String>()
        val current = StringBuilder()
        val blockTags = setOf("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "br", "div", "section", "article")
        fun flushFallback() {
            val text = current.toString().replace(Regex("\\s+"), " ").trim()
            current.setLength(0)
            val letters = text.count { it.isLetter() }
            val cyrillic = text.count { it in 'а'..'я' || it in 'А'..'Я' || it == 'ё' || it == 'Ё' }
            if (text.length >= 3 && letters >= 2 && cyrillic >= letters * 0.45) fallback += text
        }
        val callback = object : HTMLEditorKit.ParserCallback() {
            override fun handleText(data: CharArray, pos: Int) {
                current.append(data).append(' ')
            }
            override fun handleStartTag(t: HTML.Tag, a: MutableAttributeSet, pos: Int) {
                if (t.toString().lowercase(Locale.ROOT) in blockTags) flushFallback()
            }
            override fun handleEndTag(t: HTML.Tag, pos: Int) {
                if (t.toString().lowercase(Locale.ROOT) in blockTags) flushFallback()
            }
            override fun handleSimpleTag(t: HTML.Tag, a: MutableAttributeSet, pos: Int) {
                if (t.toString().lowercase(Locale.ROOT) == "br") flushFallback()
            }
        }
        ParserDelegator().parse(StringReader(String(bytes, Charsets.UTF_8)), callback, true)
        flushFallback()
        return fallback
    }
    val result = ArrayList<String>()
    val current = StringBuilder()
    val blocks = setOf("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "br", "tr", "td", "th", "div", "section", "article")
    val ignored = setOf("head", "script", "style", "svg", "math", "noscript")
    fun flush() {
        val text = current.toString().replace(Regex("\\s+"), " ").trim()
        current.setLength(0)
        val letters = text.count { it.isLetter() }
        val cyrillic = text.count { it in 'а'..'я' || it in 'А'..'Я' || it == 'ё' || it == 'Ё' }
        if (text.length >= 3 && letters >= 2 && cyrillic >= letters * 0.45) result += text
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
            if (sentence.length < 3 || sentence.count { it.isLetter() } < 2) continue
            for (piece in splitLongSentence(sentence)) {
                if (piece.length < 3 || piece.count { it.isLetter() } < 2) continue
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


/** Persistent bridge to the official TorchScript-Lite Silero accentor and homograph model. */
private class PairedTorchLiteStressModels(
    accentorFile: File,
    homoFile: File,
    bridgeScript: File,
) : StressModels, AutoCloseable {
    private val process = ProcessBuilder(
        "python3", bridgeScript.absolutePath, accentorFile.absolutePath, homoFile.absolutePath
    ).redirectError(ProcessBuilder.Redirect.INHERIT).start()
    private val writer = process.outputStream.bufferedWriter(Charsets.UTF_8)
    private val reader = process.inputStream.bufferedReader(Charsets.UTF_8)
    private val accentCache = HashMap<String, Pair<Array<FloatArray>, Array<FloatArray>>>()
    private val homoCache = HashMap<String, FloatArray>()

    init {
        val ready = reader.readLine() ?: error("Torch Lite bridge exited before ready")
        check(JSONObject(ready).optBoolean("ready")) { "Torch Lite bridge did not become ready: " + ready }
    }

    @Synchronized
    private fun request(value: JSONObject): JSONObject {
        check(process.isAlive) { "Torch Lite bridge is not running" }
        writer.write(value.toString())
        writer.newLine()
        writer.flush()
        val line = reader.readLine() ?: error("Torch Lite bridge closed stdout")
        val result = JSONObject(line)
        if (result.has("error")) error(result.getString("error"))
        return result
    }

    @Synchronized
    override fun accentor(words: List<String>): Pair<Array<FloatArray>, Array<FloatArray>> {
        val key = JSONArray(words).toString()
        accentCache[key]?.let { return it }
        val response = request(JSONObject().put("op", "accentor").put("words", JSONArray(words)))
        val stress = response.getJSONArray("stress")
        val yo = response.getJSONArray("yo")
        val result = Pair(
            Array(stress.length()) { i ->
                val row = stress.getJSONArray(i)
                FloatArray(row.length()) { j -> row.getDouble(j).toFloat() }
            },
            Array(words.size) { i ->
                val row = yo.optJSONArray(i) ?: JSONArray()
                FloatArray(row.length()) { j -> row.getDouble(j).toFloat() }
            }
        )
        accentCache[key] = result
        return result
    }

    @Synchronized
    override fun homo(ids: List<LongArray>, starts: LongArray, ends: LongArray): FloatArray {
        val idJson = JSONArray()
        ids.forEach { row ->
            val values = JSONArray()
            row.forEach { values.put(it) }
            idJson.put(values)
        }
        val startJson = JSONArray().also { array -> starts.forEach { array.put(it) } }
        val endJson = JSONArray().also { array -> ends.forEach { array.put(it) } }
        val key = JSONObject().put("ids", idJson).put("starts", startJson).put("ends", endJson).toString()
        homoCache[key]?.let { return it }
        val response = request(JSONObject().put("op", "homo").put("ids", idJson).put("starts", startJson).put("ends", endJson))
        val values = response.getJSONArray("probabilities")
        val result = FloatArray(values.length()) { values.getDouble(it).toFloat() }
        homoCache[key] = result
        return result
    }

    override fun close() {
        runCatching {
            writer.write(JSONObject().put("op", "quit").toString())
            writer.newLine()
            writer.flush()
        }
        runCatching { writer.close() }
        runCatching { reader.close() }
        if (!process.waitFor(20, java.util.concurrent.TimeUnit.SECONDS)) process.destroyForcibly()
    }
}

/** Remote production Kotlin/ONNX inference; the bridge uses the desktop ONNX Runtime, not Android JNI. */
private class PairedRemoteRuAccentCorrector(
    modelDirectory: File,
    bridgeClasspath: String,
    nativeDirectory: String,
) : IndependentStressCorrector, AutoCloseable {
    private val process = ProcessBuilder(
        "java", "-Xmx4g", "-Djava.library.path=" + nativeDirectory, "-cp", bridgeClasspath,
        "ru.kost.ruvoice.text.RuAccentBridgeKt", modelDirectory.absolutePath
    ).redirectError(ProcessBuilder.Redirect.INHERIT).start()
    private val writer = process.outputStream.bufferedWriter(Charsets.UTF_8)
    private val reader = process.inputStream.bufferedReader(Charsets.UTF_8)
    var calls = 0
        private set
    var stressed = 0
        private set
    var unstressed = 0
        private set
    var unknown = 0
        private set

    init {
        val ready = reader.readLine() ?: error("RUAccent bridge exited before ready")
        check(JSONObject(ready).optBoolean("ready")) { "RUAccent bridge did not become ready: " + ready }
    }

    @Synchronized
    override fun correct(sentence: String): IndependentStressPrediction? {
        check(process.isAlive) { "RUAccent bridge is not running" }
        writer.write(JSONObject().put("text", sentence).toString())
        writer.newLine()
        writer.flush()
        val line = reader.readLine() ?: error("RUAccent bridge closed stdout")
        val response = JSONObject(line)
        val decisionArray = response.getJSONArray("decisions")
        val yoArray = response.getJSONArray("yo_decisions")
        val decisions = List(decisionArray.length()) { StressDecision.valueOf(decisionArray.getString(it)) }
        val yo = List(yoArray.length()) { YoDecision.valueOf(yoArray.getString(it)) }
        calls++
        decisions.forEach {
            when (it) {
                StressDecision.STRESSED -> stressed++
                StressDecision.UNSTRESSED -> unstressed++
                StressDecision.UNKNOWN -> unknown++
            }
        }
        return IndependentStressPrediction(response.getString("text"), decisions, yo)
    }

    override fun close() {
        runCatching {
            writer.write(JSONObject().put("op", "quit").toString())
            writer.newLine()
            writer.flush()
        }
        runCatching { writer.close() }
        runCatching { reader.close() }
        if (!process.waitFor(20, java.util.concurrent.TimeUnit.SECONDS)) process.destroyForcibly()
    }
}

class UploadedEpubPairedEvaluationTest {
    @Test
    fun compareOriginalRuVoiceWithRuAccentMergedAcrossTheWholeBook() {
        val projectDir = File(checkNotNull(System.getenv("RUVOICE_PROJECT_DIR"))).canonicalFile
        val epub = File(checkNotNull(System.getenv("RUVOICE_BOOK_PATH"))).canonicalFile
        val reportFile = File(checkNotNull(System.getenv("RUVOICE_REPORT_PATH"))).canonicalFile
        val sileroDir = File(checkNotNull(System.getenv("RUVOICE_SILERO_ASSETS"))).canonicalFile
        val bridgeScript = File(checkNotNull(System.getenv("RUVOICE_TORCH_BRIDGE"))).canonicalFile
        val bridgeClasspath = checkNotNull(System.getenv("RUACCENT_BRIDGE_CLASSPATH"))
        val nativeDir = checkNotNull(System.getenv("RUACCENT_NATIVE_DIR"))

        require(epub.isFile && epub.length() > 0L) { "Uploaded EPUB is missing" }
        require(File(projectDir, "app/src/main/assets/morph.bin").isFile) { "morph.bin is missing" }
        require(File(sileroDir, "accentor.ptl").isFile && File(sileroDir, "homo.ptl").isFile) {
            "Official Silero stress models are missing"
        }

        val modelRoot = Files.createTempDirectory("ruvoice-paired-ruaccent").toFile()
        val downloader = RuAccentHttpDownloader(connectTimeoutMillis = 30_000, readTimeoutMillis = 120_000)
        var downloaded = 0L
        for ((index, relative) in RuAccentInt8ModelManifest.files.withIndex()) {
            val destination = File(modelRoot, relative)
            destination.parentFile?.mkdirs()
            downloader.download(RuAccentInt8ModelManifest.downloadUrl(relative), destination) { bytes ->
                if (bytes == 0L) println("RUAccent model " + (index + 1) + "/" + RuAccentInt8ModelManifest.files.size + ": " + relative)
            }
            check(destination.isFile && destination.length() > 0L) { "RUAccent model download failed: " + relative }
            downloaded += destination.length()
        }

        val json = File(projectDir, "app/src/main/assets/silero/silero_ru.json").readText(Charsets.UTF_8)
        val yoLines = File(projectDir, "app/src/main/assets/eyo_safe.txt").readLines(Charsets.UTF_8).asSequence()
        val data = SileroData(StressBin.File(ByteBuffer.wrap(StressBin.write(json, yoLines))))
        val morph = Morph.open(File(projectDir, "app/src/main/assets/morph.bin"))
        val yo = YoDict(data.yo)
        val hardE = HardE(File(projectDir, "app/src/main/assets/hard_e.txt").readLines(Charsets.UTF_8))
        Normalizer.morph = morph
        YoDict.shared = yo
        HardE.shared = hardE

        val rules = Rules()
        val torchModels = PairedTorchLiteStressModels(
            File(sileroDir, "accentor.ptl"), File(sileroDir, "homo.ptl"), bridgeScript
        )
        val baselineStress = Stress(data, torchModels, morph = morph, yo = yo, hardE = hardE)
        val corrector = PairedRemoteRuAccentCorrector(modelRoot, bridgeClasspath, nativeDir)
        val combinedStress = Stress(
            data, torchModels, morph = morph, yo = yo, hardE = hardE,
            independentCorrector = corrector
        )

        try {
            fun readable(text: String, stress: Stress): String =
                StressDiagnosticFormatter.readable(Pipeline.accent(text, data, stress, data.allowed, rules))
            val sanity = JSONObject()
            val genitiveHouse = readable("строительство дома", baselineStress)
            val genitiveEye = readable("отражается от глаза", baselineStress)
            val handsBaseline = readable("дать разуму в руки инструмент", baselineStress)
            val handsCombined = readable("дать разуму в руки инструмент", combinedStress)
            sanity.put("строительство дома", genitiveHouse)
            sanity.put("отражается от глаза", genitiveEye)
            sanity.put("дать разуму в руки инструмент_baseline", handsBaseline)
            sanity.put("дать разуму в руки инструмент_combined", handsCombined)
            check(genitiveHouse.contains("до́ма")) { "Genitive singular дома: " + genitiveHouse }
            check(genitiveEye.contains("гла́за")) { "Genitive singular глаза: " + genitiveEye }
            check(handsBaseline.contains("ру́ки")) { "Native pipeline «в ру́ки»: " + handsBaseline }
            check(handsCombined.contains("ру́ки")) { "RUAccent overwrote «в ру́ки»: " + handsCombined }

            val paragraphs = epubParagraphs(epub)
            val segments = makeSegments(paragraphs)
            require(segments.isNotEmpty()) { "No text segments extracted from EPUB" }
            var wordCount = 0
            var baselineMarked = 0
            var combinedMarked = 0
            var changedSegments = 0
            var changedTokens = 0
            var stressChanges = 0
            var stressAdded = 0
            var stressRemoved = 0
            var stressMoved = 0
            var yoChanges = 0
            var lexicalMismatches = 0
            var alignmentMismatches = 0
            val changeRows = JSONArray()

            for ((segmentIndex, segment) in segments.withIndex()) {
                val baseline = StressDiagnosticFormatter.readable(
                    Pipeline.accent(segment.text, data, baselineStress, data.allowed, rules)
                )
                val combined = StressDiagnosticFormatter.readable(
                    Pipeline.accent(segment.text, data, combinedStress, data.allowed, rules)
                )
                val oldWords = wordRegex.findAll(baseline).toList()
                val newWords = wordRegex.findAll(combined).toList()
                if (oldWords.size != newWords.size) {
                    alignmentMismatches++
                    continue
                }
                var segmentChanged = false
                wordCount += oldWords.size
                for (wordIndex in oldWords.indices) {
                    val before = oldWords[wordIndex].value
                    val after = newWords[wordIndex].value
                    val beforePlain = plain(before)
                    val afterPlain = plain(after)
                    val beforeCanonical = beforePlain.replace('ё', 'е')
                    val afterCanonical = afterPlain.replace('ё', 'е')
                    val beforeStress = stressPosition(before)
                    val afterStress = stressPosition(after)
                    if (beforeStress != null) baselineMarked++
                    if (afterStress != null) combinedMarked++
                    if (beforeCanonical != afterCanonical) {
                        lexicalMismatches++
                        changedTokens++
                        segmentChanged = true
                        if (changeRows.length() < 5000) {
                            changeRows.put(JSONObject()
                                .put("type", "TOKEN_ALIGNMENT_OR_LEXICAL_CHANGE")
                                .put("chapter", segment.chapter)
                                .put("paragraph", segment.paragraph)
                                .put("part", segment.part)
                                .put("before", before)
                                .put("after", after)
                                .put("context", segment.text.take(500)))
                        }
                        continue
                    }
                    val stressChanged = beforeStress != afterStress
                    val yoChanged = ('ё' in beforePlain) != ('ё' in afterPlain)
                    if (!stressChanged && !yoChanged) continue
                    changedTokens++
                    segmentChanged = true
                    if (stressChanged) {
                        stressChanges++
                        when {
                            beforeStress == null && afterStress != null -> stressAdded++
                            beforeStress != null && afterStress == null -> stressRemoved++
                            else -> stressMoved++
                        }
                    }
                    if (yoChanged) yoChanges++
                    if (changeRows.length() < 5000) {
                        changeRows.put(JSONObject()
                            .put("type", when {
                                stressChanged && yoChanged -> "STRESS_AND_YO"
                                stressChanged -> "STRESS"
                                else -> "YO"
                            })
                            .put("chapter", segment.chapter)
                            .put("paragraph", segment.paragraph)
                            .put("part", segment.part)
                            .put("word_index", wordIndex)
                            .put("before", before)
                            .put("after", after)
                            .put("stress_before_vowel_index", beforeStress ?: JSONObject.NULL)
                            .put("stress_after_vowel_index", afterStress ?: JSONObject.NULL)
                            .put("context", segment.text.take(500)))
                    }
                }
                if (segmentChanged) changedSegments++
                if ((segmentIndex + 1) % 500 == 0) {
                    println("PAIRED_PROGRESS segments=" + (segmentIndex + 1) + "/" + segments.size + " changed=" + changedSegments)
                }
            }

            val summary = JSONObject()
                .put("book_file", epub.name)
                .put("model_revision", RuAccentInt8ModelManifest.revision)
                .put("ruaccent_model_files", RuAccentInt8ModelManifest.files.size)
                .put("ruaccent_model_bytes", downloaded)
                .put("silero_models", "Official RuVoice 1.1.3 accentor.ptl and homo.ptl; pack ru_voices uses the shared Russian stress models")
                .put("pipeline", "Production Pipeline.accent + Stress; baseline without independentCorrector; merged result with production RUAccent ONNX and current protected gram/BERT merge")
                .put("paragraphs", paragraphs.size)
                .put("segments", segments.size)
                .put("words_compared", wordCount)
                .put("baseline_words_with_stress", baselineMarked)
                .put("combined_words_with_stress", combinedMarked)
                .put("segments_changed", changedSegments)
                .put("tokens_changed", changedTokens)
                .put("stress_position_changes", stressChanges)
                .put("stress_marks_added", stressAdded)
                .put("stress_marks_removed", stressRemoved)
                .put("stress_marks_moved", stressMoved)
                .put("yo_word_changes", yoChanges)
                .put("lexical_or_alignment_mismatches", lexicalMismatches)
                .put("segment_alignment_mismatches", alignmentMismatches)
                .put("ruaccent_sentences_called", corrector.calls)
                .put("ruaccent_decisions_stressed", corrector.stressed)
                .put("ruaccent_decisions_unstressed", corrector.unstressed)
                .put("ruaccent_decisions_unknown", corrector.unknown)
                .put("sanity_examples", sanity)
                .put("accuracy_claim", "NOT_MEASURED: this is a paired output comparison; the EPUB has no gold stress annotations, so changes are not automatically labelled corrections.")
                .put("changes", changeRows)

            reportFile.parentFile?.mkdirs()
            reportFile.writeText(summary.toString(2), Charsets.UTF_8)
            println("PAIRED_BOOK_SUMMARY segments=" + segments.size +
                " words=" + wordCount + " changed_segments=" + changedSegments + " changed_tokens=" + changedTokens +
                " stress_changes=" + stressChanges + " added=" + stressAdded + " removed=" + stressRemoved +
                " moved=" + stressMoved + " yo_changes=" + yoChanges)
            println("PAIRED_BOOK_SAFETY lexical_mismatches=" + lexicalMismatches + " alignment_mismatches=" + alignmentMismatches)
            println("PAIRED_BOOK_ACCURACY=NOT_MEASURED")
            println("PAIRED_BOOK_REPORT=" + reportFile.absolutePath + " bytes=" + reportFile.length())
        } finally {
            corrector.close()
            torchModels.close()
            modelRoot.deleteRecursively()
        }
    }
}
