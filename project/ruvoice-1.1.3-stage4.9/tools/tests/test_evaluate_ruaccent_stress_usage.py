import json
from pathlib import Path

import pytest

from tools.evaluate_ruaccent_stress_usage import (
    evaluate_cases,
    load_corpus,
)
from tools.probe_ruaccent_stress_usage import ProbeError, validate_stress_label_map


def corpus():
    return {
        "schema_version": 1,
        "name": "test corpus",
        "cases": [
            {
                "id": "one",
                "text": "Или мы едем, или ждём.",
                "expect": [
                    {"word": "Или", "occurrence": 0, "label": "NO_STRESS"},
                    {"word": "или", "occurrence": 1, "label": "NO_STRESS"},
                ],
            }
        ],
    }


def test_label_map_accepts_exact_stress_classes():
    assert validate_stress_label_map({"0": "NO_STRESS", "1": "STRESS"}) == {
        "0": "NO_STRESS", "1": "STRESS"
    }


@pytest.mark.parametrize("mapping", [
    None,
    {"0": "STRESS"},
    {"0": "STRESS", "2": "NO_STRESS"},
    {"0": "LABEL_0", "1": "LABEL_1"},
])
def test_label_map_rejects_unsupported_class_maps(mapping):
    with pytest.raises(ProbeError):
        validate_stress_label_map(mapping)


def test_evaluator_matches_repeated_occurrences_case_insensitively():
    def fake_probe(text):
        assert text == "Или мы едем, или ждём."
        return {"word_labels": [
            {"word": "Или", "label": "NO_STRESS", "confidence": 0.92,
             "label_scores": {"NO_STRESS": 0.92, "STRESS": 0.08}},
            {"word": "или", "label": "NO_STRESS", "confidence": 0.88,
             "label_scores": {"NO_STRESS": 0.88, "STRESS": 0.12}},
        ]}
    result = evaluate_cases(corpus(), fake_probe)
    assert result["total_checks"] == 2
    assert result["passed"] == 2
    assert result["mismatches"] == 0
    assert result["missing"] == 0


def test_evaluator_reports_mismatch_and_missing_separately():
    def fake_probe(_text):
        return {"word_labels": [
            {"word": "Или", "label": "STRESS", "confidence": 0.7},
        ]}
    result = evaluate_cases(corpus(), fake_probe)
    assert result["passed"] == 0
    assert result["mismatches"] == 1
    assert result["missing"] == 1
    assert result["cases"][0]["checks"][0]["status"] == "MISMATCH"
    assert result["cases"][0]["checks"][1]["status"] == "MISSING"


def test_bundled_smoke_corpus_loads_and_contains_targets():
    root = Path(__file__).resolve().parents[1]
    payload = load_corpus(root / "data" / "ruaccent_stress_usage_smoke.json")
    assert len(payload["cases"]) >= 8
    assert any(item["word"].casefold() == "между" for c in payload["cases"] for item in c["expect"])


def test_corpus_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "cases": [
            {"id": "x", "text": "тест", "expect": [{"word": "тест", "label": "STRESS"}]},
            {"id": "x", "text": "тест", "expect": [{"word": "тест", "label": "STRESS"}]},
        ],
    }), encoding="utf-8")
    with pytest.raises(ProbeError, match="duplicate"):
        load_corpus(path)
