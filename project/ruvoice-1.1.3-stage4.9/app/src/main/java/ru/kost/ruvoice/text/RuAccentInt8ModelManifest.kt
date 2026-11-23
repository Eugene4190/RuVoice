package ru.kost.ruvoice.text

/**
 * Фиксированный набор файлов контекстной русской модели stressonnx/RUAccent int8.
 * И ревизия, и SHA-256 закреплены: изменение модели требует нового манифеста и повторной проверки.
 * В комплекте 4 ONNX-графа, 3 FastTokenizer JSON и словари RUAccent.
 */
internal object RuAccentInt8ModelManifest {
    const val repository = "TigreGotico/stressonnx-models"
    const val revision = "cb1594ddf81928e678a3a7ee7a22415e6e3a218f"
    const val bundleDirectory = "ru_ruaccent"

    val files: List<String> = listOf(
        "nn_accent/model.onnx",
        "nn_accent/vocab.txt",
        "nn_accent/config.json",
        "nn_stress_usage/model.int8.onnx",
        "nn_stress_usage/tokenizer.json",
        "nn_stress_usage/config.json",
        "nn_yo_homograph/model.onnx",
        "nn_yo_homograph/tokenizer.json",
        "nn_yo_homograph/config.json",
        "nn_omograph/model.int8.onnx",
        "nn_omograph/tokenizer.json",
        "dictionary/omographs.json.gz",
        "dictionary/yo_words.json.gz",
        "dictionary/yo_homographs.json.gz",
        "dictionary/accents_nn.json.gz",
        "meta.json",
    )

    /** SHA-256 контрольные суммы 16 файлов, полученные при проверке закреплённой ревизии. */
    val expectedSha256: Map<String, String> = linkedMapOf(
        "nn_accent/model.onnx" to "4e393144e45626f6f1062a0784ef06f921b97321a8e7b87ac2a09a892286500a",
        "nn_accent/vocab.txt" to "242882b2f27800e49a6babf46867dabf6dc9b6535b600776a68815fe4d4f4382",
        "nn_accent/config.json" to "e377f159a8fc8673e211f100d4a237d5fe3dceb3b6789a5a738bf50bda23be49",
        "nn_stress_usage/model.int8.onnx" to "90a54b2c718792468a92631af80270361a48f10ce259fdfc3ff26f9f9c5079e0",
        "nn_stress_usage/tokenizer.json" to "ce51cde5df60ecb167abec4c90db11360482150628f7a91f3e316df6d6ff6f6f",
        "nn_stress_usage/config.json" to "aa0638edf56254f123e593e96f034c2b5e68303ac207b29f64f0878dc4c22631",
        "nn_yo_homograph/model.onnx" to "42cc85bf0c4b319dfe3d89fa17b162a92fd5e1c651a657cb3d5f44978d4e70ac",
        "nn_yo_homograph/tokenizer.json" to "f2bf174f2fe62ff11c28d56555f9c0cf16b24e162ef53bcf42ff85ebcf6ebfa8",
        "nn_yo_homograph/config.json" to "adf7fd2c67be1498071f447ec4a23dbe84904c49f95d1d3e6c7d9df269b9a2e9",
        "nn_omograph/model.int8.onnx" to "1df757980fba1910e31d3b30e165a1bfbf13cbe8c7fb22132850d4558e0ae64b",
        "nn_omograph/tokenizer.json" to "eb84a77af38a91f6f327486c7827d8541f8d446250f8d408909999b6be817afa",
        "dictionary/omographs.json.gz" to "04a9e81c68d65f65ba493fe0110f99e79087548c2beeec3032e2b66e28706f36",
        "dictionary/yo_words.json.gz" to "a19fa89a964a0691d9fe4ee384783e3934904891843d8f59a1c480d67947a82a",
        "dictionary/yo_homographs.json.gz" to "c4ee777bbbab87f9eac838f370ad92974e079d02b21903e480c54b5f0c8c60d1",
        "dictionary/accents_nn.json.gz" to "8395664000b80c1afe09bfea3650945b0933482b8e3dee5bb9d429eb18c44935",
        "meta.json" to "96562f2cbb84b9c6ff8f20538a946c41bc48f7feb48063f5deda79111ff94e6a",
    )

    init {
        RuAccentInstallManifestPolicy.validateManifest(repository, revision, bundleDirectory, files)
        require(RuAccentInstallManifestPolicy.isValidExpectedHashes(files, expectedSha256)) {
            "RUAccent SHA-256 manifest does not match the pinned file list"
        }
    }

    fun downloadUrl(relativePath: String): String {
        require(relativePath in files) { "Unknown RUAccent model file: $relativePath" }
        require(RuAccentInstallManifestPolicy.isSafeRelativePath(relativePath)) {
            "Unsafe RUAccent model path: $relativePath"
        }
        return "https://huggingface.co/$repository/resolve/$revision/$bundleDirectory/$relativePath"
    }
}
