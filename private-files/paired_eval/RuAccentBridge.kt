package ru.kost.ruvoice.text

import org.json.JSONArray
import org.json.JSONObject
import java.io.File

fun main(args: Array<String>) {
    require(args.size == 1) { "Usage: RuAccentBridge <model-directory>" }
    val corrector = RuAccentOnnxCorrector(File(args[0]).absoluteFile)
    try {
        check(corrector.warmUp()) { "RUAccent warm-up failed" }
        println(JSONObject().put("ready", true))
        System.out.flush()
        while (true) {
            val line = readLine() ?: break
            val request = JSONObject(line)
            if (request.optString("op") == "quit") break
            val prediction = corrector.correct(request.getString("text"))
                ?: error("RUAccent returned no prediction")
            val decisions = JSONArray()
            prediction.decisions.forEach { decisions.put(it.name) }
            val yo = JSONArray()
            prediction.yoDecisions.forEach { yo.put(it.name) }
            val yoSources = JSONArray()
            prediction.yoDecisionSources.forEach { yoSources.put(it.name) }
            check(prediction.yoDecisionSources.size == prediction.decisions.size) {
                "RUAccent ё decision provenance does not align with word decisions"
            }
            println(JSONObject()
                .put("text", prediction.text)
                .put("decisions", decisions)
                .put("yo_decisions", yo)
                .put("yo_decision_sources", yoSources))
            System.out.flush()
        }
    } finally {
        corrector.close()
    }
}
