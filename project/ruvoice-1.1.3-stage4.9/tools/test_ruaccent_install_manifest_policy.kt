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
    check(RuAccentInstallManifestPolicy.isValidCompletionMarker(
        "TigreGotico/stressonnx-models", "TigreGotico/stressonnx-models",
        "a".repeat(40), "a".repeat(40), files, expectedHashes,
    ))
    check(!RuAccentInstallManifestPolicy.isValidCompletionMarker(
        "TigreGotico/stressonnx-models", "TigreGotico/stressonnx-models",
        "a".repeat(40), "a".repeat(40), files, expectedHashes - files.last(),
    ))
    check(!RuAccentInstallManifestPolicy.isValidCompletionMarker(
        "TigreGotico/stressonnx-models", "TigreGotico/stressonnx-models",
        "a".repeat(40), "a".repeat(40), files, expectedHashes + (files.last() to "bad"),
    ))
    check(!RuAccentInstallManifestPolicy.isValidCompletionMarker(
        "wrong/repository", "TigreGotico/stressonnx-models",
        "a".repeat(40), "a".repeat(40), files, expectedHashes,
    ))
    check(!RuAccentInstallManifestPolicy.isValidCompletionMarker(
        "TigreGotico/stressonnx-models", "TigreGotico/stressonnx-models",
        "c".repeat(40), "a".repeat(40), files, expectedHashes,
    ))
    println("PASS RUAccent installer manifest/path/completion-marker tests: 10/10")
}
