package ru.kost.ruvoice.text

fun main() {
    val files = listOf("nn_accent/model.onnx", "nn_accent/vocab.txt", "dictionary/yo_words.json.gz")
    RuAccentInstallManifestPolicy.validateManifest(
        "TigreGotico/stressonnx-models", "a".repeat(40), "ru_ruaccent", files,
    )

    check(!RuAccentInstallManifestPolicy.isSafeRelativePath("../escape"))
    check(!RuAccentInstallManifestPolicy.isSafeRelativePath("/absolute/path"))
    check(!RuAccentInstallManifestPolicy.isSafeRelativePath("nn_accent\\model.onnx"))
    check(!RuAccentInstallManifestPolicy.isSafeRelativePath("nn_accent/./model.onnx"))
    check(runCatching {
        RuAccentInstallManifestPolicy.validateManifest("repo/model", "a".repeat(40), "bundle", files + files[0])
    }.isFailure)
    check(runCatching {
        RuAccentInstallManifestPolicy.validateManifest("repo/model", "main", "bundle", files)
    }.isFailure)

    val expectedHashes = files.associateWith { "b".repeat(64) }
    check(RuAccentInstallManifestPolicy.isValidExpectedHashes(files, expectedHashes))
    check(!RuAccentInstallManifestPolicy.isValidExpectedHashes(files, expectedHashes - files.last()))
    check(!RuAccentInstallManifestPolicy.isValidExpectedHashes(files, expectedHashes + ("extra.bin" to "c".repeat(64))))
    check(!RuAccentInstallManifestPolicy.isValidExpectedHashes(files, expectedHashes + (files.last() to "bad")))

    check(RuAccentInstallManifestPolicy.isValidCompletionMarker(
        "TigreGotico/stressonnx-models", "TigreGotico/stressonnx-models",
        "a".repeat(40), "a".repeat(40), files, expectedHashes, expectedHashes,
    ))
    check(!RuAccentInstallManifestPolicy.isValidCompletionMarker(
        "TigreGotico/stressonnx-models", "TigreGotico/stressonnx-models",
        "a".repeat(40), "a".repeat(40), files, expectedHashes, expectedHashes - files.last(),
    ))
    check(!RuAccentInstallManifestPolicy.isValidCompletionMarker(
        "TigreGotico/stressonnx-models", "TigreGotico/stressonnx-models",
        "a".repeat(40), "a".repeat(40), files, expectedHashes,
        expectedHashes + (files.last() to "c".repeat(64)),
    ))
    check(!RuAccentInstallManifestPolicy.isValidCompletionMarker(
        "wrong/repository", "TigreGotico/stressonnx-models",
        "a".repeat(40), "a".repeat(40), files, expectedHashes, expectedHashes,
    ))
    check(!RuAccentInstallManifestPolicy.isValidCompletionMarker(
        "TigreGotico/stressonnx-models", "TigreGotico/stressonnx-models",
        "c".repeat(40), "a".repeat(40), files, expectedHashes, expectedHashes,
    ))

    println("PASS RUAccent installer manifest/path/pinned-SHA/completion-marker tests: 15/15")
}
