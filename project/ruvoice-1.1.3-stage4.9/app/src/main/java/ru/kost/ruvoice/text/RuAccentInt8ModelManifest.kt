package ru.kost.ruvoice.text

/**
 * Фиксированный набор файлов контекстной русской модели stressonnx/RUAccent int8.
 * Список и ревизия закреплены: установщик не должен скачивать меняющиеся `main`/`dev`.
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

    init {
        RuAccentInstallManifestPolicy.validateManifest(repository, revision, bundleDirectory, files)
    }

    fun downloadUrl(relativePath: String): String {
        require(relativePath in files) { "Unknown RUAccent model file: $relativePath" }
        require(RuAccentInstallManifestPolicy.isSafeRelativePath(relativePath)) {
            "Unsafe RUAccent model path: $relativePath"
        }
        return "https://huggingface.co/$repository/resolve/$revision/$bundleDirectory/$relativePath"
    }
}
