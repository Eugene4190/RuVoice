package ru.kost.ruvoice.text

/** Strict HTTP Range response checks for resumable one-time model downloads. */
internal object RuAccentDownloadPolicy {
    enum class Action { WRITE_NEW, APPEND, RESTART_FROM_ZERO, RETRY_FROM_ZERO }

    data class Plan(
        val action: Action,
        val expectedTotalBytes: Long? = null,
        val responseBytes: Long? = null,
    )

    private val contentRangePattern = Regex("^bytes\\s+(\\d+)-(\\d+)/(\\d+|\\*)$", RegexOption.IGNORE_CASE)

    fun plan(offset: Long, statusCode: Int, contentRange: String?, contentLength: Long): Plan {
        require(offset >= 0L) { "Negative partial-file offset" }
        when {
            offset == 0L && statusCode == 200 -> {
                return Plan(Action.WRITE_NEW, expectedTotalBytes = contentLength.takeIf { it >= 0L }, responseBytes = contentLength.takeIf { it >= 0L })
            }
            offset == 0L && statusCode == 206 -> error("Unexpected partial response without a Range request")
            offset > 0L && statusCode == 200 -> {
                // Server/CDN ignored Range; its body is a complete file, so truncate the old .part.
                return Plan(Action.RESTART_FROM_ZERO, expectedTotalBytes = contentLength.takeIf { it >= 0L }, responseBytes = contentLength.takeIf { it >= 0L })
            }
            offset > 0L && statusCode == 416 -> return Plan(Action.RETRY_FROM_ZERO)
            offset > 0L && statusCode == 206 -> {
                val match = contentRangePattern.matchEntire(contentRange?.trim().orEmpty())
                    ?: error("Invalid Content-Range header for resumed download")
                val start = match.groupValues[1].toLong()
                val end = match.groupValues[2].toLong()
                val totalText = match.groupValues[3]
                require(start == offset) { "Content-Range starts at $start, expected $offset" }
                require(end >= start) { "Content-Range end precedes start" }
                val segmentBytes = end - start + 1L
                if (contentLength >= 0L) require(segmentBytes == contentLength) {
                    "Content-Range length $segmentBytes does not match Content-Length $contentLength"
                }
                val total = totalText.takeIf { it != "*" }?.toLong()
                if (total != null) require(total > end) { "Content-Range total does not exceed range end" }
                return Plan(
                    Action.APPEND,
                    expectedTotalBytes = total ?: contentLength.takeIf { it >= 0L }?.let { offset + it },
                    responseBytes = contentLength.takeIf { it >= 0L } ?: segmentBytes,
                )
            }
            else -> error("Unexpected HTTP status for model download: $statusCode")
        }
    }
}
