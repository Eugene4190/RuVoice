#!/usr/bin/env python3
"""Download, validate, and probe RUAccent's standalone nn_yo_homograph model.

This is a development-only preflight. It does not change the Android app and
intentionally downloads only the ё token classifier plus its tokenizer/config.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

try:
    from .probe_ruaccent_stress_usage import (
        ProbeError,
        _pretoken_spans,
        _softmax_rows,
        _wordpiece_word_ids,
        aggregate_word_labels,
        load_tokenizer_spec,
        normalize_ruaccent_text,
        validate_session_signature,
    )
    from .probe_ruaccent_stage41 import _read_json
except ImportError:  # Running as: python tools/probe_ruaccent_yo.py
    from probe_ruaccent_stress_usage import (
        ProbeError,
        _pretoken_spans,
        _softmax_rows,
        _wordpiece_word_ids,
        aggregate_word_labels,
        load_tokenizer_spec,
        normalize_ruaccent_text,
        validate_session_signature,
    )
    from probe_ruaccent_stage41 import _read_json

REPOSITORY = "TigreGotico/stressonnx-models"
REVISION = "cb1594ddf81928e678a3a7ee7a22415e6e3a218f"
BUNDLE = "ru_ruaccent"
MODEL_RELATIVE = Path("nn_yo_homograph/model.onnx")
TOKENIZER_RELATIVE = Path("nn_yo_homograph/tokenizer.json")
CONFIG_RELATIVE = Path("nn_yo_homograph/config.json")
FILES = (MODEL_RELATIVE, TOKENIZER_RELATIVE, CONFIG_RELATIVE)
MIN_ONNX_BYTES = 4 * 1024 * 1024  # docs describe this DistilBERT graph as ~14 MB
MAX_TOKENS = 512
USER_AGENT = "RuVoice-RUAccent-Stage4.4/1.0"
DEFAULT_CORPUS = Path(__file__).parent / "data" / "ruaccent_yo_smoke.json"


@dataclass(frozen=True)
class ArtifactReport:
    relative_path: str
    size_bytes: int
    sha256: str
    detail: str


def url_for(relative_path: Path) -> str:
    relative = Path(relative_path)
    if relative not in FILES:
        raise ValueError(f"Artifact is not part of stage 4.4: {relative}")
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


def validate_model(path: Path, deep_check: bool = False) -> str:
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


def validate_tokenizer(path: Path) -> str:
    spec = load_tokenizer_spec(path)
    model = spec["model"]
    return f"tokenizer model={model['type']}; vocab entries={len(model['vocab']):,}"


def validate_yo_label_map(raw: Any) -> dict[str, str]:
    """Validate a token-classification map with an explicit YO class.

    The upstream runtime only acts on the exact label `YO`; all other labels
    mean that this token is not selected for the dictionary's yo-homograph
    override. We preserve the original non-YO labels in the report.
    """
    if not isinstance(raw, dict) or len(raw) < 2:
        raise ProbeError("config.json id2label must contain at least two classes")
    normalized: dict[str, str] = {}
    for key, value in raw.items():
        try:
            numeric_key = str(int(key))
        except (TypeError, ValueError) as exc:
            raise ProbeError(f"Invalid id2label class index: {key!r}") from exc
        if not isinstance(value, str) or not value.strip():
            raise ProbeError(f"Invalid id2label value for class {key!r}")
        normalized[numeric_key] = value.strip().upper()
    if set(normalized) != {str(i) for i in range(len(normalized))}:
        raise ProbeError("id2label indices must be contiguous from 0")
    if "YO" not in normalized.values():
        raise ProbeError(f"nn_yo_homograph has no YO class: {normalized}")
    return normalized


def validate_bundle(root: Path, deep_onnx: bool = False) -> list[ArtifactReport]:
    model_path = root / MODEL_RELATIVE
    tokenizer_path = root / TOKENIZER_RELATIVE
    config_path = root / CONFIG_RELATIVE
    config = _read_json(config_path)
    labels = validate_yo_label_map(config.get("id2label"))
    model_detail = validate_model(model_path, deep_check=deep_onnx)
    return [
        ArtifactReport(MODEL_RELATIVE.as_posix(), model_path.stat().st_size, sha256_file(model_path), model_detail),
        ArtifactReport(TOKENIZER_RELATIVE.as_posix(), tokenizer_path.stat().st_size, sha256_file(tokenizer_path), validate_tokenizer(tokenizer_path)),
        ArtifactReport(CONFIG_RELATIVE.as_posix(), config_path.stat().st_size, sha256_file(config_path), "labels=" + ", ".join(f"{k}:{v}" for k, v in labels.items())),
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
                    print(f"\rDownloaded ё model: {total / (1024 * 1024):.1f} MiB", end="", flush=True)
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
    report_path = root / "stage4.4-verification.json"
    payload = {
        "repository": REPOSITORY,
        "revision": REVISION,
        "stage": "4.4-yo-homograph-classifier",
        "artifacts": [report.__dict__ for report in reports],
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_path


def validate_runtime_signature(session: Any, num_labels: int) -> dict[str, Any]:
    signature = validate_session_signature(session, num_labels)
    if "token_type_ids" in signature["input_names"]:
        # DistilBERT's exported yo classifier is expected to use the two input tensors.
        raise ProbeError("nn_yo_homograph unexpectedly requires token_type_ids")
    return signature


def run_probe(text: str, session: Any, tokenizer: Any, tokenizer_spec: dict[str, Any], id2label: dict[str, str]) -> dict[str, Any]:
    normalized = normalize_ruaccent_text(text).lower()
    if not normalized.strip():
        raise ProbeError("Input is empty after RUAccent normalization")
    encoding = tokenizer.encode(normalized)
    token_ids = list(encoding.ids)
    attention_mask = list(encoding.attention_mask)
    if not token_ids:
        raise ProbeError("Tokenizer returned no token IDs")
    if len(token_ids) > MAX_TOKENS:
        raise ProbeError(
            f"Sample has {len(token_ids)} tokens; this probe accepts at most {MAX_TOKENS}. "
            "Use a shorter sentence rather than silently truncating it."
        )
    if len(token_ids) != len(attention_mask):
        raise ProbeError("Tokenizer returned inconsistent ids/mask lengths")

    signature = validate_runtime_signature(session, len(id2label))
    feeds: dict[str, np.ndarray] = {
        "input_ids": np.asarray([token_ids], dtype=np.int64),
        "attention_mask": np.asarray([attention_mask], dtype=np.int64),
    }
    raw_outputs = session.run(None, feeds)
    if not raw_outputs:
        raise ProbeError("ONNX Runtime returned no outputs")
    logits = np.asarray(raw_outputs[0])
    if logits.ndim != 3 or logits.shape[0] != 1:
        raise ProbeError(f"Expected logits [1, sequence, labels], got {list(logits.shape)}")
    if logits.shape[1] != len(token_ids):
        raise ProbeError(f"Model returned {logits.shape[1]} token rows for {len(token_ids)} input tokens")
    if logits.shape[2] != len(id2label):
        raise ProbeError("Model output label count differs from config.json")

    probabilities = _softmax_rows(logits[0])
    word_ids = _wordpiece_word_ids(token_ids, tokenizer_spec)
    pretokens = _pretoken_spans(normalized, tokenizer_spec)
    word_labels = aggregate_word_labels(normalized, probabilities, word_ids, pretokens, id2label)
    for item in word_labels:
        item["raw_label"] = item["label"]
        if item["label"] is not None:
            item["label"] = "YO" if str(item["label"]).upper() == "YO" else "NO_YO"
    return {
        "input": text,
        "normalized_input": normalized,
        "token_count": len(token_ids),
        "onnx": signature,
        "word_labels": word_labels,
        "note": (
            "nn_yo_homograph predicts whether a token should use YO. "
            "The probe does not apply yo_words / yo_homographs dictionaries or rewrite the input."
        ),
    }


def load_probe_runtime(model_dir: Path) -> dict[str, Any]:
    validate_bundle(model_dir)
    tokenizer_path = model_dir / TOKENIZER_RELATIVE
    model_path = model_dir / MODEL_RELATIVE
    config_path = model_dir / CONFIG_RELATIVE
    tokenizer_spec = load_tokenizer_spec(tokenizer_path)
    config = _read_json(config_path)
    id2label = validate_yo_label_map(config.get("id2label"))

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
    session_options.intra_op_num_threads = 1
    session_options.inter_op_num_threads = 1
    session = ort.InferenceSession(
        str(model_path),
        sess_options=session_options,
        providers=["CPUExecutionProvider"],
    )
    signature = validate_runtime_signature(session, len(id2label))
    return {
        "session": session,
        "tokenizer": tokenizer,
        "tokenizer_spec": tokenizer_spec,
        "id2label": id2label,
        "signature": signature,
    }


def probe_with_runtime(text: str, runtime: dict[str, Any]) -> dict[str, Any]:
    return run_probe(text, runtime["session"], runtime["tokenizer"], runtime["tokenizer_spec"], runtime["id2label"])


def load_corpus(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeError(f"Cannot read yo smoke corpus {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("cases"), list):
        raise ProbeError("Yo smoke corpus must have schema_version=1 and a cases array")
    seen: set[str] = set()
    for case in payload["cases"]:
        if not isinstance(case, dict):
            raise ProbeError("Every yo smoke case must be an object")
        case_id, text, checks = case.get("id"), case.get("text"), case.get("expect")
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ProbeError(f"Missing or duplicate case id: {case_id!r}")
        seen.add(case_id)
        if not isinstance(text, str) or not text.strip() or not isinstance(checks, list) or not checks:
            raise ProbeError(f"Case {case_id}: text and non-empty expect list are required")
        for expected in checks:
            if not isinstance(expected, dict) or not isinstance(expected.get("word"), str) or not expected["word"]:
                raise ProbeError(f"Case {case_id}: invalid expected word")
            if expected.get("label") not in {"YO", "NO_YO"}:
                raise ProbeError(f"Case {case_id}: label must be YO or NO_YO")
            occurrence = expected.get("occurrence", 0)
            if not isinstance(occurrence, int) or occurrence < 0:
                raise ProbeError(f"Case {case_id}: occurrence must be a non-negative integer")
    return payload


def evaluate_cases(corpus: dict[str, Any], probe) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    total = passed = missing = 0
    for case in corpus["cases"]:
        prediction = probe(case["text"])
        word_labels = prediction.get("word_labels")
        if not isinstance(word_labels, list):
            raise ProbeError(f"Case {case['id']}: probe did not return word_labels")
        checks: list[dict[str, Any]] = []
        for expected in case["expect"]:
            total += 1
            matches = [item for item in word_labels if str(item.get("word", "")).casefold() == expected["word"].casefold()]
            occurrence = expected.get("occurrence", 0)
            if occurrence >= len(matches):
                missing += 1
                checks.append({"word": expected["word"], "expected": expected["label"], "actual": None, "status": "MISSING"})
                continue
            observed = matches[occurrence]
            actual = observed.get("label")
            ok = actual == expected["label"]
            passed += int(ok)
            checks.append({
                "word": expected["word"], "occurrence": occurrence,
                "expected": expected["label"], "actual": actual,
                "raw_label": observed.get("raw_label"),
                "confidence": observed.get("confidence"),
                "label_scores": observed.get("label_scores"),
                "status": "PASS" if ok else "MISMATCH",
            })
        results.append({"id": case["id"], "text": case["text"], "checks": checks})
    return {
        "corpus": corpus.get("name", "RUAccent ё diagnostic"),
        "total_checks": total,
        "passed": passed,
        "mismatches": total - passed - missing,
        "missing": missing,
        "pass_rate": (passed / total) if total else 0.0,
        "cases": results,
        "warning": "Small diagnostic corpus only; not a general ё-restoration accuracy benchmark.",
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    download_parser = commands.add_parser("download", help="download only nn_yo_homograph artifacts")
    download_parser.add_argument("directory", type=Path)
    download_parser.add_argument("--timeout", type=int, default=90)
    verify_parser = commands.add_parser("verify", help="verify a previously downloaded bundle")
    verify_parser.add_argument("directory", type=Path)
    verify_parser.add_argument("--onnx-check", action="store_true")
    eval_parser = commands.add_parser("evaluate", help="run the actual ONNX model on the ё smoke corpus")
    eval_parser.add_argument("directory", type=Path)
    eval_parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    eval_parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "download":
            args.directory.mkdir(parents=True, exist_ok=True)
            for relative in FILES:
                print(f"Downloading {relative.as_posix()} …")
                download_one(relative, args.directory, args.timeout)
        if args.command in {"download", "verify"}:
            reports = validate_bundle(args.directory, deep_onnx=getattr(args, "onnx_check", False))
            report_path = write_report(args.directory, reports)
            for item in reports:
                print(f"PASS  {item.relative_path} ({item.size_bytes:,} bytes)")
                print(f"      SHA-256 {item.sha256}")
                print(f"      {item.detail}")
            print(f"\nStage 4.4 verification report: {report_path}")
            return 0
        corpus = load_corpus(args.corpus)
        runtime = load_probe_runtime(args.directory)
        report = evaluate_cases(corpus, lambda text: probe_with_runtime(text, runtime))
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"Checks: {report['passed']}/{report['total_checks']} matched; "
                  f"mismatches={report['mismatches']}; missing={report['missing']}")
            for case in report["cases"]:
                print(f"\n{case['id']}: {case['text']}")
                for check in case["checks"]:
                    conf = check.get("confidence")
                    conf_text = "n/a" if conf is None else f"{conf:.3f}"
                    print(f"  {check['status']:<8} {check['word']}: expected={check['expected']} "
                          f"actual={check['actual']} confidence={conf_text}")
            print("\n" + report["warning"])
        return 0
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
