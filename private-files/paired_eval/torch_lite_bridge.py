#!/usr/bin/env python3
"""Persistent CPU bridge to the official TorchScript-Lite Silero stress models."""
from __future__ import annotations

import faulthandler
import json
import os
import sys
import traceback
from pathlib import Path

import torch
from torch.jit.mobile import _load_for_lite_interpreter

TORCH_VERSION = torch.__version__.split("+", 1)[0]
if TORCH_VERSION != "2.1.0":
    raise RuntimeError(
        "Official RuVoice 1.1.3 uses pytorch_android_lite 2.1.0; "
        f"desktop TorchScript-Lite bridge must match it, got {torch.__version__}"
    )
torch.set_num_threads(1)

accentor_path, homo_path = sys.argv[1:3]
log_stream = None
log_path = os.environ.get("RUVOICE_TORCH_BRIDGE_LOG")
if log_path:
    try:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        log_stream = open(log_path, "a", encoding="utf-8", buffering=1)
        faulthandler.enable(file=log_stream, all_threads=True)
    except Exception as error:
        sys.stderr.write("TORCH_BRIDGE_LOG_OPEN_FAILED=" + repr(error) + "\n")
        sys.stderr.flush()


def diagnostic(message: str) -> None:
    line = "TORCH_BRIDGE_DIAGNOSTIC=" + message
    sys.stderr.write(line + "\n")
    sys.stderr.flush()
    if log_stream is not None:
        log_stream.write(line + "\n")
        log_stream.flush()


def emit(value):
    sys.stdout.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def describe_tensor(value) -> str:
    if not isinstance(value, torch.Tensor):
        return type(value).__name__
    return "Tensor(shape=" + repr(tuple(value.shape)) + ", dtype=" + str(value.dtype) + ")"


MAX_ACCENTOR_BATCH_SIZE = 32
accentor_batch_fallbacks = 0
accentor_batch_chunks = 0


def concatenate_rows(left_stress, left_yo, right_stress, right_yo):
    # These are Python rows, not tensors: model batches can have different padded widths.
    return left_stress + right_stress, left_yo + right_yo


def accentor_predict(words):
    """Return per-word probability rows; bound batch size before entering Torch Lite."""
    global accentor_batch_fallbacks, accentor_batch_chunks
    # Do not first submit an oversized request: a failed Lite forward can leave its
    # interpreter in a bad state, making every later retry fail too.
    if len(words) > MAX_ACCENTOR_BATCH_SIZE:
        accentor_batch_chunks += 1
        middle = len(words) // 2
        left_stress, left_yo = accentor_predict(words[:middle])
        right_stress, right_yo = accentor_predict(words[middle:])
        return concatenate_rows(left_stress, left_yo, right_stress, right_yo)
    try:
        output = accentor(words)
        if isinstance(output, (tuple, list)):
            stress_logits = output[0]
            yo_logits = output[1] if len(output) > 1 else None
        else:
            stress_logits, yo_logits = output, None

        if not isinstance(stress_logits, torch.Tensor):
            raise RuntimeError("Accentor stress output is not a tensor")
        stress = torch.softmax(stress_logits, dim=1).cpu().tolist()
        yo = (
            torch.softmax(yo_logits, dim=1).cpu().tolist()
            if isinstance(yo_logits, torch.Tensor)
            else [[] for _ in words]
        )
        if len(stress) != len(words) or len(yo) != len(words):
            raise RuntimeError(
                "Accentor output rows do not align with input words: "
                f"words={len(words)} stress={len(stress)} yo={len(yo)}"
            )
        return stress, yo
    except Exception as error:
        if len(words) <= 1:
            raise
        accentor_batch_fallbacks += 1
        if accentor_batch_fallbacks <= 10:
            diagnostic(
                "ACCENTOR_BATCH_SPLIT words=" + str(len(words)) +
                " error=" + type(error).__name__ + ": " + str(error)
            )
        middle = len(words) // 2
        left_stress, left_yo = accentor_predict(words[:middle])
        right_stress, right_yo = accentor_predict(words[middle:])
        return concatenate_rows(left_stress, left_yo, right_stress, right_yo)


diagnostic("START python=" + sys.version.replace("\n", " ") + " torch=" + torch.__version__)
diagnostic("MODELS accentor=" + str(Path(accentor_path).resolve()) + " homo=" + str(Path(homo_path).resolve()))
torch.set_num_threads(2)
accentor = _load_for_lite_interpreter(accentor_path)
diagnostic("ACCENTOR_MODEL_LOADED")
homograph = _load_for_lite_interpreter(homo_path)
diagnostic("HOMO_MODEL_LOADED")

with torch.no_grad():
    diagnostic("STARTUP_SELFTEST_BEGIN")
    test = accentor(["замок"])
    if not isinstance(test, (tuple, list)) or len(test) < 1:
        raise RuntimeError("Unexpected accentor output during startup self-test")
    diagnostic("STARTUP_SELFTEST_OK output=" + repr([describe_tensor(x) for x in test]) if isinstance(test, (tuple, list)) else "STARTUP_SELFTEST_OK output=" + describe_tensor(test))
    emit({"ready": True})

    for line_number, line in enumerate(sys.stdin, start=1):
        try:
            request = json.loads(line)
            op = request.get("op")
            if op == "quit":
                diagnostic("QUIT_REQUEST")
                break

            if op == "accentor":
                words = request["words"]
                diagnostic("REQUEST_BEGIN line=" + str(line_number) + " op=accentor words=" + str(len(words)))
                stress, yo = accentor_predict(words)
                diagnostic(
                    "ACCENTOR_OUTPUT words=" + str(len(words)) +
                    " stress_rows=" + str(len(stress)) +
                    " yo_rows=" + str(len(yo))
                )
                emit({"stress": stress, "yo": yo})
                diagnostic("REQUEST_OK line=" + str(line_number) + " op=accentor")
            elif op == "homo":
                rows = request["ids"]
                starts = request["starts"]
                ends = request["ends"]
                diagnostic("REQUEST_BEGIN line=" + str(line_number) + " op=homo rows=" + str(len(rows)))
                if not rows:
                    emit({"probabilities": []})
                    diagnostic("REQUEST_OK line=" + str(line_number) + " op=homo empty")
                    continue
                width = max(len(row) for row in rows)
                pad_id = int(request.get("pad_id", 0))
                padded = [row + [pad_id] * (width - len(row)) for row in rows]
                logits = homograph(
                    torch.tensor(padded, dtype=torch.long),
                    torch.tensor(starts, dtype=torch.long),
                    torch.tensor(ends, dtype=torch.long),
                ).reshape(-1)
                probabilities = torch.sigmoid(logits).cpu().tolist()
                if len(probabilities) != len(rows):
                    raise RuntimeError(
                        "Homograph output rows do not align with input: "
                        f"rows={len(rows)} probabilities={len(probabilities)}"
                    )
                emit({"probabilities": probabilities})
                diagnostic("REQUEST_OK line=" + str(line_number) + " op=homo")
            else:
                raise RuntimeError("Unknown operation: " + str(op))
        except Exception as error:
            diagnostic(
                "REQUEST_ERROR line=" + str(line_number) + " error=" +
                type(error).__name__ + ": " + str(error)
            )
            diagnostic(traceback.format_exc().rstrip().replace("\n", " | "))
            emit({"error": type(error).__name__ + ": " + str(error)})

diagnostic("ACCENTOR_BATCH_FALLBACKS=" + str(accentor_batch_fallbacks))
diagnostic("ACCENTOR_BATCH_CHUNKS=" + str(accentor_batch_chunks))
diagnostic("BRIDGE_EXIT")
if log_stream is not None:
    log_stream.close()
