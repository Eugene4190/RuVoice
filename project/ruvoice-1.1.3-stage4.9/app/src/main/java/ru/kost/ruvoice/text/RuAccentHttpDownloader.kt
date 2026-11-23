package ru.kost.ruvoice.text

import java.io.BufferedInputStream
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL

/**
 * HTTP downloader for the optional offline RUAccent bundle.
 *
 * A partial response is appended only after strict Content-Range validation.
 * Interrupted transfers keep their .part file so the next attempt can resume.
 */
internal class RuAccentHttpDownloader(
    private val connectTimeoutMillis: Int = 20_000,
    private val readTimeoutMillis: Int = 60_000,
) {
    fun download(url: String, destination: File, onBytes: (Long) -> Unit = {}) {
        download(url, destination, allowFreshRetry = true, onBytes = onBytes)
    }

    private fun download(url: String, destination: File, allowFreshRetry: Boolean, onBytes: (Long) -> Unit) {
        val part = File(destination.parentFile, destination.name + ".part")
        val resumeOffset = part.length().coerceAtLeast(0L)
        val connection = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = connectTimeoutMillis
            readTimeout = readTimeoutMillis
            instanceFollowRedirects = true
            setRequestProperty("User-Agent", "RuVoice/1.1.3 (offline RUAccent model installer)")
            if (resumeOffset > 0L) setRequestProperty("Range", "bytes=$resumeOffset-")
        }
        try {
            connection.connect()
            val status = connection.responseCode
            val plan = try {
                RuAccentDownloadPolicy.plan(
                    offset = resumeOffset,
                    statusCode = status,
                    contentRange = connection.getHeaderField("Content-Range"),
                    contentLength = connection.contentLengthLong,
                )
            } catch (error: Throwable) {
                if (status == HttpURLConnection.HTTP_PARTIAL) part.delete()
                throw error
            }
            if (plan.action == RuAccentDownloadPolicy.Action.RETRY_FROM_ZERO) {
                check(allowFreshRetry) { "Сервер повторно отклонил загрузку с нулевого байта (HTTP 416)" }
                connection.disconnect()
                part.delete()
                download(url, destination, allowFreshRetry = false, onBytes = onBytes)
                return
            }

            val append = plan.action == RuAccentDownloadPolicy.Action.APPEND
            if (!append) part.delete()
            val baseBytes = if (append) resumeOffset else 0L
            var responseBytes = 0L
            BufferedInputStream(connection.inputStream).use { input ->
                FileOutputStream(part, append).use { output ->
                    val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) break
                        output.write(buffer, 0, count)
                        responseBytes += count
                        onBytes(baseBytes + responseBytes)
                    }
                    output.fd.sync()
                }
            }
            check(responseBytes > 0L) { "Сервер вернул пустой файл: ${destination.name}" }
            plan.responseBytes?.let { expected ->
                check(responseBytes == expected) {
                    "Загружена не вся часть ${destination.name}: $responseBytes из $expected байт"
                }
            }
            plan.expectedTotalBytes?.let { expected ->
                check(part.length() == expected) {
                    "Загружен не весь файл ${destination.name}: ${part.length()} из $expected байт"
                }
            }
            check(part.renameTo(destination)) { "Не удалось сохранить ${destination.name}" }
        } finally {
            connection.disconnect()
        }
    }
}
