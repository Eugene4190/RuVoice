#!/usr/bin/env python3
"""Persistent CPU bridge to the official TorchScript-Lite Silero stress models."""
import json
import sys
import torch
from torch.jit.mobile import _load_for_lite_interpreter

accentor_path, homo_path = sys.argv[1:3]
torch.set_num_threads(2)
accentor = _load_for_lite_interpreter(accentor_path)
homograph = _load_for_lite_interpreter(homo_path)

def emit(value):
    sys.stdout.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()

with torch.no_grad():
    test = accentor(["замок"])
    if not isinstance(test, (tuple, list)) or len(test) < 1:
        raise RuntimeError("Unexpected accentor output")
    emit({"ready": True})
    for line in sys.stdin:
        request = json.loads(line)
        op = request.get("op")
        if op == "quit":
            break
        if op == "accentor":
            words = request["words"]
            output = accentor(words)
            if isinstance(output, (tuple, list)):
                stress_logits = output[0]
                yo_logits = output[1] if len(output) > 1 else None
            else:
                stress_logits, yo_logits = output, None
            stress = torch.softmax(stress_logits, dim=1).cpu().tolist()
            yo = (
                torch.softmax(yo_logits, dim=1).cpu().tolist()
                if isinstance(yo_logits, torch.Tensor)
                else [[] for _ in words]
            )
            emit({"stress": stress, "yo": yo})
        elif op == "homo":
            rows = request["ids"]
            starts = request["starts"]
            ends = request["ends"]
            if not rows:
                emit({"probabilities": []})
                continue
            width = max(len(row) for row in rows)
            padded = [row + [0] * (width - len(row)) for row in rows]
            logits = homograph(
                torch.tensor(padded, dtype=torch.long),
                torch.tensor(starts, dtype=torch.long),
                torch.tensor(ends, dtype=torch.long),
            ).reshape(-1)
            emit({"probabilities": torch.sigmoid(logits).cpu().tolist()})
        else:
            raise RuntimeError("Unknown operation: " + str(op))
