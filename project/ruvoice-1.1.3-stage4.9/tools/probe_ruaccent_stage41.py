#!/usr/bin/env python3
"""Download/verify only RUAccent's first model stage (stress-usage classifier).

This is a development preflight tool. It does not install anything into Android
and deliberately does not download the other three ONNX models.
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
from typing import Any

REPOSITORY = "TigreGotico/stressonnx-models"
REVISION = "cb1594ddf81928e678a3a7ee7a22415e6e3a218f"
BUNDLE = "ru_ruaccent"
STAGE_DIR = Path("nn_stress_usage")
MODEL_RELATIVE = STAGE_DIR / "model.int8.onnx"
TOKENIZER_RELATIVE = STAGE_DIR / "tokenizer.json"
CONFIG_RELATIVE = STAGE_DIR / "config.json"
FILES = (MODEL_RELATIVE, TOKENIZER_RELATIVE, CONFIG_RELATIVE)
# The upstream ~111 MB figure refers to the fp32 reference graph. The pinned
# INT8 artefact is ~29 MB; 20 MB is only a corruption/LFS-pointer guard.
MIN_ONNX_BYTES = 20 * 1024 * 1024
USER_AGENT = "RuVoice-RUAccent-Stage4.2/1.0"


@dataclass(frozen=True)
class ArtifactReport:
    relative_path: str
    size_bytes: int
    sha256: str
    detail: str


def url_for(relative_path: Path) -> str:
    relative = relative_path.as_posix()
    if relative_path not in FILES:
        raise ValueError(f"Artifact is not part of stage 4.1: {relative}")
    return (
        f"https://huggingface.co/{REPOSITORY}/resolve/"
        f"{REVISION}/{BUNDLE}/{relative}"
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
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def validate_model(path: Path, deep_check: bool = False) -> str:
    if not path.is_file():
        raise ValueError(f"Missing model file: {path}")
    size = path.stat().st_size
    if size < MIN_ONNX_BYTES:
        raise ValueError(
            f"ONNX model is unexpectedly small ({size:,} bytes): {path}; "
            "possible Git-LFS pointer or incomplete download"
        )
    with path.open("rb") as stream:
        prefix = stream.read(128)
    lowered = prefix.lstrip().lower()
    if lowered.startswith((b"version https://git-lfs.github.com/spec/v1", b"<!doctype html", b"<html")):
        raise ValueError(f"Downloaded content is not an ONNX binary: {path}")
    # ONNX ModelProto is a protobuf message. The standard serialized ModelProto
    # begins with the ir_version field (field 1, varint => tag 0x08). This is a
    # cheap sanity check only; use --onnx-check for a full graph check.
    if not prefix or prefix[0] != 0x08:
        raise ValueError(f"Unexpected ONNX ModelProto header: {path}")
    detail = f"binary ONNX candidate; {size:,} bytes"
    if not deep_check:
        return detail + "; graph-level check not run (use --onnx-check)"
    try:
        import onnx  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("--onnx-check requires: python -m pip install onnx") from exc
    model = onnx.load(str(path), load_external_data=True)
    onnx.checker.check_model(model)
    return detail + f"; ONNX checker passed (IR {model.ir_version})"


def validate_tokenizer(path: Path) -> str:
    data = _read_json(path)
    model = data.get("model")
    if not isinstance(model, dict) or not isinstance(model.get("type"), str):
        raise ValueError(f"tokenizer.json has no model.type: {path}")
    vocab = model.get("vocab")
    # BPE and WordPiece tokenizers store their vocabulary as a JSON object.
    if not isinstance(vocab, dict) or not vocab:
        raise ValueError(f"tokenizer.json has no non-empty model.vocab: {path}")
    return f"tokenizer model={model['type']}; vocab entries={len(vocab):,}"


def validate_config(path: Path) -> str:
    data = _read_json(path)
    labels = data.get("id2label")
    if not isinstance(labels, dict) or len(labels) != 2:
        raise ValueError(f"config.json must define two id2label classes: {path}")
    normalized = {str(value).upper() for value in labels.values()}
    required = {"STRESS", "NO_STRESS"}
    if not required.issubset(normalized):
        raise ValueError(
            f"Unexpected stress classifier labels {sorted(normalized)}; "
            f"expected at least {sorted(required)}"
        )
    return "labels=" + ", ".join(str(labels[key]) for key in sorted(labels, key=str))


def validate_bundle(root: Path, deep_onnx: bool = False) -> list[ArtifactReport]:
    model_path = root / MODEL_RELATIVE
    tokenizer_path = root / TOKENIZER_RELATIVE
    config_path = root / CONFIG_RELATIVE
    model_detail = validate_model(model_path, deep_check=deep_onnx)
    return [
        ArtifactReport(MODEL_RELATIVE.as_posix(), model_path.stat().st_size, sha256_file(model_path), model_detail),
        ArtifactReport(TOKENIZER_RELATIVE.as_posix(), tokenizer_path.stat().st_size, sha256_file(tokenizer_path), validate_tokenizer(tokenizer_path)),
        ArtifactReport(CONFIG_RELATIVE.as_posix(), config_path.stat().st_size, sha256_file(config_path), validate_config(config_path)),
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
                raise RuntimeError(f"HTTP {status} for {relative_path}")
            expected = response.headers.get("Content-Length")
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                total += len(chunk)
                if relative_path == MODEL_RELATIVE:
                    print(f"\rDownloaded model: {total / (1024 * 1024):.1f} MiB", end="", flush=True)
            output.flush()
            os.fsync(output.fileno())
        if relative_path == MODEL_RELATIVE:
            print()
        if total <= 0:
            raise RuntimeError(f"Empty download: {relative_path}")
        if expected and expected.isdigit() and total != int(expected):
            raise RuntimeError(f"Truncated download for {relative_path}: {total} / {expected} bytes")
        partial.replace(destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def write_report(root: Path, reports: list[ArtifactReport]) -> Path:
    report_path = root / "stage4.1-verification.json"
    payload = {
        "repository": REPOSITORY,
        "revision": REVISION,
        "stage": "4.1-stress-usage-classifier",
        "artifacts": [report.__dict__ for report in reports],
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    download_parser = commands.add_parser("download", help="download only the first model stage")
    download_parser.add_argument("directory", type=Path)
    download_parser.add_argument("--timeout", type=int, default=90)
    verify_parser = commands.add_parser("verify", help="verify files already downloaded")
    verify_parser.add_argument("directory", type=Path)
    verify_parser.add_argument("--onnx-check", action="store_true", help="run onnx.checker if onnx is installed")
    args = parser.parse_args(argv)

    try:
        root: Path = args.directory
        if args.command == "download":
            root.mkdir(parents=True, exist_ok=True)
            for relative_path in FILES:
                print(f"Downloading {relative_path.as_posix()} …")
                download_one(relative_path, root, args.timeout)
        reports = validate_bundle(root, deep_onnx=getattr(args, "onnx_check", False))
        report_path = write_report(root, reports)
        for report in reports:
            print(f"PASS  {report.relative_path} ({report.size_bytes:,} bytes)")
            print(f"      SHA-256 {report.sha256}")
            print(f"      {report.detail}")
        print(f"\nStage 4.1 verification report: {report_path}")
        return 0
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
