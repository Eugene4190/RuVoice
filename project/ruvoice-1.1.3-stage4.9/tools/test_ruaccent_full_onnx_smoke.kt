package ru.kost.ruvoice.text

import java.io.File
import java.nio.file.Files
import java.security.MessageDigest
import org.json.JSONArray
import org.json.JSONObject


private val qualityWordRegex = Regex("[\\p{L}\\u0301]+")
private const val qualityVowels = "аеёиоуыэюя"

private fun qualityPlain(word: String): String =
    word.replace("\u0301", "").lowercase(java.util.Locale.ROOT).replace('ё', 'е')

private fun qualityStressPosition(word: String): Int? {
    val lower = word.lowercase(java.util.Locale.ROOT)
    var vowelIndex = 0
    for (index in lower.indices) {
        if (lower[index] in qualityVowels) {
            if (index + 1 < lower.length && lower[index + 1] == '\u0301') return vowelIndex
            vowelIndex++
        }
    }
    return null
}

private fun qualityYoPositions(word: String): List<Int> =
    word.lowercase(java.util.Locale.ROOT).replace("\u0301", "")
        .mapIndexedNotNull { index, ch -> index.takeIf { ch == 'ё' } }

private data class QualitySummary(
    val name: String,
    val total: Int,
    val passed: Int,
    val skipped: Int,
    val errors: List<String>,
) {
    val percent: Double get() = if (total == 0) 0.0 else passed * 100.0 / total
}

/** RUAccent standalone scoring against the repository's human-labelled homograph corpus. */
private fun evaluateHomographs(corrector: RuAccentOnnxCorrector): QualitySummary {
    val corpusFile = File("app/src/test/resources/homograph_eval/HomographResolutionEval.json")
    check(corpusFile.isFile) { "Missing gold homograph corpus: \${corpusFile.path}" }
    val items = JSONArray(corpusFile.readText(Charsets.UTF_8))
    val errors = ArrayList<String>()
    var total = 0
    var passed = 0
    var skipped = 0
    var unknown = 0
    for (index in 0 until items.length()) {
        val item = items.getJSONObject(index)
        val context = item.getString("context")
        val gold = item.getString("homograph").lowercase(java.util.Locale.ROOT)
        val expectedPosition = qualityStressPosition(gold)
        if (expectedPosition == null) {
            skipped++
            errors += "HOMOGRAPH_GOLD_WITHOUT_STRESS | id=\${item.optInt("id")} | $context | gold=$gold"
            continue
        }
        val sourceWords = qualityWordRegex.findAll(context).map { it.value }.toList()
        val targetIndex = sourceWords.indexOfFirst { qualityPlain(it) == qualityPlain(gold) }
        if (targetIndex < 0) {
            skipped++
            errors += "HOMOGRAPH_TARGET_NOT_FOUND | id=\${item.optInt("id")} | $context | gold=$gold"
            continue
        }
        val prediction = corrector.correct(context)
            ?: error("RUAccent returned null for homograph case \${item.optInt("id")}")
        val predictedWords = qualityWordRegex.findAll(prediction.text).map { it.value }.toList()
        if (predictedWords.size != sourceWords.size || targetIndex >= predictedWords.size) {
            skipped++
            errors += "HOMOGRAPH_ALIGNMENT | id=\${item.optInt("id")} | $context | gold=$gold | output=\${prediction.text}"
            continue
        }
        total++
        val actualWord = predictedWords[targetIndex]
        val actualPosition = qualityStressPosition(actualWord)
        val decision = prediction.decisions.getOrNull(targetIndex)?.name ?: "NO_DECISION"
        if (decision == "UNKNOWN") unknown++
        if (actualPosition == expectedPosition) {
            passed++
        } else {
            errors += "HOMOGRAPH_MISMATCH | id=\${item.optInt("id")} | $context | gold=$gold | predicted=$actualWord | decision=$decision"
        }
    }
    println("QUALITY_HOMOGRAPH total=$total passed=$passed skipped=$skipped unknown=$unknown accuracy=\${"%.2f".format(java.util.Locale.ROOT, passed * 100.0 / maxOf(total, 1))}%")
    return QualitySummary("HomographResolutionEval", total, passed, skipped, errors)
}

/** Score exact restoration of author-written ё after erasing it from the input, as in YoEvalTest. */
private fun evaluateYo(corrector: RuAccentOnnxCorrector): QualitySummary {
    val corpusFile = File("app/src/test/resources/yo_eval/wiki_yo.txt")
    check(corpusFile.isFile) { "Missing gold ё corpus: \${corpusFile.path}" }
    val errors = ArrayList<String>()
    var total = 0
    var restored = 0
    var skipped = 0
    var falseYo = 0
    var lexicalMismatch = 0
    for ((lineIndex, original) in corpusFile.readLines(Charsets.UTF_8).withIndex()) {
        if (original.isBlank()) continue
        val input = original.replace('ё', 'е').replace('Ё', 'Е')
        val prediction = corrector.correct(input)
            ?: error("RUAccent returned null for ё case line \${lineIndex + 1}")
        val originalWords = qualityWordRegex.findAll(original).map { it.value }.toList()
        val predictedWords = qualityWordRegex.findAll(prediction.text).map { it.value }.toList()
        if (originalWords.size != predictedWords.size) {
            skipped++
            errors += "YO_ALIGNMENT | line=\${lineIndex + 1} | $original | output=\${prediction.text}"
            continue
        }
        for (wordIndex in originalWords.indices) {
            val expected = originalWords[wordIndex].lowercase(java.util.Locale.ROOT).replace("\u0301", "")
            val actual = predictedWords[wordIndex].lowercase(java.util.Locale.ROOT).replace("\u0301", "")
            if (qualityPlain(expected) != qualityPlain(actual)) {
                lexicalMismatch++
                continue
            }
            val expectedYo = qualityYoPositions(expected)
            val actualYo = qualityYoPositions(actual)
            if (expectedYo.isNotEmpty()) {
                total++
                if (expectedYo == actualYo) {
                    restored++
                } else {
                    errors += "YO_MISMATCH | line=\${lineIndex + 1} | \${originalWords[wordIndex]} | $actual | $original"
                }
            } else if (actualYo.isNotEmpty()) {
                falseYo++
                errors += "YO_FALSE_POSITIVE | line=\${lineIndex + 1} | \${originalWords[wordIndex]} | $actual | $original"
            }
        }
    }
    println("QUALITY_YO gold_words=$total restored=$restored skipped_sentences=$skipped false_yo=$falseYo lexical_mismatch=$lexicalMismatch recall=\${"%.2f".format(java.util.Locale.ROOT, restored * 100.0 / maxOf(total, 1))}%")
    return QualitySummary("Wikipedia ё restoration", total, restored, skipped, errors)
}

/** Score the independent STRESS/NO_STRESS classifier on the repository's curated context smoke set. */
private fun evaluateStressUsage(corrector: RuAccentOnnxCorrector): QualitySummary {
    val corpusFile = File("tools/data/ruaccent_stress_usage_smoke.json")
    check(corpusFile.isFile) { "Missing stress usage corpus: \${corpusFile.path}" }
    val root = JSONObject(corpusFile.readText(Charsets.UTF_8))
    val cases = root.getJSONArray("cases")
    val errors = ArrayList<String>()
    var total = 0
    var passed = 0
    var skipped = 0
    for (caseIndex in 0 until cases.length()) {
        val item = cases.getJSONObject(caseIndex)
        val text = item.getString("text")
        val words = qualityWordRegex.findAll(text).map { it.value }.toList()
        val prediction = corrector.correct(text)
            ?: error("RUAccent returned null for usage case \${item.getString("id")}")
        val outputWords = qualityWordRegex.findAll(prediction.text).map { it.value }.toList()
        if (words.size != outputWords.size || prediction.decisions.size != words.size) {
            skipped += item.getJSONArray("expect").length()
            errors += "USAGE_ALIGNMENT | \${item.getString("id")} | $text | output=\${prediction.text}"
            continue
        }
        val expectedItems = item.getJSONArray("expect")
        for (expectIndex in 0 until expectedItems.length()) {
            val expected = expectedItems.getJSONObject(expectIndex)
            val target = expected.getString("word")
            val occurrence = expected.optInt("occurrence", 0)
            val indices = words.indices.filter { words[it].equals(target, ignoreCase = true) }
            if (occurrence !in indices.indices) {
                skipped++
                errors += "USAGE_TARGET_NOT_FOUND | \${item.getString("id")} | $target | $text"
                continue
            }
            total++
            val actual = prediction.decisions[indices[occurrence]].name
            val wanted = when (expected.getString("label")) {
                "STRESS" -> "STRESSED"
                "NO_STRESS" -> "UNSTRESSED"
                else -> error("Unsupported gold label in usage smoke corpus")
            }
            if (actual == wanted) passed++
            else errors += "USAGE_MISMATCH | \${item.getString("id")} | $text | $target | expected=$wanted actual=$actual"
        }
    }
    println("QUALITY_STRESS_USAGE total=$total passed=$passed skipped=$skipped accuracy=\${"%.2f".format(java.util.Locale.ROOT, passed * 100.0 / maxOf(total, 1))}%")
    return QualitySummary("STRESS/NO_STRESS smoke", total, passed, skipped, errors)
}

private fun writeQualityReport(summaries: List<QualitySummary>): File {
    val report = File("app/build/reports/ruaccent-quality-report.txt")
    check(report.parentFile?.exists() == true || report.parentFile?.mkdirs() == true) {
        "Cannot create quality report directory"
    }
    report.bufferedWriter(Charsets.UTF_8).use { out ->
        out.appendLine("RUAccent real-model quality evaluation")
        out.appendLine("Model revision: \${RuAccentInt8ModelManifest.revision}")
        out.appendLine("Important: these are standalone RUAccent scores against gold corpora, not a measured delta versus baseline RuVoice.")
        out.appendLine()
        for (summary in summaries) {
            out.appendLine("\${summary.name}: \${summary.passed}/\${summary.total} (\${"%.2f".format(java.util.Locale.ROOT, summary.percent)}%), skipped=\${summary.skipped}")
        }
        out.appendLine()
        out.appendLine("Detailed mismatches:")
        for (summary in summaries) {
            out.appendLine()
            out.appendLine("[\${summary.name}]")
            summary.errors.forEach(out::appendLine)
        }
    }
    return report
}


private fun sha256(file: File): String {
    val digest = MessageDigest.getInstance("SHA-256")
    file.inputStream().buffered().use { input ->
        val buffer = ByteArray(1024 * 1024)
        while (true) {
            val count = input.read(buffer)
            if (count < 0) break
            digest.update(buffer, 0, count)
        }
    }
    return digest.digest().joinToString("") { "%02x".format(it) }
}

fun main() {
    val root = Files.createTempDirectory("ruvoice-ruaccent-real-models").toFile()
    val downloader = RuAccentHttpDownloader(connectTimeoutMillis = 30_000, readTimeoutMillis = 120_000)
    var totalBytes = 0L
    val hashes = linkedMapOf<String, String>()

    try {
        println("Pinned model revision: ${RuAccentInt8ModelManifest.revision}")
        println("Files in manifest: ${RuAccentInt8ModelManifest.files.size}")

        RuAccentInt8ModelManifest.files.forEachIndexed { index, relative ->
            val destination = File(root, relative)
            check(destination.parentFile?.exists() == true || destination.parentFile?.mkdirs() == true) {
                "Cannot create model directory for $relative"
            }
            downloader.download(RuAccentInt8ModelManifest.downloadUrl(relative), destination) { bytes ->
                if (bytes == 0L || bytes % (32L * 1024 * 1024) < 1024 * 1024) {
                    // Progress is deliberately sparse; no token or model data is printed.
                    System.err.print("\rDownloading ${index + 1}/${RuAccentInt8ModelManifest.files.size}: $relative — $bytes bytes")
                }
            }
            check(destination.isFile && destination.length() > 0L) { "Downloaded file is empty: $relative" }
            totalBytes += destination.length()
            hashes[relative] = sha256(destination)
            println("\nOK ${index + 1}/${RuAccentInt8ModelManifest.files.size}: $relative (${destination.length()} bytes, sha256=${hashes.getValue(relative)})")
        }

        check(hashes.keys == RuAccentInt8ModelManifest.files.toSet()) {
            "Not all pinned model files were downloaded"
        }

        println("\nAll 16 files downloaded: $totalBytes bytes")
        val corrector = RuAccentOnnxCorrector(root)
        try {
            check(corrector.warmUp()) {
                "The four ONNX sessions did not complete the local warm-up inference"
            }
            println("PASS: all four ONNX sessions loaded and warm-up inference completed")

            val samples = listOf(
                "Старинный замок стоял на горе, а дверной замок был сломан.",
                "Все пришли, но всё закончилось.",
                "Жёлтый лист лежал у берёзы.",
                "Он долго ходил по лесу и искал белок."
            )
            for ((index, sample) in samples.withIndex()) {
                val prediction = corrector.correct(sample)
                    ?: error("RUAccent returned null for smoke sample ${index + 1}")
                check(prediction.text.isNotEmpty()) { "RUAccent returned empty text for sample ${index + 1}" }
                check(prediction.decisions.size == Regex("[\\p{L}\\u0301]+").findAll(sample).count()) {
                    "Stress decisions do not align with source words in sample ${index + 1}"
                }
                println("INFERENCE ${index + 1}: ${prediction.text}")
            }
            println("PASS: four real Russian sentence inferences completed")

            // Full corpus run: no hand-picked examples and no user/device dependency.
            val summaries = listOf(
                evaluateHomographs(corrector),
                evaluateYo(corrector),
                evaluateStressUsage(corrector),
            )
            val report = writeQualityReport(summaries)
            println("QUALITY_REPORT=${report.absolutePath} bytes=${report.length()}")
        } finally {
            corrector.close()
        }

        println("\nPASS REAL RUACCENT INT8 MODEL SMOKE TEST")
        println("TOTAL_MODEL_BYTES=$totalBytes")
        hashes.forEach { (path, hash) -> println("MODEL_SHA256 $hash  $path") }
    } finally {
        root.deleteRecursively()
    }
}
