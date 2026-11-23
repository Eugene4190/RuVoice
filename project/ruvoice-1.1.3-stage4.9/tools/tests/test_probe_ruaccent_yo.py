import json
from pathlib import Path

import numpy as np
import pytest

from tools.probe_ruaccent_yo import (
    CONFIG_RELATIVE,
    FILES,
    MIN_ONNX_BYTES,
    MODEL_RELATIVE,
    REVISION,
    TOKENIZER_RELATIVE,
    ProbeError,
    aggregate_word_labels,
    evaluate_cases,
    load_corpus,
    run_probe,
    url_for,
    validate_bundle,
    validate_model,
    validate_yo_label_map,
)


def make_fixture(root: Path) -> None:
    model = root / MODEL_RELATIVE
    model.parent.mkdir(parents=True, exist_ok=True)
    with model.open("wb") as stream:
        stream.write(b"\x08\x08")
        stream.truncate(MIN_ONNX_BYTES + 1)

    tokenizer = root / TOKENIZER_RELATIVE
    tokenizer.parent.mkdir(parents=True, exist_ok=True)
    tokenizer.write_text(json.dumps({
        "version": "1.0",
        "model": {
            "type": "WordPiece",
            "vocab": {"[UNK]": 0, "[CLS]": 1, "[SEP]": 2, "он": 3, "все": 4, "знает": 5, ".": 6},
            "continuing_subword_prefix": "##"
        },
        "pre_tokenizer": {"type": "BertPreTokenizer"},
        "post_processor": {
            "type": "TemplateProcessing",
            "single": [
                {"SpecialToken": {"id": "[CLS]", "type_id": 0}},
                {"Sequence": {"id": "A", "type_id": 0}},
                {"SpecialToken": {"id": "[SEP]", "type_id": 0}}
            ]
        },
        "added_tokens": []
    }), encoding="utf-8")

    config = root / CONFIG_RELATIVE
    config.write_text(json.dumps({
        "model_type": "distilbert",
        "num_labels": 2,
        "id2label": {"0": "NO_YO", "1": "YO"}
    }), encoding="utf-8")


def test_manifest_is_pinned_and_contains_only_yo_classifier_files():
    assert len(FILES) == 3
    assert all(str(path).startswith("nn_yo_homograph/") for path in FILES)
    assert len(REVISION) == 40
    assert REVISION in url_for(MODEL_RELATIVE)
    assert "main" not in url_for(MODEL_RELATIVE)


def test_label_map_requires_yo_class_but_preserves_other_names():
    assert validate_yo_label_map({"0": "NO_YO", "1": "YO"}) == {"0": "NO_YO", "1": "YO"}
    assert validate_yo_label_map({"0": "KEEP_E", "1": "YO", "2": "PUNCT"})["2"] == "PUNCT"
    with pytest.raises(ProbeError, match="no YO class"):
        validate_yo_label_map({"0": "NO_YO", "1": "PUNCT"})
    with pytest.raises(ProbeError, match="contiguous"):
        validate_yo_label_map({"0": "NO_YO", "2": "YO"})


def test_bundle_verifies_model_tokenizer_and_config(tmp_path):
    make_fixture(tmp_path)
    reports = validate_bundle(tmp_path)
    assert len(reports) == 3
    assert reports[0].relative_path == MODEL_RELATIVE.as_posix()
    assert len(reports[0].sha256) == 64
    assert "WordPiece" in reports[1].detail
    assert "YO" in reports[2].detail


def test_model_rejects_lfs_pointer_and_short_file(tmp_path):
    path = tmp_path / MODEL_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"version https://git-lfs.github.com/spec/v1\n" + b"0" * 100)
    with pytest.raises(ProbeError):
        validate_model(path)


def test_load_corpus_checks_schema_and_target_labels(tmp_path):
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps({
        "schema_version": 1,
        "cases": [{"id": "x", "text": "Он все знает.", "expect": [{"word": "все", "label": "YO"}]}]
    }), encoding="utf-8")
    assert load_corpus(corpus)["cases"][0]["id"] == "x"
    corpus.write_text(json.dumps({
        "schema_version": 1,
        "cases": [{"id": "x", "text": "Он все знает.", "expect": [{"word": "все", "label": "MAYBE"}]}]
    }), encoding="utf-8")
    with pytest.raises(ProbeError, match="YO or NO_YO"):
        load_corpus(corpus)


class FakeEncoding:
    def __init__(self):
        self.ids = [1, 3, 4, 5, 6, 2]
        self.attention_mask = [1, 1, 1, 1, 1, 1]


class FakeTokenizer:
    def encode(self, text):
        assert text == "он все знает."
        return FakeEncoding()


class FakeMeta:
    def __init__(self, name, shape, type_):
        self.name, self.shape, self.type = name, shape, type_


class FakeSession:
    def get_inputs(self):
        return [
            FakeMeta("input_ids", [1, 6], "tensor(int64)"),
            FakeMeta("attention_mask", [1, 6], "tensor(int64)"),
        ]

    def get_outputs(self):
        return [FakeMeta("logits", [1, 6, 2], "tensor(float)")]

    def run(self, _, feeds):
        assert feeds["input_ids"].shape == (1, 6)
        # [CLS], он, все, знает, ., [SEP]. The target 
        logits = np.asarray([[[0.0, 0.0], [6.0, 0.0], [0.0, 6.0], [6.0, 0.0], [6.0, 0.0], [0.0, 0.0]]], dtype=np.float32)
        return [logits]


def test_real_probe_path_aggregates_wordpiece_scores_and_reports_yo():
    spec = {
        "model": {
            "type": "WordPiece",
            "vocab": {"[UNK]": 0, "[CLS]": 1, "[SEP]": 2, "он": 3, "все": 4, "знает": 5, ".": 6},
            "continuing_subword_prefix": "##",
        },
        "post_processor": {
            "single": [
                {"SpecialToken": {"id": "[CLS]", "type_id": 0}},
                {"Sequence": {"id": "A", "type_id": 0}},
                {"SpecialToken": {"id": "[SEP]", "type_id": 0}},
            ]
        },
        "added_tokens": [],
    }
    result = run_probe("Он все знает.", FakeSession(), FakeTokenizer(), spec, {"0": "NO_YO", "1": "YO"})
    target = next(item for item in result["word_labels"] if item["word"] == "все")
    assert target["label"] == "YO"
    assert target["raw_label"] == "YO"
    assert target["confidence"] > 0.99


def test_evaluator_reports_match_mismatch_and_missing():
    corpus = {
        "name": "test",
        "cases": [{
            "id": "case-1",
            "text": "Он все знает.",
            "expect": [
                {"word": "все", "label": "YO"},
                {"word": "он", "label": "NO_YO"},
                {"word": "потом", "label": "NO_YO"},
            ],
        }],
    }

    def fake_probe(_text):
        return {"word_labels": [
            {"word": "он", "label": "NO_YO", "confidence": 0.99},
            {"word": "все", "label": "YO", "confidence": 0.98},
        ]}

    report = evaluate_cases(corpus, fake_probe)
    assert report["total_checks"] == 3
    assert report["passed"] == 2
    assert report["missing"] == 1
    assert report["mismatches"] == 0


def test_smoke_corpus_has_documented_contextual_pair():
    corpus = load_corpus(Path(__file__).parents[1] / "data" / "ruaccent_yo_smoke.json")
    by_id = {case["id"]: case for case in corpus["cases"]}
    assert by_id["all-people-no-yo"]["expect"][0]["label"] == "NO_YO"
    assert by_id["everything-yo"]["expect"][0]["label"] == "YO"
