package ru.kost.ruvoice.text

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.nio.file.Files
import java.security.MessageDigest
import java.util.Locale

private const val ACUTE = '\u0301'
private val WORD_RE = Regex("[\\p{L}\\u0301]+")

private data class WordResult(
    val word: String,
    val total: Int = 0,
    val correct: Int = 0,
    val noMark: Int = 0,
)

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

private fun plain(word: String): String =
    word.replace(ACUTE.toString(), "").lowercase(Locale.ROOT).replace('ё', 'е').removeSuffix("ъ")

/** The reference corpus writes the acute after the stressed vowel: "замо́к". */
private fun markedVowelIndex(word: String): Int {
    // Match the existing RuVoice homograph evaluator: use the first explicit acute mark.
    val marker = word.indexOf(ACUTE)
    return if (marker < 1) -1 else marker - 1
}

private fun evaluateHomographs(
    corrector: RuAccentOnnxCorrector,
    corpusFile: File,
    baselineFile: File,
): JSONObject {
    val items = JSONArray(corpusFile.readText(Charsets.UTF_8))
    require(items.length() > 0) { "Homograph gold corpus is empty" }
    val baselinePayload = JSONObject(baselineFile.readText(Charsets.UTF_8))
    require(baselinePayload.optInt("schema_version") == 1) { "Stock baseline report schema is unsupported" }
    val baselineById = HashMap<Int, JSONObject>()
    val baselineRows = baselinePayload.getJSONArray("results")
    for (index in 0 until baselineRows.length()) {
        val row = baselineRows.getJSONObject(index)
        baselineById[row.getInt("id")] = row
    }

    var correct = 0
    var noMark = 0
    var wrongPosition = 0
    var missingTarget = 0
    var skippedPhraseTargets = 0
    var alignmentErrors = 0
    var stockCorrect = 0
    var combinedCorrect = 0
    var combinedWins = 0
    var combinedRegressions = 0
    var combinedChanges = 0
    var baselineMissing = 0
    val byWord = LinkedHashMap<String, IntArray>()
    val misses = JSONArray()

    val started = System.nanoTime()
    for (itemIndex in 0 until items.length()) {
        val item = items.getJSONObject(itemIndex)
        val context = item.getString("context")
        val gold = item.getString("homograph")
        val goldWord = gold.replace(ACUTE.toString(), "")
        // Existing HomographEvalTest/homo_eval.py score only one target word, not gold phrases.
        if (goldWord.any { it.isWhitespace() }) {
            skippedPhraseTargets++
            continue
        }
        val goldPosition = markedVowelIndex(gold)
        require(goldPosition >= 0) {
            "Gold item ${item.optString("id")} has no acute mark: $gold"
        }

        val sourceTokens = WORD_RE.findAll(context).map { it.value }.toList()
        val candidates = sourceTokens.indices.filter { plain(sourceTokens[it]) == plain(goldWord) }
        if (candidates.isEmpty()) {
            missingTarget++
            continue
        }
        val occurrence = item.optInt("occurrence", 0).coerceAtLeast(0)
        val sourceIndex = candidates[minOf(occurrence, candidates.lastIndex)]

        val prediction = corrector.correct(context)
            ?: error("RUAccent returned null for gold item ${item.optString("id")}")
        val predictedTokens = WORD_RE.findAll(prediction.text).map { it.value }.toList()
        if (predictedTokens.size != sourceTokens.size ||
            prediction.decisions.size != sourceTokens.size ||
            prediction.yoDecisions.size != sourceTokens.size
        ) {
            alignmentErrors++
            val row = JSONObject()
                .put("id", item.optInt("id"))
                .put("context", context)
                .put("expected", gold)
                .put("actual", "ALIGNMENT_ERROR")
                .put("source_tokens", sourceTokens.size)
                .put("predicted_tokens", predictedTokens.size)
                .put("decisions", prediction.decisions.size)
            if (misses.length() < 100) misses.put(row)
            continue
        }

        val row = baselineById[item.getInt("id")]
        if (row == null) {
            baselineMissing++
            error("Stock baseline has no scored row for gold item ${item.getInt("id")}")
        }
        val stockVariant = row.getString("stock")
        val stockPosition = stockVariant.indexOf('+')
        require(plain(stockVariant.replace("+", "")) == plain(goldWord)) {
            "Stock baseline word alignment failed for item ${item.getInt("id")}: $stockVariant vs $goldWord"
        }

        val observed = predictedTokens[sourceIndex]
        val predictedPosition = markedVowelIndex(observed)
        val decision = prediction.decisions[sourceIndex]
        val sourceHasExplicitStress = ACUTE in sourceTokens[sourceIndex] || '+' in sourceTokens[sourceIndex]
        val combinedPosition = when {
            sourceHasExplicitStress -> stockPosition
            decision == StressDecision.STRESSED -> predictedPosition.takeIf { it >= 0 } ?: stockPosition
            decision == StressDecision.UNSTRESSED -> -1
            else -> stockPosition
        }
        val stockOk = stockPosition == goldPosition
        val combinedOk = combinedPosition == goldPosition
        if (stockOk) stockCorrect++
        if (combinedOk) combinedCorrect++
        if (!stockOk && combinedOk) combinedWins++
        if (stockOk && !combinedOk) combinedRegressions++
        if (combinedPosition != stockPosition) combinedChanges++

        val key = plain(goldWord)
        val stat = byWord.getOrPut(key) { intArrayOf(0, 0, 0) }
        stat[0]++
        val decision = prediction.decisions[sourceIndex].name

        if (predictedPosition == goldPosition) {
            correct++
            stat[1]++
        } else {
            if (predictedPosition < 0) {
                noMark++
                stat[2]++
            } else {
                wrongPosition++
            }
            if (misses.length() < 100) {
                misses.put(
                    JSONObject()
                        .put("id", item.optInt("id"))
                        .put("word", goldWord)
                        .put("context", context)
                        .put("expected", gold)
                        .put("stock", stockVariant)
                        .put("actual_ruaccent", observed)
                        .put("combined_position", combinedPosition)
                        .put("decision", decision.name)
                        .put("combined_correct", combinedOk)
                )
            }
        }

        if ((itemIndex + 1) % 100 == 0) {
            println("HOMOGRAPH_PROGRESS=${itemIndex + 1}/${items.length()}")
        }
    }

    val elapsedMs = (System.nanoTime() - started) / 1_000_000
    val evaluated = items.length() - missingTarget - skippedPhraseTargets
    val coverage = if (evaluated == 0) 0.0 else (evaluated - noMark - alignmentErrors).toDouble() / evaluated
    val report = JSONObject()
        .put("corpus", corpusFile.name)
        .put("source_note", "HomographResolutionEval gold-labelled contexts; one target homograph per sentence.")
        .put("items_total", items.length())
        .put("items_scored", evaluated)
        .put("ruaccent_alone_correct", correct)
        .put("wrong_stress_position", wrongPosition)
        .put("no_stress_mark", noMark)
        .put("stock_ruvoice_correct", stockCorrect)
        .put("combined_ruvoice_plus_ruaccent_correct", combinedCorrect)
        .put("combined_wins_over_stock", combinedWins)
        .put("combined_regressions_vs_stock", combinedRegressions)
        .put("combined_changed_target", combinedChanges)
        .put("combined_net_gain", combinedWins - combinedRegressions)
        .put("stock_accuracy", if (evaluated == 0) 0.0 else stockCorrect.toDouble() / evaluated)
        .put("combined_accuracy", if (evaluated == 0) 0.0 else combinedCorrect.toDouble() / evaluated)
        .put("ruaccent_alone_accuracy", if (evaluated == 0) 0.0 else correct.toDouble() / evaluated)
        .put("missing_target", missingTarget)
        .put("skipped_phrase_targets", skippedPhraseTargets)
        .put("alignment_errors", alignmentErrors)
        .put("baseline_missing", baselineMissing)
        .put("stress_mark_coverage", coverage)
        .put("elapsed_ms", elapsedMs)
        .put("misses", misses)

    val wordArray = JSONArray()
    byWord.entries
        .map { (word, stats) -> word to stats }
        .sortedWith(compareByDescending<Pair<String, IntArray>> { it.second[0] - it.second[1] }
            .thenByDescending { it.second[0] })
        .take(40)
        .forEach { (word, stats) ->
            wordArray.put(
                JSONObject()
                    .put("word", word)
                    .put("total", stats[0])
                    .put("correct", stats[1])
                    .put("no_mark", stats[2])
                    .put("accuracy", stats[1].toDouble() / stats[0])
            )
        }
    report.put("worst_repeated_word_forms", wordArray)

    println("\n=== GOLD HOMOGRAPH EVALUATION ===")
    println("Dataset: ${items.length()} sentences, ${byWord.size} distinct unaccented forms")
    println("RUAccent alone: $correct / $evaluated (${"%.2f".format(Locale.ROOT, 100.0 * correct / evaluated.coerceAtLeast(1))}%)")
    println("Stock RuVoice: $stockCorrect / $evaluated (${"%.2f".format(Locale.ROOT, 100.0 * stockCorrect / evaluated.coerceAtLeast(1))}%)")
    println("Stock + RUAccent merge: $combinedCorrect / $evaluated (${"%.2f".format(Locale.ROOT, 100.0 * combinedCorrect / evaluated.coerceAtLeast(1))}%)")
    println("RUAccent wins=$combinedWins; regressions=$combinedRegressions; net=${combinedWins - combinedRegressions}; changed=$combinedChanges")
    println("RUAccent standalone wrong vowel=$wrongPosition; no mark=$noMark; target missing=$missingTarget; multiword skipped=$skippedPhraseTargets; baseline missing=$baselineMissing; alignment errors=$alignmentErrors")
    println("Time: ${elapsedMs} ms")
    println("Worst repeated forms:")
    for (i in 0 until wordArray.length().coerceAtMost(15)) {
        val item = wordArray.getJSONObject(i)
        println("  ${item.getString("word")}: ${item.getInt("correct")}/${item.getInt("total")}")
    }
    println("=================================\n")
    return report
}

private fun evaluateLabelCorpus(
    corrector: RuAccentOnnxCorrector,
    corpusFile: File,
    kind: String,
): JSONObject {
    val corpus = JSONObject(corpusFile.readText(Charsets.UTF_8))
    require(corpus.optInt("schema_version") == 1) { "$kind corpus schema version is not supported" }
    val cases = corpus.getJSONArray("cases")
    var total = 0
    var passed = 0
    var missing = 0
    val misses = JSONArray()

    for (caseIndex in 0 until cases.length()) {
        val case = cases.getJSONObject(caseIndex)
        val text = case.getString("text")
        val expected = case.getJSONArray("expect")
        val prediction = corrector.correct(text) ?: error("RUAccent returned null in $kind case")
        val tokens = WORD_RE.findAll(text).map { it.value }.toList()
        val predictedTokens = WORD_RE.findAll(prediction.text).map { it.value }.toList()
        require(tokens.size == prediction.decisions.size && tokens.size == prediction.yoDecisions.size) {
            "Decision alignment failed in $kind case ${case.getString("id")}"
        }
        require(predictedTokens.size == tokens.size) {
            "Text alignment failed in $kind case ${case.getString("id")}"
        }

        for (checkIndex in 0 until expected.length()) {
            val check = expected.getJSONObject(checkIndex)
            val target = check.getString("word")
            val occurrence = check.optInt("occurrence", 0).coerceAtLeast(0)
            val matching = tokens.indices.filter { plain(tokens[it]) == plain(target) }
            total++
            if (matching.isEmpty() || occurrence >= matching.size) {
                missing++
                if (misses.length() < 100) misses.put(
                    JSONObject().put("case", case.getString("id")).put("word", target).put("status", "MISSING")
                )
                continue
            }
            val index = matching[occurrence]
            val actual = if (kind == "stress_usage") {
                prediction.decisions[index].name
            } else {
                when (prediction.yoDecisions[index]) {
                    YoDecision.RESTORE_YO -> "YO"
                    YoDecision.KEEP_E -> "NO_YO"
                    YoDecision.UNKNOWN -> "UNKNOWN"
                }
            }
            val expectedLabel = check.getString("label")
            if (actual == expectedLabel) passed++ else if (misses.length() < 100) {
                misses.put(
                    JSONObject()
                        .put("case", case.getString("id"))
                        .put("text", text)
                        .put("word", target)
                        .put("expected", expectedLabel)
                        .put("actual", actual)
                )
            }
        }
    }

    val scored = total - missing
    val report = JSONObject()
        .put("corpus", corpus.optString("name", kind))
        .put("total_checks", total)
        .put("scored", scored)
        .put("passed", passed)
        .put("mismatches", scored - passed)
        .put("missing", missing)
        .put("accuracy", if (scored == 0) 0.0 else passed.toDouble() / scored)
        .put("warning", "Small component smoke set only; not a general quality estimate.")
        .put("misses", misses)

    println("$kind: $passed/$scored passed; mismatches=${scored - passed}; missing=$missing")
    return report
}

fun main(args: Array<String>) {
    require(args.size == 5) {
        "Usage: Evaluate_ruaccent_qualityKt homograph.json stress_usage.json yo.json output.json stock-baseline.json"
    }
    val corpusFile = File(args[0])
    val stressUsageFile = File(args[1])
    val yoFile = File(args[2])
    val reportFile = File(args[3])
    val baselineFile = File(args[4])

    val root = Files.createTempDirectory("ruvoice-ruaccent-quality").toFile()
    val downloader = RuAccentHttpDownloader(connectTimeoutMillis = 30_000, readTimeoutMillis = 120_000)
    val hashes = linkedMapOf<String, String>()

    try {
        println("Pinned model revision: ${RuAccentInt8ModelManifest.revision}")
        println("Downloading ${RuAccentInt8ModelManifest.files.size} manifest-pinned files")
        RuAccentInt8ModelManifest.files.forEachIndexed { index, relative ->
            val destination = File(root, relative)
            check(destination.parentFile?.exists() == true || destination.parentFile?.mkdirs() == true) {
                "Cannot create model directory for $relative"
            }
            downloader.download(RuAccentInt8ModelManifest.downloadUrl(relative), destination) { bytes ->
                if (bytes == 0L || bytes % (64L * 1024 * 1024) < 1024 * 1024) {
                    System.err.print("\rModel ${index + 1}/${RuAccentInt8ModelManifest.files.size}: $relative — $bytes bytes")
                }
            }
            val actual = sha256(destination)
            val expected = RuAccentInt8ModelManifest.expectedSha256[relative]
                ?: error("No pinned SHA-256 for $relative")
            check(actual == expected) { "SHA-256 mismatch for $relative: $actual != $expected" }
            hashes[relative] = actual
        }
        println("\nPASS: all ${hashes.size} downloaded files match pinned SHA-256 values")

        val corrector = RuAccentOnnxCorrector(root)
        try {
            check(corrector.warmUp()) { "Four ONNX models failed to warm up" }
            println("PASS: all four production Kotlin ONNX sessions are loaded")

            val homographs = evaluateHomographs(corrector, corpusFile, baselineFile)
            val stressUsage = evaluateLabelCorpus(corrector, stressUsageFile, "stress_usage")
            val yo = evaluateLabelCorpus(corrector, yoFile, "yo")

            val report = JSONObject()
                .put("schema_version", 1)
                .put("model_repository", RuAccentInt8ModelManifest.repository)
                .put("model_revision", RuAccentInt8ModelManifest.revision)
                .put("runtime", "Production Kotlin RuAccentOnnxCorrector + ONNX Runtime CPU")
                .put("model_hashes", JSONObject(hashes))
                .put("homograph_eval", homographs)
                .put("stress_usage_smoke", stressUsage)
                .put("yo_smoke", yo)
                .put("interpretation", "Gold homograph accuracy measures RUAccent's independent output on labelled target words. It is not by itself proof of improvement over the separate stock RuVoice pipeline.")
            reportFile.parentFile?.mkdirs()
            reportFile.writeText(report.toString(2) + "\n", Charsets.UTF_8)
            println("QUALITY_REPORT=${reportFile.absolutePath}")
            println("PASS: RUAccent quality evaluation completed")
        } finally {
            corrector.close()
        }
    } finally {
        root.deleteRecursively()
    }
}
