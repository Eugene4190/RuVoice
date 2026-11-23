package ru.kost.ruvoice.text

import android.content.Context
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.util.zip.GZIPInputStream

/** Загружает фиксированную ревизию RUAccent int8 один раз; после загрузки сеть не нужна. */
internal class RuAccentModelInstaller(context: Context) {
    private val appContext = context.applicationContext

    data class Progress(val fileIndex: Int, val fileCount: Int, val fileName: String, val bytesRead: Long)

    /** Быстрая проверка для запуска сервиса: не перечитывает 145 МБ SHA на каждом старте. */
    fun installedDirectory(): File? = finalDirectory().takeIf { isComplete(it, verifyHashes = false) }

    @Throws(Exception::class)
    fun install(progress: ((Progress) -> Unit)? = null): File {
        finalDirectory().takeIf { isComplete(it, verifyHashes = true) }?.let { return it }
        val parent = finalDirectory().parentFile ?: error("Не удалось определить каталог моделей")
        check(parent.exists() || parent.mkdirs()) { "Не удалось создать каталог моделей" }
        val staging = File(parent, "${RuAccentInt8ModelManifest.revision}.installing")
        check(staging.exists() || staging.mkdirs()) { "Не удалось создать временный каталог модели" }
        // Preserve known completed files and .part downloads after an interrupted connection.
        // Remove unexpected staging paths; the manifest is pinned and already path-validated.
        val retained = buildSet {
            add(COMPLETE_FILE)
            RuAccentInt8ModelManifest.files.forEach { add(it); add("$it.part") }
        }
        staging.walkTopDown().filter { it.isFile }.forEach { file ->
            val relative = file.relativeTo(staging).path.replace(File.separatorChar, '/')
            if (relative !in retained) file.delete()
        }

        try {
            RuAccentInt8ModelManifest.files.forEachIndexed { index, relative ->
                val destination = File(staging, relative)
                check(destination.parentFile?.exists() == true || destination.parentFile?.mkdirs() == true) {
                    "Не удалось создать каталог для $relative"
                }
                // A validated completed file from a previous attempt is reused.
                val alreadyComplete = destination.isFile && runCatching { validateFile(relative, destination) }.isSuccess
                if (alreadyComplete) {
                    progress?.invoke(Progress(index + 1, RuAccentInt8ModelManifest.files.size, relative, destination.length()))
                    return@forEachIndexed
                }
                if (destination.exists()) destination.delete()
                download(RuAccentInt8ModelManifest.downloadUrl(relative), destination) { bytes ->
                    progress?.invoke(Progress(index + 1, RuAccentInt8ModelManifest.files.size, relative, bytes))
                }
                validateFile(relative, destination)
            }

            val marker = JSONObject().apply {
                put("repository", RuAccentInt8ModelManifest.repository)
                put("revision", RuAccentInt8ModelManifest.revision)
                put("files", JSONObject().apply {
                    RuAccentInt8ModelManifest.files.forEach { relative ->
                        put(relative, sha256(File(staging, relative)))
                    }
                })
            }
            File(staging, COMPLETE_FILE).writeText(marker.toString(), Charsets.UTF_8)

            val target = finalDirectory()
            val backup = File(parent, "${RuAccentInt8ModelManifest.revision}.previous")
            deleteRecursively(backup)
            if (target.exists() && !target.renameTo(backup)) error("Не удалось заменить старую модель")
            if (!staging.renameTo(target)) {
                if (backup.exists()) backup.renameTo(target)
                error("Не удалось завершить установку модели")
            }
            deleteRecursively(backup)
            return target
        } catch (error: Throwable) {
            // Keep validated completed files and .part fragments so the next attempt can resume.
            throw error
        }
    }

    private fun finalDirectory() = File(
        appContext.filesDir,
        "ruvoice-models/${RuAccentInt8ModelManifest.bundleDirectory}/${RuAccentInt8ModelManifest.revision}"
    )

    private fun isComplete(directory: File, verifyHashes: Boolean): Boolean = runCatching {
        val marker = File(directory, COMPLETE_FILE)
        if (!marker.isFile) return@runCatching false
        val json = JSONObject(marker.readText(Charsets.UTF_8))
        if (json.optString("revision") != RuAccentInt8ModelManifest.revision) return@runCatching false
        if (json.optString("repository") != RuAccentInt8ModelManifest.repository) return@runCatching false
        val hashes = json.optJSONObject("files") ?: return@runCatching false
        val recordedHashes = LinkedHashMap<String, String>()
        val hashKeys = hashes.keys()
        while (hashKeys.hasNext()) {
            val key = hashKeys.next()
            recordedHashes[key] = hashes.optString(key, "")
        }
        if (!RuAccentInstallManifestPolicy.isValidCompletionMarker(
                repository = json.optString("repository"),
                expectedRepository = RuAccentInt8ModelManifest.repository,
                revision = json.optString("revision"),
                expectedRevision = RuAccentInt8ModelManifest.revision,
                expectedFiles = RuAccentInt8ModelManifest.files,
                recordedHashes = recordedHashes,
            )) return@runCatching false
        RuAccentInt8ModelManifest.files.all { relative ->
            val file = File(directory, relative)
            file.isFile && file.length() > 0L &&
                (!verifyHashes || recordedHashes[relative] == sha256(file))
        }
    }.getOrDefault(false)

    private fun download(
        url: String,
        destination: File,
        allowFreshRetry: Boolean = true,
        onBytes: (Long) -> Unit,
    ) {
        val part = File(destination.parentFile, destination.name + ".part")
        val resumeOffset = part.length().coerceAtLeast(0L)
        val connection = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 20_000
            readTimeout = 60_000
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
            plan.responseBytes?.let { expected -> check(responseBytes == expected) {
                "Загружена не вся часть ${destination.name}: $responseBytes из $expected байт"
            } }
            plan.expectedTotalBytes?.let { expected -> check(part.length() == expected) {
                "Загружен не весь файл ${destination.name}: ${part.length()} из $expected байт"
            } }
            check(part.renameTo(destination)) { "Не удалось сохранить ${destination.name}" }
        } finally {
            connection.disconnect()
        }
    }

    private fun validateFile(relative: String, file: File) {
        when {
            relative.endsWith(".json") -> JSONObject(file.readText(Charsets.UTF_8))
            relative.endsWith(".json.gz") -> GZIPInputStream(file.inputStream()).bufferedReader(Charsets.UTF_8).use {
                JSONObject(it.readText())
            }
            relative.endsWith(".onnx") -> check(file.length() > 16_384L) {
                "ONNX-файл подозрительно мал: $relative"
            }
            relative.endsWith(".txt") -> check(file.readLines().size > 100) {
                "Словарь токенизатора неполный: $relative"
            }
            else -> check(file.length() > 0L) { "Пустой файл: $relative" }
        }
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().buffered().use { input ->
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                digest.update(buffer, 0, count)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun deleteRecursively(file: File) {
        if (file.isDirectory) file.listFiles()?.forEach(::deleteRecursively)
        file.delete()
    }

    private companion object { const val COMPLETE_FILE = ".ruvoice-model-installed.json" }
}
