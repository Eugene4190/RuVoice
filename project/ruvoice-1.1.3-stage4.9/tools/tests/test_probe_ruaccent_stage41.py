import json
from pathlib import Path

import pytest

from tools.probe_ruaccent_stage41 import (
    FILES,
    MIN_ONNX_BYTES,
    MODEL_RELATIVE,
    REVISION,
    TOKENIZER_RELATIVE,
    CONFIG_RELATIVE,
    url_for,
    validate_bundle,
    validate_model,
)


def make_fixture(root: Path) -> None:
    model = root / MODEL_RELATIVE
    model.parent.mkdir(parents=True, exist_ok=True)
    # Large enough to exercise the size guard; synthetic, not an executable model.
    with model.open("wb") as stream:
        stream.write(b"\x08\x08")
        stream.truncate(MIN_ONNX_BYTES + 1)

    tokenizer = root / TOKENIZER_RELATIVE
    tokenizer.parent.mkdir(parents=True, exist_ok=True)
    tokenizer.write_text(json.dumps({
        "version": "1.0",
        "model": {"type": "WordPiece", "vocab": {"[UNK]": 0, "тест": 1}},
        "pre_tokenizer": {"type": "BertPreTokenizer"},
    }), encoding="utf-8")

    config = root / CONFIG_RELATIVE
    config.write_text(json.dumps({
        "model_type": "bert",
        "num_labels": 3,
        "id2label": {"0": "NO_STRESS", "1": "PUNCT", "2": "STRESS"},
    }), encoding="utf-8")


def test_manifest_is_commit_pinned_and_limited_to_first_stage():
    assert len(FILES) == 3
    assert all(str(path).startswith("nn_stress_usage/") for path in FILES)
    assert len(REVISION) == 40
    assert REVISION in url_for(MODEL_RELATIVE)
    assert "main" not in url_for(MODEL_RELATIVE)


def test_bundle_verifies_local_artifacts(tmp_path):
    make_fixture(tmp_path)
    reports = validate_bundle(tmp_path)
    assert len(reports) == 3
    assert reports[0].relative_path == MODEL_RELATIVE.as_posix()
    assert len(reports[0].sha256) == 64
    assert "vocab entries=2" in reports[1].detail
    assert "STRESS" in reports[2].detail


def test_model_rejects_small_or_lfs_pointer(tmp_path):
    model = tmp_path / MODEL_RELATIVE
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"version https://git-lfs.github.com/spec/v1\n" + b"0" * 100)
    with pytest.raises(ValueError):
        validate_model(model)


def test_config_rejects_wrong_label_map(tmp_path):
    make_fixture(tmp_path)
    config = tmp_path / CONFIG_RELATIVE
    config.write_text(json.dumps({"id2label": {"0": "LABEL_0", "1": "LABEL_1"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="Unexpected stress classifier labels"):
        validate_bundle(tmp_path)
