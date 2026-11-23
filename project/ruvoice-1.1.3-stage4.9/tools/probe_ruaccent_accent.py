#!/usr/bin/env python3
"""Download, validate and probe RUAccent's char-level nn_accent model.

This preflight is intentionally standalone: it does not change Android or the
TTS path. It reproduces the narrow _put_accent() contract from stressonnx:
BOS=2, UNK=1, EOS=3; character-level logits; one highest-confidence primary
stress on a Russian vowel if its confidence reaches the configured threshold.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

REPOSITORY = "TigreGotico/stressonnx-models"
REVISION = "cb1594ddf81928e678a3a7ee7a22415e6e3a218f"
BUNDLE = "ru_ruaccent"
MODEL_RELATIVE = Path("nn_accent/model.onnx")
VOCAB_RELATIVE = Path("nn_accent/vocab.txt")
CONFIG_RELATIVE = Path("nn_accent/config.json")
ACCENTS_RELATIVE = Path("dictionary/accents_nn.json.gz")
FILES = (MODEL_RELATIVE, VOCAB_RELATIVE, CONFIG_RELATIVE, ACCENTS_RELATIVE)
MIN_ONNX_BYTES = 100 * 1024  # model is documented at roughly 0.8 MB
BOS_ID = 2
UNK_ID = 1
EOS_ID = 3
CHAR_STRESS_CONFIDENCE = 0.55
RU_VOWELS = frozenset("аеёиоуыэюя")
USER_AGENT = "RuVoice-RUAccent-Stage4.7/1.0"
DEFAULT_WORDS = Path(__file__).parent / "data" / "ruaccent_accent_probe_words.json"


class ProbeError(RuntimeError):
    """The nn_accent bundle or its ONNX interface is not usable."""


@dataclass(frozen=True)
class ArtifactReport:
    relative_path: str
    size_bytes: int
    sha256: str
    detail: str


def url_for(relative: Path) -> str:
    relative = Path(relative)
    if relative not in FILES:
        raise ValueError(f"Artifact is not part of stage 4.7: {relative}")
    return (
        f"https://huggingface.co/{REPOSITORY}/resolve/"
        f"{REVISION}/{BUNDLE}/{relative.as_posix()}"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProbeError(f"Cannot read UTF-8 JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProbeError(f"JSON root must be an object: {path}")
    return value


def validate_onnx(path: Path, deep_check: bool = False) -> str:
    if not path.is_file():
        raise ProbeError(f"Missing ONNX model: {path}")
    size = path.stat().st_size
    if size < MIN_ONNX_BYTES:
        raise ProbeError(
            f"ONNX model is unexpectedly small ({size:,} bytes): {path}; "
            "possible Git-LFS pointer or incomplete download"
        )
    with path.open("rb") as stream:
        prefix = stream.read(128)
    lowered = prefix.lstrip().lower()
    if lowered.startswith((b"version https://git-lfs.github.com/spec/v1", b"<!doctype html", b"<html")):
        raise ProbeError(f"Downloaded content is not an ONNX binary: {path}")
    if not prefix or prefix[0] != 0x08:
        raise ProbeError(f"Unexpected ONNX ModelProto header: {path}")
    detail = f"binary ONNX candidate; {size:,} bytes"
    if deep_check:
        try:
            import onnx  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ProbeError("--onnx-check requires: python -m pip install onnx") from exc
        model = onnx.load(str(path), load_external_data=True)
        onnx.checker.check_model(model)
        detail += f"; ONNX checker passed (IR {model.ir_version})"
    else:
        detail += "; graph-level check not run (use --onnx-check)"
    return detail


def validate_vocab(path: Path) -> tuple[list[str], str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ProbeError(f"Cannot read nn_accent character vocab {path}: {exc}") from exc
    if len(lines) <= EOS_ID:
        raise ProbeError(f"nn_accent vocab has only {len(lines)} entries; expected ids through {EOS_ID}")
    if any(token == "" for token in lines):
        raise ProbeError("nn_accent vocab contains an empty token line")
    duplicates = len(lines) - len(set(lines))
    if duplicates:
        raise ProbeError(f"nn_accent vocab contains {duplicates} duplicate token line(s)")
    russian_chars = sum(1 for token in lines if len(token) == 1 and token.lower() in RU_VOWELS)
    if russian_chars != len(RU_VOWELS):
        raise ProbeError(
            f"nn_accent vocab must contain all {len(RU_VOWELS)} Russian vowels as single-character tokens; "
            f"found {russian_chars}"
        )
    special = {"unk_id": UNK_ID, "bos_id": BOS_ID, "eos_id": EOS_ID}
    return lines, f"character vocab={len(lines):,}; fixed special IDs={special}; vowel chars={russian_chars}"


def validate_labels(path: Path) -> tuple[dict[int, str], str]:
    raw = _read_json(path)
    id2label = raw.get("id2label")
    if not isinstance(id2label, dict) or not id2label:
        raise ProbeError("nn_accent config.json must contain a non-empty id2label object")
    labels: dict[int, str] = {}
    for key, value in id2label.items():
        try:
            index = int(key)
        except (TypeError, ValueError) as exc:
            raise ProbeError(f"Non-integer id2label key: {key!r}") from exc
        if not isinstance(value, str) or not value:
            raise ProbeError(f"Invalid label name for id {key!r}")
        labels[index] = value
    expected = list(range(len(labels)))
    if sorted(labels) != expected:
        raise ProbeError(f"id2label keys must be contiguous from 0; got {sorted(labels)}")
    if "STRESS_PRIMARY" not in labels.values():
        raise ProbeError("nn_accent labels do not contain STRESS_PRIMARY")
    return labels, f"character classification labels={labels}"


def load_accent_dictionary(path: Path) -> tuple[dict[str, str], str]:
    if not path.is_file():
        raise ProbeError(f"Missing RUAccent accent dictionary: {path}")
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            raw = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProbeError(f"Cannot read gzip JSON accent dictionary: {path}: {exc}") from exc
    if not isinstance(raw, dict) or not raw:
        raise ProbeError("accents_nn.json.gz must contain a non-empty JSON object")
    invalid = []
    for word, marked in raw.items():
        if not isinstance(word, str) or not word or not isinstance(marked, str) or not marked:
            invalid.append(repr(word))
            continue
        if marked.replace("+", "").casefold() != word.casefold():
            invalid.append(f"{word!r}->{marked!r}: spelling mismatch")
            continue
        plus_positions = [i for i, ch in enumerate(marked) if ch == "+"]
        if not plus_positions or any(
            i + 1 >= len(marked) or marked[i + 1].lower() not in RU_VOWELS
            for i in plus_positions
        ):
            invalid.append(f"{word!r}->{marked!r}: invalid stress notation")
    if invalid:
        raise ProbeError("Invalid accent dictionary entries: " + "; ".join(invalid[:8]))
    return {str(k): str(v) for k, v in raw.items()}, f"accent dictionary entries={len(raw):,}"


def validate_bundle(root: Path, deep_onnx: bool = False) -> list[ArtifactReport]:
    paths = {
        MODEL_RELATIVE: validate_onnx(root / MODEL_RELATIVE, deep_check=deep_onnx),
        VOCAB_RELATIVE: validate_vocab(root / VOCAB_RELATIVE)[1],
        CONFIG_RELATIVE: validate_labels(root / CONFIG_RELATIVE)[1],
        ACCENTS_RELATIVE: load_accent_dictionary(root / ACCENTS_RELATIVE)[1],
    }
    reports = []
    for relative, detail in paths.items():
        path = root / relative
        reports.append(ArtifactReport(relative.as_posix(), path.stat().st_size, sha256_file(path), detail))
    return reports


def download_one(relative: Path, root: Path, timeout: int = 60) -> None:
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    request = urllib.request.Request(url_for(relative), headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, partial.open("wb") as output:
            status = getattr(response, "status", 200)
            if not 200 <= status < 300:
                raise ProbeError(f"HTTP {status} for {relative}: {status}")
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                output.write(block)
        if not partial.is_file() or partial.stat().st_size == 0:
            raise ProbeError(f"Empty download for {relative}")
        partial.replace(destination)
    except (OSError, urllib.error.URLError) as exc:
        partial.unlink(missing_ok=True)
        raise ProbeError(f"Download failed for {relative}: {exc}") from exc


def validate_session_signature(session: Any, labels: dict[int, str]) -> dict[str, Any]:
    inputs = {item.name: item for item in session.get_inputs()}
    required = {"input_ids", "attention_mask", "token_type_ids"}
    missing = required - set(inputs)
    if missing:
        raise ProbeError(f"nn_accent ONNX is missing required inputs: {sorted(missing)}")
    unexpected = set(inputs) - required
    if unexpected:
        raise ProbeError(f"Unexpected nn_accent ONNX inputs: {sorted(unexpected)}")
    for name, meta in inputs.items():
        if meta.type != "tensor(int64)":
            raise ProbeError(f"nn_accent input {name!r} must be tensor(int64), got {meta.type!r}")
    outputs = session.get_outputs()
    if not outputs:
        raise ProbeError("nn_accent ONNX has no outputs")
    shape = list(outputs[0].shape)
    if len(shape) != 3:
        raise ProbeError(f"Expected char-level logits [batch, sequence, classes], got {shape}")
    if isinstance(shape[-1], int) and shape[-1] != len(labels):
        raise ProbeError(f"ONNX class dimension {shape[-1]} does not match id2label ({len(labels)})")
    return {"input_names": list(inputs), "output_name": outputs[0].name, "output_shape": shape, "label_count": len(labels)}


def _softmax(logits: np.ndarray) -> np.ndarray:
    values = np.asarray(logits, dtype=np.float32).reshape(-1)
    if values.size < 2 or not np.all(np.isfinite(values)):
        raise ProbeError(f"Invalid char logits: {values.tolist()}")
    shifted = values - np.max(values)
    exps = np.exp(shifted)
    total = float(exps.sum())
    if not math.isfinite(total) or total <= 0:
        raise ProbeError("Invalid char softmax denominator")
    return exps / total


class CharAccentProbe:
    def __init__(self, session: Any, vocab: list[str], labels: dict[int, str], min_confidence: float = CHAR_STRESS_CONFIDENCE):
        if not 0.0 < min_confidence < 1.0:
            raise ProbeError("min_confidence must be between 0 and 1")
        self.session = session
        self.char_vocab = {token: index for index, token in enumerate(vocab)}
        self.labels = labels
        self.min_confidence = min_confidence
        validate_session_signature(session, labels)

    def predict(self, word: str) -> dict[str, Any]:
        if not isinstance(word, str) or not word or any(ch.isspace() for ch in word):
            raise ProbeError("word must be one non-empty token without whitespace")
        lower = word.lower()
        if any(ch not in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя" for ch in lower):
            raise ProbeError("word must contain only Russian Cyrillic letters")
        if len(lower) < 2:
            raise ProbeError("word is too short for the nn_accent OOV model")
        ids = [BOS_ID] + [self.char_vocab.get(ch, UNK_ID) for ch in lower] + [EOS_ID]
        input_ids = np.asarray([ids], dtype=np.int64)
        attention = np.ones_like(input_ids)
        token_types = np.zeros_like(input_ids)
        outputs = self.session.run(None, {
            "input_ids": input_ids,
            "attention_mask": attention,
            "token_type_ids": token_types,
        })
        if not outputs:
            raise ProbeError("nn_accent returned no outputs")
        logits = np.asarray(outputs[0], dtype=np.float32)
        if logits.ndim != 3 or logits.shape[0] != 1 or logits.shape[1] != len(ids):
            raise ProbeError(f"Expected output shape [1,{len(ids)},classes], got {list(logits.shape)}")
        if logits.shape[2] != len(self.labels):
            raise ProbeError(f"Output classes {logits.shape[2]} do not match id2label ({len(self.labels)})")

        candidates = []
        for input_position, char in enumerate(lower, start=1):
            probabilities = _softmax(logits[0, input_position])
            label_index = int(np.argmax(probabilities))
            label = self.labels.get(label_index)
            confidence = float(probabilities[label_index])
            if label == "STRESS_PRIMARY" and confidence >= self.min_confidence and char in RU_VOWELS:
                candidates.append({"char_index": input_position - 1, "vowel": char, "confidence": confidence})
        best = max(candidates, key=lambda item: item["confidence"], default=None)
        marked = None
        if best is not None:
            at = int(best["char_index"])
            marked = word[:at + 1] + "\u0301" + word[at + 1:]
        return {
            "word": word,
            "model_input_ids": ids,
            "candidate_positions": candidates,
            "selected": best,
            "marked": marked,
            "min_confidence": self.min_confidence,
        }


def make_session(model_path: Path, threads: int = 2) -> Any:
    try:
        import onnxruntime as ort  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ProbeError("ONNX probe requires: python -m pip install onnxruntime numpy") from exc
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])


def run_probe(root: Path, word: str, min_confidence: float = CHAR_STRESS_CONFIDENCE) -> dict[str, Any]:
    vocab, _ = validate_vocab(root / VOCAB_RELATIVE)
    labels, _ = validate_labels(root / CONFIG_RELATIVE)
    dictionary, _ = load_accent_dictionary(root / ACCENTS_RELATIVE)
    model = make_session(root / MODEL_RELATIVE)
    probe = CharAccentProbe(model, vocab, labels, min_confidence)
    result = probe.predict(word)
    lower = word.lower()
    result["accent_dictionary_entry"] = dictionary.get(lower)
    result["runtime_would_use_char_model"] = lower not in dictionary and sum(ch in RU_VOWELS for ch in lower) > 1
    return result


def run_smoke(
    root: Path,
    words_path: Path = DEFAULT_WORDS,
    min_confidence: float = CHAR_STRESS_CONFIDENCE,
    session_factory: Any = make_session,
) -> list[dict[str, Any]]:
    try:
        raw = json.loads(words_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProbeError(f"Cannot read smoke word list {words_path}: {exc}") from exc
    if not isinstance(raw, list) or not raw:
        raise ProbeError("Smoke word list must be a non-empty JSON array")
    words = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("word"), str):
            raise ProbeError("Each smoke item must be an object with a string 'word'")
        words.append(item["word"])

    vocab, _ = validate_vocab(root / VOCAB_RELATIVE)
    labels, _ = validate_labels(root / CONFIG_RELATIVE)
    dictionary, _ = load_accent_dictionary(root / ACCENTS_RELATIVE)
    session = session_factory(root / MODEL_RELATIVE)
    probe = CharAccentProbe(session, vocab, labels, min_confidence)
    results = []
    for word in words:
        result = probe.predict(word)
        lower = word.lower()
        result["accent_dictionary_entry"] = dictionary.get(lower)
        result["runtime_would_use_char_model"] = (
            lower not in dictionary and sum(ch in RU_VOWELS for ch in lower) > 1
        )
        results.append(result)
    return results


def write_report(root: Path, reports: list[ArtifactReport]) -> Path:
    target = root / "stage4.7-verification.json"
    target.write_text(json.dumps({"repository": REPOSITORY, "revision": REVISION,
                                  "stage": "4.7-nn-accent-char-roformer",
                                  "artifacts": [r.__dict__ for r in reports]},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    download = sub.add_parser("download", help="download the nn_accent model bundle")
    download.add_argument("root", type=Path)
    download.add_argument("--timeout", type=int, default=60)
    verify = sub.add_parser("verify", help="validate all nn_accent artifacts")
    verify.add_argument("root", type=Path)
    verify.add_argument("--onnx-check", action="store_true")
    probe = sub.add_parser("probe", help="run the real char-level ONNX model on one word")
    probe.add_argument("root", type=Path)
    probe.add_argument("--word", required=True)
    probe.add_argument("--min-confidence", type=float, default=CHAR_STRESS_CONFIDENCE)
    smoke = sub.add_parser("smoke", help="run a small non-gold word list with one loaded session")
    smoke.add_argument("root", type=Path)
    smoke.add_argument("--words-json", type=Path, default=DEFAULT_WORDS)
    smoke.add_argument("--min-confidence", type=float, default=CHAR_STRESS_CONFIDENCE)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "download":
            for relative in FILES:
                download_one(relative, args.root, args.timeout)
            print(f"Downloaded {len(FILES)} nn_accent artifacts to {args.root}")
        elif args.command == "verify":
            reports = validate_bundle(args.root, deep_onnx=args.onnx_check)
            report = write_report(args.root, reports)
            for item in reports:
                print(f"OK {item.relative_path}: {item.size_bytes:,} bytes; sha256={item.sha256}; {item.detail}")
            print(f"Wrote {report}")
        elif args.command == "probe":
            result = run_probe(args.root, args.word, args.min_confidence)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "smoke":
            results = run_smoke(args.root, args.words_json, args.min_confidence)
            print(json.dumps({"count": len(results), "results": results}, ensure_ascii=False, indent=2))
        return 0
    except (ProbeError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
