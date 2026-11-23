import gzip
import json
from pathlib import Path

import numpy as np
import pytest

from tools.probe_ruaccent_omograph import (
    CONTEXT_WORDS,
    DICTIONARY_RELATIVE,
    FILES,
    MAX_TOKENS,
    MIN_ONNX_BYTES,
    MODEL_RELATIVE,
    REVISION,
    TOKENIZER_RELATIVE,
    ProbeError,
    acute_to_plus,
    evaluate_dataset,
    load_dictionary,
    score_candidates,
    url_for,
    validate_bundle,
    validate_omograph_dictionary,
    validate_onnx_file,
    validate_session_signature,
    validate_tokenizer,
)


def make_bundle(root: Path):
    model = root / MODEL_RELATIVE
    model.parent.mkdir(parents=True, exist_ok=True)
    with model.open("wb") as stream:
        stream.write(b"\x08\x08")
        stream.truncate(MIN_ONNX_BYTES + 1)

    tokenizer = root / TOKENIZER_RELATIVE
    tokenizer.parent.mkdir(parents=True, exist_ok=True)
    tokenizer.write_text(json.dumps({
        "version": "1.0",
        "model": {"type": "BPE", "vocab": {"<w>": 0, "</w>": 1, "замок": 2}, "merges": ["з а", "а м"]},
        "added_tokens": [
            {"id": 0, "content": "<w>", "special": True},
            {"id": 1, "content": "</w>", "special": True},
        ],
        "pre_tokenizer": {"type": "ByteLevel", "add_prefix_space": False},
        "post_processor": {"type": "RobertaProcessing", "sep": ["</s>", 3], "cls": ["<s>", 4]},
    }, ensure_ascii=False), encoding="utf-8")

    dictionary = root / DICTIONARY_RELATIVE
    dictionary.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(dictionary, "wt", encoding="utf-8") as stream:
        json.dump({
            "замок": ["з+амок", "зам+ок"],
            "мука": ["м+ука", "мук+а"],
        }, stream, ensure_ascii=False)


class FakeEncoding:
    def __init__(self, ids, pair):
        self.ids = ids
        self.attention_mask = [1] * len(ids)
        self.type_ids = [0] + [1] * (len(ids) - 2) + [1]
        self.pair = pair


class FakeTokenizer:
    def __init__(self, tokens_per_word=1):
        self.tokens_per_word = tokens_per_word
        self.calls = []

    def encode(self, text, pair=None):
        self.calls.append((text, pair))
        premise_tokens = len(text.split()) * self.tokens_per_word
        hypothesis_tokens = len(pair.split()) if pair else 0
        ids = [101] + [500 + (sum((i + 1) * ord(c) for i, c in enumerate(pair or "")) % 1000)] * max(1, premise_tokens + hypothesis_tokens) + [102]
        return FakeEncoding(ids, pair)


class Meta:
    def __init__(self, name, shape, type_="tensor(int64)"):
        self.name = name
        self.shape = shape
        self.type = type_


class FakeSession:
    def __init__(self, entailment_by_candidate, with_tti=False, output_shape=(1, 2)):
        self.entailment_by_candidate = entailment_by_candidate
        self.with_tti = with_tti
        self.output_shape = list(output_shape)
        self.seen = []

    def get_inputs(self):
        values = [Meta("input_ids", [1, None]), Meta("attention_mask", [1, None])]
        if self.with_tti:
            values.append(Meta("token_type_ids", [1, None]))
        return values

    def get_outputs(self):
        return [Meta("logits", self.output_shape, "tensor(float)")]

    def run(self, _, feeds):
        self.seen.append(feeds)
        if self.with_tti:
            assert "token_type_ids" in feeds
        else:
            assert "token_type_ids" not in feeds
        token_id = int(feeds["input_ids"][0][1])
        candidate = next(
            key for key in self.entailment_by_candidate
            if 500 + (sum((i + 1) * ord(c) for i, c in enumerate(key)) % 1000) == token_id
        )
        score = self.entailment_by_candidate[candidate]
        class_count = self.output_shape[-1] if len(self.output_shape) == 2 else 2
        logits = [0.0, score] + [-1.0] * max(0, class_count - 2)
        return [np.asarray([logits], dtype=np.float32)]


def test_manifest_is_pinned_and_only_contains_omograph_bundle_files():
    assert len(REVISION) == 40
    assert FILES == (MODEL_RELATIVE, TOKENIZER_RELATIVE, DICTIONARY_RELATIVE)
    assert url_for(MODEL_RELATIVE).endswith("/ru_ruaccent/nn_omograph/model.int8.onnx")
    with pytest.raises(ValueError):
        url_for(Path("nn_omograph/config.json"))


def test_dictionary_validator_accepts_stressed_variants():
    dictionary, counts = validate_omograph_dictionary({
        "замок": ["з+амок", "зам+ок"],
        "слова": ["сл+ова", "слов+а"],
    })
    assert dictionary["замок"] == ["з+амок", "зам+ок"]
    assert counts == {"words": 2, "variants": 4}


def test_dictionary_validator_rejects_spelling_change_or_bad_stress():
    with pytest.raises(ProbeError, match="changes the word spelling"):
        validate_omograph_dictionary({"замок": ["з+амок", "з+амка"]})
    with pytest.raises(ProbeError, match="invalid stress notation"):
        validate_omograph_dictionary({"замок": ["з+амок", "замо+к"]})
    with pytest.raises(ProbeError, match="at least two"):
        validate_omograph_dictionary({"замок": ["з+амок"]})


def test_tokenizer_requires_bpe_and_trained_word_markers(tmp_path):
    path = tmp_path / "tokenizer.json"
    make_bundle(tmp_path)
    spec, detail = validate_tokenizer(tmp_path / TOKENIZER_RELATIVE)
    assert spec["model"]["type"] == "BPE"
    assert "markers" in detail

    spec["model"]["type"] = "WordPiece"
    path.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(ProbeError, match="expected to use BPE"):
        validate_tokenizer(path)


def test_bundle_validator_checks_all_three_real_artifact_paths(tmp_path):
    make_bundle(tmp_path)
    reports = validate_bundle(tmp_path)
    assert [item.relative_path for item in reports] == [
        MODEL_RELATIVE.as_posix(), TOKENIZER_RELATIVE.as_posix(), DICTIONARY_RELATIVE.as_posix()
    ]
    assert all(len(item.sha256) == 64 for item in reports)
    assert "valid words=2" in reports[2].detail


def test_onnx_validator_rejects_lfs_pointer_and_small_file(tmp_path):
    path = tmp_path / "model.onnx"
    path.write_bytes(b"version https://git-lfs.github.com/spec/v1\n" + b"0" * 64)
    with pytest.raises(ProbeError):
        validate_onnx_file(path)
    path.write_bytes(b"\x08\x08")
    with pytest.raises(ProbeError, match="unexpectedly small"):
        validate_onnx_file(path)


def test_nli_signature_accepts_roberta_inputs_without_token_type_ids():
    signature = validate_session_signature(FakeSession({"з+амок": 5.0, "зам+ок": 1.0}))
    assert signature["input_names"] == ["input_ids", "attention_mask"]
    assert signature["entailment_class_index"] == 1


def test_nli_signature_also_supports_bert_segment_ids():
    signature = validate_session_signature(FakeSession({"з+амок": 5.0}, with_tti=True))
    assert "token_type_ids" in signature["input_names"]


def test_nli_signature_rejects_token_classification_output_shape():
    with pytest.raises(ProbeError, match="sequence-classification logits"):
        validate_session_signature(FakeSession({"з+амок": 5.0}, output_shape=(1, 5, 2)))


def test_nli_signature_accepts_three_class_sequence_classifier():
    signature = validate_session_signature(FakeSession({"з+амок": 5.0}, output_shape=(1, 3)))
    assert signature["output_shape"] == [1, 3]


def test_probe_uses_entailment_class_one_for_three_class_output():
    tokenizer = FakeTokenizer()
    session = FakeSession({"з+амок": 5.0, "зам+ок": 1.0}, output_shape=(1, 3))
    result = score_candidates(
        "На двери висел замок.", "замок", 0, ["з+амок", "зам+ок"], session, tokenizer
    )
    scores = result["candidates"]
    assert len(scores[0]["class_probabilities"]) == 3
    assert scores[0]["entailment_probability"] == scores[0]["class_probabilities"][1]
    assert scores[0]["entailment_probability"] > scores[1]["entailment_probability"]


def test_probe_marks_target_and_chooses_highest_entailment_candidate():
    tokenizer = FakeTokenizer()
    session = FakeSession({"з+амок": 6.0, "зам+ок": 1.0})
    result = score_candidates(
        "На двери висел замок, а на холме стоял замок.",
        "замок", 0, ["з+амок", "зам+ок"], session, tokenizer,
    )
    assert result["predicted_candidate"] == "з+амок"
    assert result["context_radius_words"] == CONTEXT_WORDS
    premise = result["candidates"][0]["premise"]
    assert "<w>замок</w>" in premise and "," in premise
    assert premise.index("</w>") < premise.index(",")
    assert result["candidates"][0]["entailment_probability"] > result["candidates"][1]["entailment_probability"]


def test_probe_can_select_second_occurrence():
    tokenizer = FakeTokenizer()
    session = FakeSession({"з+амок": 1.0, "зам+ок": 6.0})
    result = score_candidates(
        "На двери висел замок, а на холме стоял замок.",
        "замок", 1, ["з+амок", "зам+ок"], session, tokenizer,
    )
    assert result["target_token_index"] > 0
    premise = result["candidates"][0]["premise"]
    assert "стоял <w>замок</w>" in premise and "." in premise
    assert premise.index("</w>") < premise.index(".")


def test_probe_shrinks_long_context_instead_of_truncating():
    tokenizer = FakeTokenizer(tokens_per_word=5)
    session = FakeSession({"з+амок": 5.0, "зам+ок": 1.0})
    words = ["слово"] * 160
    words[80] = "замок"
    result = score_candidates(" ".join(words), "замок", 0, ["з+амок", "зам+ок"], session, tokenizer)
    assert result["context_radius_words"] < CONTEXT_WORDS
    assert max(item["token_count"] for item in result["candidates"]) <= MAX_TOKENS


def test_probe_refuses_overlong_pair_even_with_target_only_context():
    tokenizer = FakeTokenizer(tokens_per_word=600)
    session = FakeSession({"з+амок": 5.0, "зам+ок": 1.0})
    with pytest.raises(ProbeError, match="refusing silent truncation"):
        score_candidates("замок", "замок", 0, ["з+амок", "зам+ок"], session, tokenizer)


def test_probe_rejects_absent_target_and_invalid_candidate():
    tokenizer = FakeTokenizer()
    session = FakeSession({"з+амок": 5.0, "зам+ок": 1.0})
    with pytest.raises(ProbeError, match="not found"):
        score_candidates("Старый замок.", "мука", 0, ["м+ука", "мук+а"], session, tokenizer)
    with pytest.raises(ProbeError, match="does not match target"):
        score_candidates("Старый замок.", "замок", 0, ["з+амок", "з+амка"], session, tokenizer)


def test_acute_to_plus_converts_dataset_gold_notation():
    assert acute_to_plus("сло́ва") == "сл+ова"
    assert acute_to_plus("Замо́к") == "зам+ок"
    with pytest.raises(ProbeError, match="Malformed"):
        acute_to_plus("\u0301слово")


def test_evaluator_compares_gold_and_skips_uncovered_dictionary_entries():
    dictionary = {"замок": ["з+амок", "зам+ок"]}
    dataset = [
        {"id": 1, "context": "Старинный замок стоял.", "homograph": "за́мок"},
        {"id": 2, "context": "Он запер замок.", "homograph": "замо́к"},
        {"id": 3, "context": "Он просеял муку.", "homograph": "му́ку"},
    ]
    def fake_probe(text, target, occurrence, candidates):
        return {"predicted_candidate": "з+амок" if "Старинный" in text else "зам+ок", "candidates": []}
    report = evaluate_dataset(dataset, dictionary, fake_probe)
    assert report["metrics"]["checked"] == 2
    assert report["metrics"]["correct"] == 2
    assert report["metrics"]["missing_dictionary"] == 1
    assert report["accuracy_percent"] == 100.0


def test_project_homograph_dataset_has_expected_shape():
    dataset_path = Path(__file__).parents[2] / "app/src/test/resources/homograph_eval/HomographResolutionEval.json"
    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    assert len(data) == 1741
    assert all("context" in row and "homograph" in row for row in data)
