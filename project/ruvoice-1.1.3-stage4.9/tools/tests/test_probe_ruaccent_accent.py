import gzip
import json
from pathlib import Path

import numpy as np
import pytest

from tools.probe_ruaccent_accent import (
    ACCENTS_RELATIVE, BOS_ID, CHAR_STRESS_CONFIDENCE, CONFIG_RELATIVE,
    EOS_ID, FILES, MODEL_RELATIVE, REVISION, UNK_ID, VOCAB_RELATIVE,
    CharAccentProbe, ProbeError, load_accent_dictionary, url_for,
    run_smoke, validate_bundle, validate_labels, validate_onnx, validate_session_signature,
    validate_vocab,
)


class Meta:
    def __init__(self, name, shape, type_="tensor(int64)"):
        self.name, self.shape, self.type = name, shape, type_


class FakeSession:
    def __init__(self, rows=None, class_count=2, output_shape=None, input_names=None, input_type="tensor(int64)"):
        self.rows = rows or {}
        self.class_count = class_count
        self.output_shape = output_shape or [1, None, class_count]
        self.input_names = input_names or ["input_ids", "attention_mask", "token_type_ids"]
        self.input_type = input_type
        self.seen = []

    def get_inputs(self):
        return [Meta(name, [1, None], self.input_type) for name in self.input_names]

    def get_outputs(self):
        return [Meta("logits", self.output_shape, "tensor(float)")]

    def run(self, _, feeds):
        self.seen.append(feeds)
        ids = feeds["input_ids"][0]
        logits = np.zeros((1, len(ids), self.class_count), dtype=np.float32)
        # rows maps input-position to the logit margin in favour of STRESS_PRIMARY (id 1).
        for position, margin in self.rows.items():
            logits[0, position, 1] = margin
        return [logits]


VOCAB = ["[pad]", "[unk]", "[bos]", "[eos]", *list("абвгдеёжзийклмнопрстуфхцчшщъыьэюя")]
LABELS = {0: "O", 1: "STRESS_PRIMARY"}


def make_bundle(root: Path):
    model = root / MODEL_RELATIVE
    model.parent.mkdir(parents=True, exist_ok=True)
    with model.open("wb") as stream:
        stream.write(b"\x08\x08")
        stream.truncate(100 * 1024 + 1)
    vocab = root / VOCAB_RELATIVE
    vocab.parent.mkdir(parents=True, exist_ok=True)
    vocab.write_text("\n".join(VOCAB) + "\n", encoding="utf-8")
    config = root / CONFIG_RELATIVE
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"id2label": {"0": "O", "1": "STRESS_PRIMARY"}}), encoding="utf-8")
    dictionary = root / ACCENTS_RELATIVE
    dictionary.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(dictionary, "wt", encoding="utf-8") as stream:
        json.dump({"молоко": "молок+о", "корова": "кор+ова"}, stream, ensure_ascii=False)


def test_manifest_is_commit_pinned_and_contains_only_expected_artifacts():
    assert len(REVISION) == 40
    assert FILES == (MODEL_RELATIVE, VOCAB_RELATIVE, CONFIG_RELATIVE, ACCENTS_RELATIVE)
    assert url_for(MODEL_RELATIVE).endswith("/ru_ruaccent/nn_accent/model.onnx")
    with pytest.raises(ValueError):
        url_for(Path("nn_accent/tokenizer.json"))


def test_char_vocab_uses_reference_special_ids_and_all_russian_vowels(tmp_path):
    path = tmp_path / "vocab.txt"
    path.write_text("\n".join(VOCAB) + "\n", encoding="utf-8")
    vocab, detail = validate_vocab(path)
    assert vocab[BOS_ID] == "[bos]" and vocab[EOS_ID] == "[eos]" and vocab[UNK_ID] == "[unk]"
    assert "vowel chars=10" in detail


def test_vocab_rejects_duplicate_or_missing_vowels(tmp_path):
    path = tmp_path / "vocab.txt"
    path.write_text("\n".join(VOCAB + ["а"]) + "\n", encoding="utf-8")
    with pytest.raises(ProbeError, match="duplicate"):
        validate_vocab(path)
    path.write_text("\n".join(VOCAB[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(ProbeError, match="all 10 Russian vowels"):
        validate_vocab(path)


def test_label_config_requires_contiguous_ids_and_primary_stress(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"id2label": {"0": "O", "1": "STRESS_PRIMARY"}}), encoding="utf-8")
    labels, _ = validate_labels(path)
    assert labels == LABELS
    path.write_text(json.dumps({"id2label": {"0": "O", "2": "STRESS_PRIMARY"}}), encoding="utf-8")
    with pytest.raises(ProbeError, match="contiguous"):
        validate_labels(path)
    path.write_text(json.dumps({"id2label": {"0": "O", "1": "OTHER"}}), encoding="utf-8")
    with pytest.raises(ProbeError, match="STRESS_PRIMARY"):
        validate_labels(path)


def test_accent_dictionary_validates_plus_notation(tmp_path):
    path = tmp_path / "accents.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        json.dump({"молоко": "молок+о", "корова": "кор+ова"}, stream, ensure_ascii=False)
    words, detail = load_accent_dictionary(path)
    assert words["молоко"] == "молок+о"
    assert "entries=2" in detail
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        json.dump({"молоко": "молок+а"}, stream, ensure_ascii=False)
    with pytest.raises(ProbeError, match="spelling mismatch"):
        load_accent_dictionary(path)


def test_bundle_validator_checks_four_artifacts(tmp_path):
    make_bundle(tmp_path)
    reports = validate_bundle(tmp_path)
    assert tuple(Path(r.relative_path) for r in reports) == FILES
    assert all(len(report.sha256) == 64 for report in reports)


def test_session_signature_requires_three_int64_character_inputs():
    signature = validate_session_signature(FakeSession(), LABELS)
    assert signature["input_names"] == ["input_ids", "attention_mask", "token_type_ids"]
    with pytest.raises(ProbeError, match="missing required inputs"):
        validate_session_signature(FakeSession(input_names=["input_ids", "attention_mask"]), LABELS)
    with pytest.raises(ProbeError, match=r"tensor\(int64\)"):
        validate_session_signature(FakeSession(input_type="tensor(float)"), LABELS)
    with pytest.raises(ProbeError, match="char-level logits"):
        validate_session_signature(FakeSession(output_shape=[1, 5]), LABELS)


def test_char_model_selects_the_highest_confidence_stressed_vowel_and_inserts_acute():
    # корова: first 'о' is input row 2, second 'о' is row 4.
    session = FakeSession(rows={2: 2.0, 4: 5.0})
    probe = CharAccentProbe(session, VOCAB, LABELS)
    result = probe.predict("корова")
    assert result["marked"] == "коро\u0301ва"
    assert result["selected"]["char_index"] == 3
    assert session.seen[0]["input_ids"].dtype == np.int64
    assert session.seen[0]["input_ids"].tolist()[0][0] == BOS_ID
    assert session.seen[0]["input_ids"].tolist()[0][-1] == EOS_ID


def test_char_model_does_not_mark_non_vowel_or_low_confidence_positions():
    # Confident stress on 'р' is ignored; small margin on 'о' is below 0.55.
    session = FakeSession(rows={3: 7.0, 2: 0.01})
    probe = CharAccentProbe(session, VOCAB, LABELS)
    result = probe.predict("корова")
    assert result["marked"] is None


def test_unknown_character_uses_unk_id_and_input_is_one_russian_word():
    vocab_without_tse = [token for token in VOCAB if token != "ц"]
    probe = CharAccentProbe(FakeSession(), vocab_without_tse, LABELS)
    result = probe.predict("циркуляция")
    assert result["model_input_ids"][1] == UNK_ID
    with pytest.raises(ProbeError, match="only Russian"):
        probe.predict("коffee")
    with pytest.raises(ProbeError, match="one non-empty token"):
        probe.predict("две коровы")


def test_confidence_threshold_is_configurable_but_validated():
    with pytest.raises(ProbeError, match="between 0 and 1"):
        CharAccentProbe(FakeSession(), VOCAB, LABELS, min_confidence=1.0)
    assert CharAccentProbe(FakeSession(), VOCAB, LABELS, min_confidence=0.7).min_confidence == 0.7


def test_smoke_uses_one_session_for_multiple_words_and_flags_runtime_oov_path(tmp_path):
    make_bundle(tmp_path)
    words_path = tmp_path / "smoke.json"
    words_path.write_text(json.dumps([{"word": "корова"}, {"word": "молоко"}, {"word": "интерпретация"}]), encoding="utf-8")
    created = []

    def session_factory(_model_path):
        session = FakeSession(rows={2: 5.0})
        created.append(session)
        return session

    results = run_smoke(tmp_path, words_path, session_factory=session_factory)
    assert len(created) == 1
    assert len(created[0].seen) == 3
    assert results[0]["runtime_would_use_char_model"] is False  # present in dictionary
    assert results[1]["runtime_would_use_char_model"] is False  # present in dictionary
    assert results[2]["runtime_would_use_char_model"] is True   # OOV, multi-vowel word
