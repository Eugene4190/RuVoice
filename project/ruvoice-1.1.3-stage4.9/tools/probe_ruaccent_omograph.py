#!/usr/bin/env python3
"""Validate and probe RUAccent's NLI nn_omograph model (turbo3.1, int8).

This development tool is deliberately limited to the context-sensitive
homograph resolver. It does not modify the Android application or the live
RuVoice text pipeline. It uses the exact pair-building and entailment-scoring
contract from stressonnx's RuAccentStressor reference backend.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

try:
    from .probe_ruaccent_stage41 import _read_json
except ImportError:  # Running as: python tools/probe_ruaccent_omograph.py
    from probe_ruaccent_stage41 import _read_json

REPOSITORY = "TigreGotico/stressonnx-models"
REVISION = "cb1594ddf81928e678a3a7ee7a22415e6e3a218f"
BUNDLE = "ru_ruaccent"
MODEL_RELATIVE = Path("nn_omograph/model.int8.onnx")
TOKENIZER_RELATIVE = Path("nn_omograph/tokenizer.json")
DICTIONARY_RELATIVE = Path("dictionary/omographs.json.gz")
FILES = (MODEL_RELATIVE, TOKENIZER_RELATIVE, DICTIONARY_RELATIVE)
MIN_ONNX_BYTES = 20 * 1024 * 1024  # LFS pointer / truncated-file guard, not an exact size pin.
MAX_TOKENS = 512
CONTEXT_WORDS = 64
ENTAILMENT_CLASS_INDEX = 1
USER_AGENT = "RuVoice-RUAccent-Stage4.6/1.0"
DEFAULT_DATASET = Path(__file__).parents[1] / "app" / "src" / "test" / "resources" / "homograph_eval" / "HomographResolutionEval.json"
_RU_SPLIT_RE = re.compile(r"[\w\u0301]+|[^\w\s\u0301]+", flags=re.UNICODE)
_RU_VOWELS = frozenset("аеёиоуыэюя")
_PUNC_CHARS = '!"#%&\'()*,./:;<=>?@[\\]^_`{|}-'


class ProbeError(RuntimeError):
    """The model bundle, dictionary or ONNX inference signature is unusable."""


@dataclass(frozen=True)
class ArtifactReport:
    relative_path: str
    size_bytes: int
    sha256: str
    detail: str


def url_for(relative_path: Path) -> str:
    relative = Path(relative_path)
    if relative not in FILES:
        raise ValueError(f"Artifact is not part of stage 4.6: {relative}")
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


def validate_onnx_file(path: Path, deep_check: bool = False) -> str:
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
    if not deep_check:
        return detail + "; graph-level check not run (use --onnx-check)"
    try:
        import onnx  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ProbeError("--onnx-check requires: python -m pip install onnx") from exc
    model = onnx.load(str(path), load_external_data=True)
    onnx.checker.check_model(model)
    return detail + f"; ONNX checker passed (IR {model.ir_version})"


def validate_tokenizer(path: Path) -> tuple[dict[str, Any], str]:
    spec = _read_json(path)
    model = spec.get("model")
    if not isinstance(model, dict) or model.get("type") != "BPE":
        kind = model.get("type") if isinstance(model, dict) else None
        raise ProbeError(f"nn_omograph tokenizer is expected to use BPE, got {kind!r}")
    vocab = model.get("vocab")
    merges = model.get("merges")
    if not isinstance(vocab, dict) or not vocab:
        raise ProbeError("nn_omograph tokenizer has no BPE vocabulary")
    if not isinstance(merges, list) or not merges:
        raise ProbeError("nn_omograph tokenizer has no BPE merges")
    added = spec.get("added_tokens", [])
    added_contents = {
        item.get("content") for item in added
        if isinstance(item, dict) and isinstance(item.get("content"), str)
    }
    marker_locations: dict[str, str] = {}
    for marker in ("<w>", "</w>"):
        if marker in added_contents:
            marker_locations[marker] = "added_tokens"
        elif marker in vocab:
            marker_locations[marker] = "vocab"
        else:
            raise ProbeError(f"nn_omograph tokenizer is missing the trained marker {marker!r}")
    detail = (
        f"BPE tokenizer; vocab={len(vocab):,}; merges={len(merges):,}; "
        f"markers={marker_locations}"
    )
    return spec, detail


def _strip_plus(value: str) -> str:
    return value.replace("+", "")


def validate_omograph_dictionary(raw: Any) -> tuple[dict[str, list[str]], dict[str, int]]:
    """Validate {lowercase_word: [plus-notated candidate, ...]} dictionary shape."""
    if not isinstance(raw, dict) or not raw:
        raise ProbeError("omographs.json.gz root must be a non-empty JSON object")
    checked: dict[str, list[str]] = {}
    invalid: list[str] = []
    total_variants = 0
    for key, variants in raw.items():
        if not isinstance(key, str) or not key or key != key.lower():
            invalid.append(f"invalid key {key!r}")
            continue
        if not isinstance(variants, list) or len(variants) < 2:
            invalid.append(f"{key!r}: expected at least two candidate variants")
            continue
        normalized: list[str] = []
        for candidate in variants:
            if not isinstance(candidate, str) or not candidate:
                invalid.append(f"{key!r}: candidate is not a non-empty string")
                continue
            if _strip_plus(candidate) != key:
                invalid.append(f"{key!r}: candidate {candidate!r} changes the word spelling")
                continue
            positions = [i for i, ch in enumerate(candidate) if ch == "+"]
            if not positions or any(
                pos + 1 >= len(candidate) or candidate[pos + 1].lower() not in _RU_VOWELS
                for pos in positions
            ):
                invalid.append(f"{key!r}: candidate {candidate!r} has invalid stress notation")
                continue
            normalized.append(candidate)
        if len(normalized) >= 2 and len(set(normalized)) >= 2:
            checked[key] = normalized
            total_variants += len(normalized)
        else:
            invalid.append(f"{key!r}: fewer than two distinct valid variants")
    if invalid:
        preview = "; ".join(invalid[:8])
        suffix = f"; and {len(invalid) - 8} more" if len(invalid) > 8 else ""
        raise ProbeError(f"Invalid omograph dictionary entries ({len(invalid)}): {preview}{suffix}")
    return checked, {"words": len(checked), "variants": total_variants}


def load_dictionary(path: Path) -> tuple[dict[str, list[str]], dict[str, int]]:
    if not path.is_file():
        raise ProbeError(f"Missing omograph dictionary: {path}")
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            raw = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProbeError(f"Cannot read gzip JSON dictionary: {path}: {exc}") from exc
    return validate_omograph_dictionary(raw)


def validate_bundle(root: Path, deep_onnx: bool = False) -> list[ArtifactReport]:
    model_path = root / MODEL_RELATIVE
    tokenizer_path = root / TOKENIZER_RELATIVE
    dictionary_path = root / DICTIONARY_RELATIVE
    model_detail = validate_onnx_file(model_path, deep_check=deep_onnx)
    _, tokenizer_detail = validate_tokenizer(tokenizer_path)
    _, counts = load_dictionary(dictionary_path)
    return [
        ArtifactReport(MODEL_RELATIVE.as_posix(), model_path.stat().st_size, sha256_file(model_path), model_detail),
        ArtifactReport(TOKENIZER_RELATIVE.as_posix(), tokenizer_path.stat().st_size, sha256_file(tokenizer_path), tokenizer_detail),
        ArtifactReport(DICTIONARY_RELATIVE.as_posix(), dictionary_path.stat().st_size, sha256_file(dictionary_path),
                       f"valid words={counts['words']:,}; candidates={counts['variants']:,}"),
    ]


def download_one(relative_path: Path, root: Path, timeout: int) -> None:
    destination = root / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    request = urllib.request.Request(url_for(relative_path), headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, partial.open("wb") as output:
            status = getattr(response, "status", 200)
            if not 200 <= status < 300:
                raise ProbeError(f"HTTP {status} for {relative_path}")
            expected = response.headers.get("Content-Length")
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                total += len(chunk)
                if relative_path == MODEL_RELATIVE:
                    print(f"\rDownloaded NLI omograph model: {total / (1024 * 1024):.1f} MiB", end="", flush=True)
            output.flush()
            os.fsync(output.fileno())
        if relative_path == MODEL_RELATIVE:
            print()
        if total <= 0:
            raise ProbeError(f"Empty download: {relative_path}")
        if expected and expected.isdigit() and total != int(expected):
            raise ProbeError(f"Truncated download for {relative_path}: {total} / {expected} bytes")
        partial.replace(destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def write_report(root: Path, reports: list[ArtifactReport]) -> Path:
    report_path = root / "stage4.6-verification.json"
    payload = {
        "repository": REPOSITORY,
        "revision": REVISION,
        "stage": "4.6-nn-omograph-nli-turbo3.1-int8",
        "artifacts": [report.__dict__ for report in reports],
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_path


def _delete_spaces_before_punctuation(text: str) -> str:
    # Mirrors stressonnx._delete_spaces_before_punc(), including the special
    # treatment of spaced hyphens used to join the word-stream representation.
    for char in _PUNC_CHARS:
        if char == "-":
            text = text.replace(" -", "-").replace("- ", "-")
        text = text.replace(" " + char, char)
    return text.replace("~", "-")


def _encode_pair(tokenizer: Any, premise: str, hypothesis: str) -> Any:
    try:
        return tokenizer.encode(premise, pair=hypothesis)
    except TypeError:
        # tokenizers 1.x accepts a tuple for sequence pairs.
        return tokenizer.encode((premise, hypothesis))


def validate_session_signature(session: Any) -> dict[str, Any]:
    inputs = {item.name: item for item in session.get_inputs()}
    required = {"input_ids", "attention_mask"}
    missing = required - set(inputs)
    if missing:
        raise ProbeError(f"NLI ONNX is missing required inputs: {sorted(missing)}")
    unsupported = set(inputs) - required - {"token_type_ids"}
    if unsupported:
        raise ProbeError(f"Unexpected NLI inputs: {sorted(unsupported)}")
    for name, meta in inputs.items():
        if meta.type != "tensor(int64)":
            raise ProbeError(f"NLI input {name!r} must be tensor(int64), got {meta.type!r}")
    outputs = session.get_outputs()
    if not outputs:
        raise ProbeError("NLI ONNX has no outputs")
    shape = list(outputs[0].shape)
    if len(shape) != 2:
        raise ProbeError(f"Expected sequence-classification logits [batch, classes], got {shape}")
    # The reference backend consumes softmax(logits)[1] as entailment.
    # Keep two-class and three-class NLI heads valid; reject only a statically
    # known output with fewer than two classes.
    if isinstance(shape[-1], int) and shape[-1] < 2:
        raise ProbeError(f"NLI sequence classifier must expose at least two classes, got {shape}")
    return {
        "input_names": list(inputs),
        "input_types": {name: meta.type for name, meta in inputs.items()},
        "output_name": outputs[0].name,
        "output_shape": shape,
        "entailment_class_index": ENTAILMENT_CLASS_INDEX,
    }


def _softmax(values: Any) -> np.ndarray:
    logits = np.asarray(values, dtype=np.float32).reshape(-1)
    if logits.size < 2 or not np.all(np.isfinite(logits)):
        raise ProbeError(f"NLI must return at least two finite class logits, got {logits.tolist()}")
    shifted = logits - float(np.max(logits))
    exps = np.exp(shifted)
    denominator = float(np.sum(exps))
    if not np.isfinite(denominator) or denominator <= 0:
        raise ProbeError("NLI returned invalid logits")
    return exps / denominator


def _context_words(text: str) -> list[str]:
    # The upstream pipeline scores lower-case tokenized text including
    # punctuation runs as independent context items.
    return _RU_SPLIT_RE.findall(text.lower())


def _make_context_window(words: list[str], target_index: int, radius: int) -> str:
    window_size = radius * 2 + 1
    left = max(0, min(target_index - radius, len(words) - window_size))
    selected = list(words[left:left + window_size])
    local_index = target_index - left
    if local_index < 0 or local_index >= len(selected):
        raise ProbeError("Target fell outside the selected NLI context window")
    selected[local_index] = " <w>" + selected[local_index] + "</w> "
    return _delete_spaces_before_punctuation(" ".join(selected))


def score_candidates(
    text: str,
    target: str,
    occurrence: int,
    candidates: list[str],
    session: Any,
    tokenizer: Any,
) -> dict[str, Any]:
    if not text.strip():
        raise ProbeError("Input context is empty")
    if not target or any(ch.isspace() for ch in target):
        raise ProbeError("Target must be one word")
    if not isinstance(occurrence, int) or occurrence < 0:
        raise ProbeError("Occurrence must be a non-negative integer")
    if not candidates or len(candidates) < 2:
        raise ProbeError("The target must have at least two dictionary candidates")
    base_word = target.lower()
    for candidate in candidates:
        if not isinstance(candidate, str) or _strip_plus(candidate) != base_word:
            raise ProbeError(f"Dictionary candidate {candidate!r} does not match target {base_word!r}")

    words = _context_words(text)
    positions = [i for i, word in enumerate(words) if word == base_word]
    if occurrence >= len(positions):
        raise ProbeError(
            f"Target {base_word!r} occurrence {occurrence} not found; context contains {len(positions)} occurrence(s)"
        )
    target_index = positions[occurrence]
    signature = validate_session_signature(session)

    radius = CONTEXT_WORDS
    encoded_by_candidate: list[tuple[str, Any, str]] = []
    while True:
        premise = _make_context_window(words, target_index, radius)
        encoded = [(candidate, _encode_pair(tokenizer, premise, candidate), premise) for candidate in candidates]
        if all(len(item[1].ids) <= MAX_TOKENS for item in encoded):
            encoded_by_candidate = encoded
            break
        if radius == 0:
            longest = max(len(item[1].ids) for item in encoded)
            raise ProbeError(
                f"Even the target-only context exceeds {MAX_TOKENS} tokens ({longest}); refusing silent truncation"
            )
        radius //= 2

    scored: list[dict[str, Any]] = []
    input_names = set(signature["input_names"])
    for candidate, encoding, premise in encoded_by_candidate:
        ids = np.asarray([list(encoding.ids)], dtype=np.int64)
        mask = np.asarray([list(encoding.attention_mask)], dtype=np.int64)
        if ids.shape != mask.shape:
            raise ProbeError("Tokenizer returned different input_ids and attention_mask lengths")
        feeds: dict[str, np.ndarray] = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in input_names:
            type_ids = getattr(encoding, "type_ids", None)
            if type_ids is None or len(type_ids) != ids.shape[1]:
                raise ProbeError("This ONNX model requires token_type_ids, but tokenizer did not return them")
            feeds["token_type_ids"] = np.asarray([list(type_ids)], dtype=np.int64)
        raw_outputs = session.run(None, feeds)
        if not raw_outputs:
            raise ProbeError("ONNX Runtime returned no NLI outputs")
        logits = np.asarray(raw_outputs[0])
        if logits.ndim != 2 or logits.shape[0] != 1 or logits.shape[1] < 2:
            raise ProbeError(
                f"Expected NLI sequence-classification logits [1, classes>=2], got {list(logits.shape)}"
            )
        probabilities = _softmax(logits[0])
        scored.append({
            "candidate": candidate,
            "entailment_probability": float(probabilities[ENTAILMENT_CLASS_INDEX]),
            "class_0_probability": float(probabilities[0]),
            "class_probabilities": probabilities.astype(float).tolist(),
            "token_count": int(ids.shape[1]),
            "premise": premise,
        })

    # Python max, like NumPy argmax in the reference backend, keeps the first
    # candidate in dictionary order when scores tie.
    best = max(scored, key=lambda item: item["entailment_probability"])
    ordered = sorted(scored, key=lambda item: item["entailment_probability"], reverse=True)
    margin = (
        ordered[0]["entailment_probability"] - ordered[1]["entailment_probability"]
        if len(ordered) > 1 else 1.0
    )
    return {
        "text": text,
        "target": base_word,
        "occurrence": occurrence,
        "target_token_index": target_index,
        "context_radius_words": radius,
        "predicted_candidate": best["candidate"],
        "entailment_margin": margin,
        "candidates": scored,
        "onnx": signature,
        "note": "Candidate probabilities are pairwise NLI entailment scores; selection mirrors RUAccent argmax over class-1 probabilities.",
    }


def acute_to_plus(word: str) -> str:
    """Convert acute to RUAccent plus notation, e.g. сло́ва -> сл+ова."""
    output: list[str] = []
    for char in word:
        if char == "\u0301":
            if not output or output[-1] == "+":
                raise ProbeError(f"Malformed combining stress mark in {word!r}")
            output.insert(len(output) - 1, "+")
        else:
            output.append(char.lower())
    return "".join(output)


def evaluate_dataset(
    dataset: list[dict[str, Any]],
    dictionary: dict[str, list[str]],
    probe: Callable[[str, str, int, list[str]], dict[str, Any]],
    max_cases: int | None = None,
) -> dict[str, Any]:
    if max_cases is not None and max_cases < 1:
        raise ProbeError("max_cases must be positive")
    totals = {"checked": 0, "correct": 0, "wrong": 0, "missing_dictionary": 0,
              "gold_not_in_dictionary": 0, "target_not_found": 0, "errors": 0}
    examples: list[dict[str, Any]] = []
    limit = len(dataset) if max_cases is None else min(len(dataset), max_cases)
    for item in dataset[:limit]:
        try:
            context = item["context"]
            marked_gold = acute_to_plus(item["homograph"])
            target = _strip_plus(marked_gold)
            if target not in dictionary:
                totals["missing_dictionary"] += 1
                continue
            if marked_gold not in dictionary[target]:
                totals["gold_not_in_dictionary"] += 1
                continue
            occurrence = item.get("occurrence", 0)
            positions = [m.group(0).lower() for m in _RU_SPLIT_RE.finditer(context)]
            if positions.count(target) <= occurrence:
                totals["target_not_found"] += 1
                continue
            result = probe(context, target, occurrence, dictionary[target])
            totals["checked"] += 1
            predicted = result["predicted_candidate"]
            correct = predicted == marked_gold
            totals["correct" if correct else "wrong"] += 1
            if not correct and len(examples) < 40:
                examples.append({
                    "id": item.get("id"), "context": context, "target": target,
                    "gold": marked_gold, "predicted": predicted,
                    "candidate_scores": result["candidates"],
                })
        except ProbeError:
            totals["errors"] += 1
            if len(examples) < 40:
                examples.append({"id": item.get("id"), "error": "probe failed"})
    accuracy = totals["correct"] / totals["checked"] if totals["checked"] else None
    return {
        "dataset_cases_seen": limit,
        "metrics": totals,
        "accuracy": accuracy,
        "accuracy_percent": round(accuracy * 100, 2) if accuracy is not None else None,
        "examples_of_errors": examples,
        "note": "Evaluation is limited to cases whose target and gold stressed variant both exist in the RUAccent omograph dictionary.",
    }


def load_runtime(root: Path) -> tuple[Any, Any, dict[str, list[str]], dict[str, int]]:
    try:
        import onnxruntime as ort  # type: ignore[import-not-found]
        from tokenizers import Tokenizer  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ProbeError("Inference requires `pip install onnxruntime tokenizers numpy`") from exc
    model_path = root / MODEL_RELATIVE
    tokenizer_path = root / TOKENIZER_RELATIVE
    model_detail = validate_onnx_file(model_path)
    spec, _ = validate_tokenizer(tokenizer_path)
    dictionary, counts = load_dictionary(root / DICTIONARY_RELATIVE)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    tokenizer.no_truncation()
    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    signature = validate_session_signature(session)
    return session, tokenizer, dictionary, counts


def _load_dataset(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProbeError(f"Cannot read evaluation JSON: {path}: {exc}") from exc
    if not isinstance(data, list):
        raise ProbeError("HomographResolutionEval must be a JSON array")
    for index, item in enumerate(data):
        if not isinstance(item, dict) or not isinstance(item.get("context"), str) or not isinstance(item.get("homograph"), str):
            raise ProbeError(f"Invalid HomographResolutionEval row at index {index}")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    download_parser = commands.add_parser("download", help="download only nn_omograph int8, tokenizer and dictionary")
    download_parser.add_argument("directory", type=Path)
    download_parser.add_argument("--timeout", type=int, default=180)

    verify_parser = commands.add_parser("verify", help="verify already-downloaded model bundle")
    verify_parser.add_argument("directory", type=Path)
    verify_parser.add_argument("--onnx-check", action="store_true")

    probe_parser = commands.add_parser("probe", help="score all dictionary variants for one target in a sentence")
    probe_parser.add_argument("directory", type=Path)
    probe_parser.add_argument("--text", required=True)
    probe_parser.add_argument("--target", required=True)
    probe_parser.add_argument("--occurrence", type=int, default=0)

    eval_parser = commands.add_parser("evaluate", help="evaluate dictionary-covered cases from HomographResolutionEval")
    eval_parser.add_argument("directory", type=Path)
    eval_parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    eval_parser.add_argument("--max-cases", type=int, default=None)
    eval_parser.add_argument("--output", type=Path, default=None)

    args = parser.parse_args(argv)
    try:
        root: Path = args.directory
        if args.command == "download":
            root.mkdir(parents=True, exist_ok=True)
            for relative_path in FILES:
                print(f"Downloading {relative_path.as_posix()} …")
                download_one(relative_path, root, args.timeout)
            reports = validate_bundle(root)
            report_path = write_report(root, reports)
            for report in reports:
                print(f"PASS  {report.relative_path} ({report.size_bytes:,} bytes)")
                print(f"      SHA-256 {report.sha256}")
                print(f"      {report.detail}")
            print(f"\nStage 4.6 verification report: {report_path}")
            return 0
        if args.command == "verify":
            reports = validate_bundle(root, deep_onnx=args.onnx_check)
            report_path = write_report(root, reports)
            for report in reports:
                print(f"PASS  {report.relative_path} ({report.size_bytes:,} bytes)")
                print(f"      SHA-256 {report.sha256}")
                print(f"      {report.detail}")
            print(f"\nStage 4.6 verification report: {report_path}")
            return 0

        session, tokenizer, dictionary, counts = load_runtime(root)
        print(f"Loaded omograph dictionary: {counts['words']:,} words / {counts['variants']:,} variants")
        if args.command == "probe":
            target = args.target.lower()
            if target not in dictionary:
                raise ProbeError(f"Target {target!r} is not in the RUAccent omograph dictionary")
            result = score_candidates(args.text, target, args.occurrence, dictionary[target], session, tokenizer)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "evaluate":
            dataset = _load_dataset(args.dataset)
            report = evaluate_dataset(
                dataset, dictionary,
                lambda text, target, occurrence, variants: score_candidates(
                    text, target, occurrence, variants, session, tokenizer
                ),
                max_cases=args.max_cases,
            )
            rendered = json.dumps(report, ensure_ascii=False, indent=2)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(rendered + "\n", encoding="utf-8")
                print(f"Wrote evaluation report: {args.output}")
            print(rendered)
            return 0
        raise ProbeError("Unknown command")
    except (OSError, ValueError, RuntimeError, urllib.error.URLError, ProbeError) as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
