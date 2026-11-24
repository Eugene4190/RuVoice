#!/usr/bin/env python3
"""Run one real ONNX smoke test for RUAccent's nn_stress_usage model.

This stage tests the BERT classifier's STRESS/NO_STRESS word labels; the model
may also expose a PUNCT class for punctuation tokens. It does NOT place stress
on a vowel and does NOT resolve homographs. No Android app files or RuVoice runtime code are changed here.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import numpy as np

try:
    from .probe_ruaccent_stage41 import (
        CONFIG_RELATIVE, MODEL_RELATIVE, TOKENIZER_RELATIVE, _read_json, validate_bundle,
    )
except ImportError:  # Running as: python tools/probe_ruaccent_stress_usage.py
    from probe_ruaccent_stage41 import (
        CONFIG_RELATIVE, MODEL_RELATIVE, TOKENIZER_RELATIVE, _read_json, validate_bundle,
    )

MAX_TOKENS = 512
_RUACCENT_NORM = re.compile(
    r"[^a-zA-Z0-9\sа-яА-ЯёЁ—.,!?:;\"“”‘’(){}\[\]«»„\"\-]"
)
_RU_SPLIT_RE = re.compile(r"[\w\u0301]+|[^\w\s\u0301]+")


class ProbeError(RuntimeError):
    """The model bundle or inference signature is not usable by this probe."""


def normalize_ruaccent_text(text: str) -> str:
    """Mirror stressonnx's RUAccent allow-list normalization for the probe."""
    return _RUACCENT_NORM.sub("", text)


def load_tokenizer_spec(path: Path) -> dict[str, Any]:
    data = _read_json(path)
    model = data.get("model")
    if not isinstance(model, dict) or model.get("type") != "WordPiece":
        raise ProbeError("The stress-usage tokenizer must use a WordPiece model")
    vocab = model.get("vocab")
    if not isinstance(vocab, dict) or not vocab:
        raise ProbeError("The tokenizer has no WordPiece vocabulary")
    processor = data.get("post_processor")
    single = processor.get("single") if isinstance(processor, dict) else None
    if not isinstance(single, list) or not single:
        raise ProbeError("The tokenizer has no post_processor.single template")
    sequence_positions = [
        i for i, item in enumerate(single)
        if isinstance(item, dict) and "Sequence" in item
    ]
    if len(sequence_positions) != 1:
        raise ProbeError("Expected exactly one Sequence entry in tokenizer post-processor")
    model_prefix = model.get("continuing_subword_prefix")
    if not isinstance(model_prefix, str) or not model_prefix:
        raise ProbeError("WordPiece continuing_subword_prefix is missing")
    return data


def validate_stress_label_map(raw: Any) -> dict[str, str]:
    """Validate the two stress classes and optional punctuation class."""
    if not isinstance(raw, dict) or len(raw) not in {2, 3}:
        raise ProbeError("config.json id2label must define STRESS/NO_STRESS and optional PUNCT")
    normalized: dict[str, str] = {}
    for key, value in raw.items():
        try:
            numeric_key = str(int(key))
        except (TypeError, ValueError) as exc:
            raise ProbeError(f"Invalid id2label class index: {key!r}") from exc
        if not isinstance(value, str):
            raise ProbeError(f"Invalid id2label value for class {key!r}")
        normalized[numeric_key] = value.upper()
    if set(normalized) != {str(index) for index in range(len(normalized))}:
        raise ProbeError(f"Non-contiguous stress classifier labels: {normalized}")
    labels = set(normalized.values())
    required = {"STRESS", "NO_STRESS"}
    if not required.issubset(labels) or not labels.issubset(required | {"PUNCT"}):
        raise ProbeError(
            "nn_stress_usage must define STRESS/NO_STRESS and optional PUNCT; "
            f"got {normalized}"
        )
    return normalized


def _wordpiece_word_ids(token_ids: list[int], tokenizer_spec: dict[str, Any]) -> list[int | None]:
    """Reproduce stressonnx's WordPiece grouping without relying on Encoding.word_ids."""
    model = tokenizer_spec["model"]
    vocab: dict[str, int] = model["vocab"]
    continuation_prefix: str = model["continuing_subword_prefix"]
    continuation_ids = {
        int(token_id)
        for token, token_id in vocab.items()
        if token.startswith(continuation_prefix)
    }
    template = tokenizer_spec["post_processor"]["single"]
    sequence_index = next(
        i for i, item in enumerate(template)
        if isinstance(item, dict) and "Sequence" in item
    )
    leading_specials = sequence_index
    trailing_specials = len(template) - sequence_index - 1
    if len(token_ids) < leading_specials + trailing_specials:
        raise ProbeError("Tokenizer output is shorter than its special-token template")

    result: list[int | None] = [None] * len(token_ids)
    word_index = -1
    end = len(token_ids) - trailing_specials if trailing_specials else len(token_ids)
    for i in range(leading_specials, end):
        if token_ids[i] not in continuation_ids:
            word_index += 1
        result[i] = word_index
    return result


def _pretoken_spans(text: str, tokenizer_spec: dict[str, Any]) -> list[tuple[int, int]]:
    added = tokenizer_spec.get("added_tokens", [])
    added_contents = sorted(
        {
            item.get("content")
            for item in added
            if isinstance(item, dict) and isinstance(item.get("content"), str) and item.get("content")
        },
        key=len,
        reverse=True,
    )
    alternatives = [re.escape(item) for item in added_contents]
    alternatives.extend([r"\w+", r"[^\w\s]"])
    pattern = re.compile("|".join(alternatives))
    return [match.span() for match in pattern.finditer(text)]


def validate_session_signature(session: Any, num_labels: int) -> dict[str, Any]:
    inputs = {item.name: item for item in session.get_inputs()}
    missing = {"input_ids", "attention_mask"} - set(inputs)
    if missing:
        raise ProbeError(f"ONNX model is missing required inputs: {sorted(missing)}")
    unsupported = set(inputs) - {"input_ids", "attention_mask", "token_type_ids"}
    if unsupported:
        raise ProbeError(f"Unexpected ONNX inputs: {sorted(unsupported)}")
    for name, meta in inputs.items():
        if meta.type != "tensor(int64)":
            raise ProbeError(f"ONNX input {name!r} must be tensor(int64), got {meta.type!r}")

    outputs = session.get_outputs()
    if not outputs:
        raise ProbeError("ONNX model has no outputs")
    output = outputs[0]
    shape = list(output.shape)
    if len(shape) != 3:
        raise ProbeError(f"Expected token-classification logits [batch, sequence, labels], got {shape}")
    last_dim = shape[-1]
    if isinstance(last_dim, int) and last_dim != num_labels:
        raise ProbeError(f"ONNX output has {last_dim} labels, config declares {num_labels}")
    return {
        "input_names": list(inputs),
        "input_types": {name: meta.type for name, meta in inputs.items()},
        "output_name": output.name,
        "output_shape": shape,
        "num_labels": num_labels,
    }


def _softmax_rows(logits: np.ndarray) -> np.ndarray:
    logits = np.asarray(logits, dtype=np.float32)
    logits = logits - np.max(logits, axis=-1, keepdims=True)
    exp = np.exp(logits)
    denominator = np.sum(exp, axis=-1, keepdims=True)
    if np.any(denominator == 0) or not np.all(np.isfinite(denominator)):
        raise ProbeError("ONNX model returned invalid logits")
    return exp / denominator


def aggregate_word_labels(
    text: str,
    probabilities: np.ndarray,
    word_ids: list[int | None],
    pretoken_spans: list[tuple[int, int]],
    id2label: dict[str, str],
) -> list[dict[str, Any]]:
    """Average subword probabilities per RUAccent word and map labels to spans."""
    spans = list(_RU_SPLIT_RE.finditer(text))
    if probabilities.ndim != 2 or probabilities.shape[0] != len(word_ids):
        raise ProbeError("Logit/token alignment mismatch")
    if probabilities.shape[1] != len(id2label):
        raise ProbeError("Model label dimension does not match config.json")

    char_to_word: dict[int, int] = {}
    for word_index, match in enumerate(spans):
        for offset in range(match.start(), match.end()):
            char_to_word[offset] = word_index

    grouped: dict[int, list[np.ndarray]] = {}
    for token_index, tokenizer_word_id in enumerate(word_ids):
        if tokenizer_word_id is None or tokenizer_word_id >= len(pretoken_spans):
            continue
        pretoken_start = pretoken_spans[tokenizer_word_id][0]
        ru_word_index = char_to_word.get(pretoken_start)
        if ru_word_index is not None:
            grouped.setdefault(ru_word_index, []).append(probabilities[token_index])

    id_to_label = {int(key): str(value) for key, value in id2label.items()}
    results: list[dict[str, Any]] = []
    for word_index, match in enumerate(spans):
        pieces = grouped.get(word_index, [])
        if not pieces:
            results.append({
                "word": match.group(0), "label": None,
                "confidence": None, "subword_count": 0,
            })
            continue
        mean_probs = np.stack(pieces).mean(axis=0)
        class_id = int(mean_probs.argmax())
        label = id_to_label.get(class_id, f"LABEL_{class_id}")
        label_scores = {
            id_to_label.get(index, f"LABEL_{index}"): float(mean_probs[index])
            for index in range(len(mean_probs))
        }
        results.append({
            "word": match.group(0),
            "label": label,
            "confidence": float(mean_probs[class_id]),
            "label_scores": label_scores,
            "subword_count": len(pieces),
        })
    return results


def run_probe(text: str, session: Any, tokenizer: Any, tokenizer_spec: dict[str, Any], id2label: dict[str, str]) -> dict[str, Any]:
    normalized = normalize_ruaccent_text(text)
    if not normalized.strip():
        raise ProbeError("Input is empty after RUAccent normalization")
    encoding = tokenizer.encode(normalized)
    token_ids = list(encoding.ids)
    attention_mask = list(encoding.attention_mask)
    type_ids = list(encoding.type_ids)
    if not token_ids:
        raise ProbeError("Tokenizer returned no token IDs")
    if len(token_ids) > MAX_TOKENS:
        raise ProbeError(
            f"Sample has {len(token_ids)} tokens; this one-sentence probe accepts at most {MAX_TOKENS}. "
            "Use a shorter sentence rather than silently truncating it."
        )
    if not (len(token_ids) == len(attention_mask) == len(type_ids)):
        raise ProbeError("Tokenizer returned inconsistent ids/mask/type_ids lengths")

    signature = validate_session_signature(session, len(id2label))
    feeds: dict[str, np.ndarray] = {
        "input_ids": np.asarray([token_ids], dtype=np.int64),
        "attention_mask": np.asarray([attention_mask], dtype=np.int64),
    }
    if "token_type_ids" in signature["input_names"]:
        feeds["token_type_ids"] = np.asarray([type_ids], dtype=np.int64)

    raw_outputs = session.run(None, feeds)
    if not raw_outputs:
        raise ProbeError("ONNX Runtime returned no outputs")
    logits = np.asarray(raw_outputs[0])
    if logits.ndim != 3 or logits.shape[0] != 1:
        raise ProbeError(f"Expected logits shape [1, sequence, labels], got {list(logits.shape)}")
    if logits.shape[1] != len(token_ids):
        raise ProbeError(
            f"Model returned {logits.shape[1]} token rows for {len(token_ids)} input tokens"
        )
    if logits.shape[2] != len(id2label):
        raise ProbeError("Model output label count differs from config.json")

    probs = _softmax_rows(logits[0])
    word_ids = _wordpiece_word_ids(token_ids, tokenizer_spec)
    pretokens = _pretoken_spans(normalized, tokenizer_spec)
    words = aggregate_word_labels(normalized, probs, word_ids, pretokens, id2label)
    return {
        "input": text,
        "normalized_input": normalized,
        "token_count": len(token_ids),
        "onnx": signature,
        "word_labels": words,
        "note": (
            "nn_stress_usage predicts STRESS/NO_STRESS only; it does not choose "
            "the stressed vowel and does not resolve homograph readings."
        ),
    }


def load_probe_runtime(model_dir: Path) -> dict[str, Any]:
    """Load and validate the real ONNX runtime once for repeated probe calls."""
    validate_bundle(model_dir)
    tokenizer_path = model_dir / TOKENIZER_RELATIVE
    model_path = model_dir / MODEL_RELATIVE
    config_path = model_dir / CONFIG_RELATIVE
    tokenizer_spec = load_tokenizer_spec(tokenizer_path)
    config = _read_json(config_path)
    id2label = validate_stress_label_map(config.get("id2label"))

    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise ProbeError("Install ONNX Runtime: pip install onnxruntime") from exc
    try:
        from tokenizers import Tokenizer
    except ImportError as exc:
        raise ProbeError("Install Hugging Face tokenizers: pip install tokenizers") from exc

    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    session_options = ort.SessionOptions()
    # Keep this isolated preflight light on laptops; Android threading is a later stage.
    session_options.intra_op_num_threads = 1
    session_options.inter_op_num_threads = 1
    session = ort.InferenceSession(
        str(model_path),
        sess_options=session_options,
        providers=["CPUExecutionProvider"],
    )
    signature = validate_session_signature(session, len(id2label))
    return {
        "session": session,
        "tokenizer": tokenizer,
        "tokenizer_spec": tokenizer_spec,
        "id2label": id2label,
        "signature": signature,
    }


def probe_with_runtime(text: str, runtime: dict[str, Any]) -> dict[str, Any]:
    return run_probe(
        text,
        runtime["session"],
        runtime["tokenizer"],
        runtime["tokenizer_spec"],
        runtime["id2label"],
    )


def load_and_probe(model_dir: Path, text: str) -> dict[str, Any]:
    runtime = load_probe_runtime(model_dir)
    return probe_with_runtime(text, runtime)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_directory", type=Path, help="directory produced by stage 4.1 downloader")
    parser.add_argument(
        "--text", default="В замке за дверью сломался замок.",
        help="one Russian sentence to pass through the stress-usage classifier",
    )
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args(argv)

    try:
        result = load_and_probe(args.model_directory, args.text)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Input: {result['input']}")
            print(f"Normalized: {result['normalized_input']}")
            print(f"Tokens: {result['token_count']}")
            print("Word labels:")
            for item in result["word_labels"]:
                confidence = "n/a" if item["confidence"] is None else f"{item['confidence']:.3f}"
                print(f"  {item['word']:<18} {str(item['label']):<12} confidence={confidence}")
            print(f"\nNOTE: {result['note']}")
        return 0
    except (OSError, ValueError, ProbeError, KeyError, TypeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
