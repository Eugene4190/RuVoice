package ru.kost.ruvoice.text

fun main() {
    val first = RuAccentDownloadPolicy.plan(0, 200, null, 1000)
    check(first.action == RuAccentDownloadPolicy.Action.WRITE_NEW)
    check(first.expectedTotalBytes == 1000L)

    val resumed = RuAccentDownloadPolicy.plan(600, 206, "bytes 600-999/1000", 400)
    check(resumed.action == RuAccentDownloadPolicy.Action.APPEND)
    check(resumed.expectedTotalBytes == 1000L)
    check(resumed.responseBytes == 400L)

    val unknownTotal = RuAccentDownloadPolicy.plan(600, 206, "bytes 600-999/*", 400)
    check(unknownTotal.action == RuAccentDownloadPolicy.Action.APPEND)
    check(unknownTotal.expectedTotalBytes == 1000L)

    val serverIgnoredRange = RuAccentDownloadPolicy.plan(600, 200, null, 1000)
    check(serverIgnoredRange.action == RuAccentDownloadPolicy.Action.RESTART_FROM_ZERO)
    check(serverIgnoredRange.expectedTotalBytes == 1000L)

    check(RuAccentDownloadPolicy.plan(600, 416, null, 0).action == RuAccentDownloadPolicy.Action.RETRY_FROM_ZERO)
    check(runCatching { RuAccentDownloadPolicy.plan(600, 206, "bytes 500-999/1000", 500) }.isFailure)
    check(runCatching { RuAccentDownloadPolicy.plan(600, 206, "nonsense", 400) }.isFailure)
    check(runCatching { RuAccentDownloadPolicy.plan(600, 206, "bytes 600-999/1000", 399) }.isFailure)
    check(runCatching { RuAccentDownloadPolicy.plan(0, 206, "bytes 0-999/1000", 1000) }.isFailure)
    check(runCatching { RuAccentDownloadPolicy.plan(-1, 200, null, 1000) }.isFailure)

    println("PASS RUAccent resumable-download HTTP Range tests: 10/10")
}
