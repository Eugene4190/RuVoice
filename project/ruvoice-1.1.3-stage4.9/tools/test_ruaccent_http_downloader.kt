package ru.kost.ruvoice.text

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.io.File
import java.net.InetSocketAddress
import java.nio.file.Files
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger

private fun HttpExchange.respond(status: Int, body: ByteArray, headers: Map<String, String> = emptyMap()) {
    headers.forEach { (key, value) -> responseHeaders.add(key, value) }
    sendResponseHeaders(status, body.size.toLong())
    responseBody.use { it.write(body) }
    close()
}

fun main() {
    val payload = ByteArray(32_000) { (it % 251).toByte() }
    val split = 4_096
    val temp = Files.createTempDirectory("ruvoice-range-test").toFile()
    val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
    val executor = Executors.newCachedThreadPool()
    server.executor = executor
    val base = "http://127.0.0.1:${server.address.port}"

    val resumedRange = AtomicInteger(-1)
    server.createContext("/resume") { exchange ->
        val range = exchange.requestHeaders.getFirst("Range")
        if (range == null) {
            exchange.sendResponseHeaders(200, payload.size.toLong())
            exchange.responseBody.use { output ->
                output.write(payload, 0, split)
                output.flush()
            }
            exchange.close()
        } else {
            val start = range.removePrefix("bytes=").removeSuffix("-").toInt()
            resumedRange.set(start)
            val suffix = payload.copyOfRange(start, payload.size)
            exchange.respond(
                206,
                suffix,
                mapOf("Content-Range" to "bytes $start-${payload.size - 1}/${payload.size}"),
            )
        }
    }

    val ignoreRangeCalls = AtomicInteger()
    server.createContext("/ignore-range") { exchange ->
        if (exchange.requestHeaders.getFirst("Range") != null) ignoreRangeCalls.incrementAndGet()
        exchange.respond(200, payload)
    }

    val badRangeCalls = AtomicInteger()
    server.createContext("/bad-range") { exchange ->
        badRangeCalls.incrementAndGet()
        val requested = exchange.requestHeaders.getFirst("Range")!!
            .removePrefix("bytes=").removeSuffix("-").toInt()
        val start = requested + 1
        val suffix = payload.copyOfRange(start, payload.size)
        exchange.respond(
            206,
            suffix,
            mapOf("Content-Range" to "bytes $start-${payload.size - 1}/${payload.size}"),
        )
    }

    val retryCalls = AtomicInteger()
    server.createContext("/retry-416") { exchange ->
        if (retryCalls.incrementAndGet() == 1) {
            exchange.sendResponseHeaders(416, -1)
            exchange.close()
        } else {
            check(exchange.requestHeaders.getFirst("Range") == null) {
                "HTTP 416 retry must restart without Range"
            }
            exchange.respond(200, payload)
        }
    }

    server.start()
    try {
        val downloader = RuAccentHttpDownloader(connectTimeoutMillis = 3_000, readTimeoutMillis = 3_000)

        val fresh = File(temp, "fresh.bin")
        downloader.download("$base/ignore-range", fresh)
        check(fresh.readBytes().contentEquals(payload))

        val resumed = File(temp, "resumed.bin")
        check(runCatching { downloader.download("$base/resume", resumed) }.isFailure) {
            "Truncated first response must fail instead of activating a partial file"
        }
        val partial = File(temp, "resumed.bin.part")
        check(partial.length() == split.toLong()) {
            "Expected $split retained bytes, got ${partial.length()}"
        }
        downloader.download("$base/resume", resumed)
        check(resumed.readBytes().contentEquals(payload))
        check(resumedRange.get() == split) {
            "Expected Range from $split, got ${resumedRange.get()}"
        }
        check(!partial.exists())

        val ignored = File(temp, "ignored.bin")
        File(temp, "ignored.bin.part").writeBytes(payload.copyOfRange(0, split))
        downloader.download("$base/ignore-range", ignored)
        check(ignored.readBytes().contentEquals(payload))
        check(ignoreRangeCalls.get() == 1)

        val malformed = File(temp, "malformed.bin")
        File(temp, "malformed.bin.part").writeBytes(payload.copyOfRange(0, split))
        check(runCatching { downloader.download("$base/bad-range", malformed) }.isFailure)
        check(!File(temp, "malformed.bin.part").exists())
        check(!malformed.exists())
        check(badRangeCalls.get() == 1)

        val retry = File(temp, "retry.bin")
        File(temp, "retry.bin.part").writeBytes(payload.copyOfRange(0, split))
        downloader.download("$base/retry-416", retry)
        check(retry.readBytes().contentEquals(payload))
        check(retryCalls.get() == 2)

        println("PASS real HTTP downloader integration: 5 scenarios")
        println("PASS truncated-response resume: retained $split bytes and sent the matching Range header")
        println("PASS ignored Range, malformed Content-Range, and HTTP 416 recovery")
    } finally {
        server.stop(0)
        executor.shutdownNow()
        temp.deleteRecursively()
    }
}
