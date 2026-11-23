package ru.kost.ruvoice.text

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RuAccentInstallManifestPolicyTest {
    private val files = listOf("nn_accent/model.onnx", "nn_accent/vocab.txt", "dictionary/yo_words.json.gz")
    private val hashes = files.associateWith { "b".repeat(64) }

    @Test fun actualPinnedManifestIsValidAndComplete() {
        RuAccentInstallManifestPolicy.validateManifest(
            RuAccentInt8ModelManifest.repository,
            RuAccentInt8ModelManifest.revision,
            RuAccentInt8ModelManifest.bundleDirectory,
            RuAccentInt8ModelManifest.files,
        )
        assertTrue(RuAccentInt8ModelManifest.files.all { RuAccentInt8ModelManifest.downloadUrl(it).contains("/resolve/${RuAccentInt8ModelManifest.revision}/") })
    }

    @Test fun rejectsPathTraversalAndDuplicateFiles() {
        assertFalse(RuAccentInstallManifestPolicy.isSafeRelativePath("../outside"))
        assertFalse(RuAccentInstallManifestPolicy.isSafeRelativePath("nn_accent\\model.onnx"))
        assertFalse(runCatching {
            RuAccentInstallManifestPolicy.validateManifest("owner/repo", "a".repeat(40), "bundle", files + files.first())
        }.isSuccess)
    }

    @Test fun acceptsOnlyExactCompletionMarkerWithSha256Values() {
        assertTrue(RuAccentInstallManifestPolicy.isValidCompletionMarker(
            "owner/repo", "owner/repo", "a".repeat(40), "a".repeat(40), files, hashes,
        ))
        assertFalse(RuAccentInstallManifestPolicy.isValidCompletionMarker(
            "owner/repo", "owner/repo", "a".repeat(40), "a".repeat(40), files, hashes - files.last(),
        ))
        assertFalse(RuAccentInstallManifestPolicy.isValidCompletionMarker(
            "owner/repo", "owner/repo", "a".repeat(40), "a".repeat(40), files, hashes + (files.last() to "bad"),
        ))
    }
}
