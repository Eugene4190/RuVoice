package ru.kost.ruvoice.text

/** Small no-Gradle regression harness for the pure NLI context helper. */
fun main() {
    val words = listOf("на", "двери", "висел", "замок", ",", "а", "на", "холме", "стоял", "замок", ".")
    val first = RuAccentOmographContext.buildMarkedWindow(words, 3, 64)
    check(first == "на двери висел <w>замок</w> , а на холме стоял замок.") {
        "Unexpected first-occurrence NLI context: $first"
    }
    val second = RuAccentOmographContext.buildMarkedWindow(words, 9, 64)
    check(second == "на двери висел замок, а на холме стоял <w>замок</w> .") {
        "Unexpected second-occurrence NLI context: $second"
    }
    val adjacentWords = listOf("он", "поставил", "замок", "и", "ушел", ".")
    val adjacent = RuAccentOmographContext.buildMarkedWindow(adjacentWords, 2, 64)
    check(adjacent == "он поставил <w>замок</w>  и ушел.") {
        "Unexpected reference context after target before next word: $adjacent"
    }
    val longWords = List(160) { "слово" }.toMutableList().also { it[80] = "замок" }
    val centered = RuAccentOmographContext.buildMarkedWindow(longWords, 80, 64) ?: error("Missing window")
    check(centered.split(' ').count { it.isNotEmpty() } == 129)
    check(Regex("<w>замок</w>").findAll(centered).count() == 1)
    check(RuAccentOmographContext.buildMarkedWindow(words, 99, 64) == null)
    println("PASS reference NLI context padding / punctuation / occurrence / window tests: 5/5")
}
