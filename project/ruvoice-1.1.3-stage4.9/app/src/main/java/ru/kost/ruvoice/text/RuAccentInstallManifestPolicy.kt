package ru.kost.ruvoice.text

/** Pure checks for the pinned offline RUAccent model bundle manifest and completion marker. */
internal object RuAccentInstallManifestPolicy {
    private val revisionPattern = Regex("^[0-9a-f]{40}$")
    private val sha256Pattern = Regex("^[0-9a-f]{64}$")

    fun isSafeRelativePath(path: String): Boolean {
        if (path.isBlank() || path.startsWith('/') || path.startsWith('\\')) return false
        if ('\\' in path || '\u0000' in path) return false
        val segments = path.split('/')
        return segments.all { it.isNotBlank() && it != "." && it != ".." && ':' !in it }
    }

    fun validateManifest(
        repository: String,
        revision: String,
        bundleDirectory: String,
        files: List<String>,
    ) {
        require(repository.matches(Regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"))) {
            "Invalid Hugging Face repository id"
        }
        require(revisionPattern.matches(revision)) { "Model revision must be a pinned 40-character commit" }
        require(isSafeRelativePath(bundleDirectory) && '/' !in bundleDirectory) {
            "Model bundle directory must be one safe path segment"
        }
        require(files.isNotEmpty()) { "Model bundle manifest is empty" }
        require(files.size == files.toSet().size) { "Model bundle manifest contains duplicate paths" }
        require(files.all(::isSafeRelativePath)) { "Model bundle manifest contains an unsafe path" }
    }

    fun isValidCompletionMarker(
        repository: String,
        expectedRepository: String,
        revision: String,
        expectedRevision: String,
        expectedFiles: List<String>,
        recordedHashes: Map<String, String>,
    ): Boolean {
        if (repository != expectedRepository || revision != expectedRevision) return false
        if (expectedFiles.isEmpty() || expectedFiles.size != expectedFiles.toSet().size) return false
        if (expectedFiles.any { !isSafeRelativePath(it) }) return false
        if (recordedHashes.keys != expectedFiles.toSet()) return false
        return recordedHashes.values.all(sha256Pattern::matches)
    }

    fun isValidSha256(value: String): Boolean = sha256Pattern.matches(value)
}
