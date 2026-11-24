import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tools.probe_ruaccent_stress_usage import (
    ProbeError,
    _pretoken_spans,
    _wordpiece_word_ids,
    aggregate_word_labels,
    normalize_ruaccent_text,
    run_probe,
    validate_session_signature,
    validate_stress_label_map,
)


def tokenizer_spec():
    vocab = {
        "[CLS]": 0, "[SEP]": 1, "[UNK]": 2,
        "привет": 3, "##ств": 4, "мир": 5, ",": 6, ".": 7,
        "замок": 8,
    }
    return {
        "model": {
            "type": "WordPiece",
            "vocab": vocab,
            "continuing_subword_prefix": "##",
        },
        "post_processor": {
            "single": [
                {"SpecialToken": {"id": "[CLS]", "type_id": 0}},
                {"Sequence": {"id": "A", "type_id": 0}},
                {"SpecialToken": {"id": "[SEP]", "type_id": 0}},
            ]
        },
        "added_tokens": [
            {"id": 0, "content": "[CLS]"},
            {"id": 1, "content": "[SEP]"},
        ],
    }


class FakeEncoding:
    def __init__(self, ids):
        self.ids = ids
        self.attention_mask = [1] * len(ids)
        self.type_ids = [0] * len(ids)


class FakeTokenizer:
    def encode(self, text):
        # [CLS] привет + ##ств , мир . [SEP]
        return FakeEncoding([0, 3, 4, 6, 5, 7, 1])


class FakeSession:
    def __init__(self, logits):
        self.logits = np.asarray(logits, dtype=np.float32)
        self.last_feeds = None

    def get_inputs(self):
        return [
            SimpleNamespace(name="input_ids", type="tensor(int64)", shape=[1, "sequence"]),
            SimpleNamespace(name="attention_mask", type="tensor(int64)", shape=[1, "sequence"]),
            SimpleNamespace(name="token_type_ids", type="tensor(int64)", shape=[1, "sequence"]),
        ]

    def get_outputs(self):
        return [SimpleNamespace(name="logits", shape=[1, "sequence", 2])]

    def run(self, output_names, feeds):
        self.last_feeds = feeds
        return [self.logits]


def test_normalization_matches_ruaccent_allow_list():
    assert normalize_ruaccent_text("Привет, мир! 😀 №5") == "Привет, мир!  5"


def test_wordpiece_ids_group_continuations_and_skip_special_tokens():
    ids = [0, 3, 4, 6, 5, 7, 1]
    assert _wordpiece_word_ids(ids, tokenizer_spec()) == [None, 0, 0, 1, 2, 3, None]


def test_pretokenizer_uses_bert_like_word_and_punctuation_spans():
    spans = _pretoken_spans("Привет, мир.", tokenizer_spec())
    assert ["Привет, мир."[a:b] for a, b in spans] == ["Привет", ",", "мир", "."]


def test_aggregate_probabilities_averages_subwords_per_word():
    text = "Привет, мир."
    probs = np.asarray([
        [0.01, 0.99],  # CLS ignored
        [0.80, 0.20],  # привет
        [0.30, 0.70],  # ##ств; average for word => class 0 wins
        [0.90, 0.10],  # comma
        [0.10, 0.90],  # мир
        [0.80, 0.20],  # period
        [0.01, 0.99],  # SEP ignored
    ], dtype=np.float32)
    result = aggregate_word_labels(
        text,
        probs,
        _wordpiece_word_ids([0, 3, 4, 6, 5, 7, 1], tokenizer_spec()),
        _pretoken_spans(text, tokenizer_spec()),
        {"0": "NO_STRESS", "1": "STRESS"},
    )
    assert [x["word"] for x in result] == ["Привет", ",", "мир", "."]
    assert result[0]["label"] == "NO_STRESS"
    assert result[2]["label"] == "STRESS"
    assert result[0]["subword_count"] == 2


def test_real_probe_path_builds_int64_feed_and_classifies_words():
    # Make the per-token logits: class 0 for first word, class 1 for third word.
    logits = np.zeros((1, 7, 2), dtype=np.float32)
    logits[0, 1] = [3.0, 0.0]
    logits[0, 2] = [3.0, 0.0]
    logits[0, 3] = [0.0, 2.0]
    logits[0, 4] = [0.0, 3.0]
    logits[0, 5] = [2.0, 0.0]
    session = FakeSession(logits)
    result = run_probe(
        "Привет, мир.", session, FakeTokenizer(), tokenizer_spec(),
        {"0": "NO_STRESS", "1": "STRESS"},
    )
    assert result["word_labels"][0]["label"] == "NO_STRESS"
    assert result["word_labels"][2]["label"] == "STRESS"
    assert set(session.last_feeds) == {"input_ids", "attention_mask", "token_type_ids"}
    assert session.last_feeds["input_ids"].dtype == np.int64
    assert result["token_count"] == 7


def test_session_rejects_missing_or_wrong_input_types():
    class BadSession(FakeSession):
        def get_inputs(self):
            return [SimpleNamespace(name="input_ids", type="tensor(float)", shape=[1, "seq"])]
    with pytest.raises(ProbeError, match="missing required inputs"):
        validate_session_signature(BadSession(np.zeros((1, 1, 2))), 2)


def test_probe_rejects_output_sequence_mismatch():
    session = FakeSession(np.zeros((1, 6, 2), dtype=np.float32))
    with pytest.raises(ProbeError, match="token rows"):
        run_probe(
            "Привет, мир.", session, FakeTokenizer(), tokenizer_spec(),
            {"0": "NO_STRESS", "1": "STRESS"},
        )


def test_probe_refuses_to_silently_truncate_overlong_input():
    class LongTokenizer(FakeTokenizer):
        def encode(self, text):
            return FakeEncoding([0] + [3] * 512 + [1])
    session = FakeSession(np.zeros((1, 514, 2), dtype=np.float32))
    with pytest.raises(ProbeError, match="rather than silently truncating"):
        run_probe(
            "очень длинный текст", session, LongTokenizer(), tokenizer_spec(),
            {"0": "NO_STRESS", "1": "STRESS"},
        )


def test_stress_label_map_accepts_optional_punctuation_class():
    labels = validate_stress_label_map({
        "0": "NO_STRESS",
        "1": "PUNCT",
        "2": "STRESS",
    })
    assert labels == {
        "0": "NO_STRESS",
        "1": "PUNCT",
        "2": "STRESS",
    }


def test_stress_label_map_rejects_missing_stress_class():
    with pytest.raises(ProbeError, match="must define STRESS/NO_STRESS"):
        validate_stress_label_map({"0": "NO_STRESS", "1": "PUNCT"})
