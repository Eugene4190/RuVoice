package ru.kost.ruvoice.text

import java.io.File
import java.nio.file.Files
import java.security.MessageDigest

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
                check(prediction.decisions.size == Regex("[\\\\p{L}\\\\u0301]+").findAll(sample).count()) {
                    "Stress decisions do not align with source words in sample ${index + 1}"
                }
                println("INFERENCE ${index + 1}: ${prediction.text}")
            }
            println("PASS: four real Russian sentence inferences completed")
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
