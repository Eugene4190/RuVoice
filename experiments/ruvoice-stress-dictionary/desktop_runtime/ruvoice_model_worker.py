#!/usr/bin/env python3
"""Single portable PyInstaller worker for RuVoice's Silero and independent stress models."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

from portable_stdio import configure_utf8_stdio

# The predictor prints Unicode status messages (including emoji). PyInstaller's
# Windows console otherwise inherits the legacy CP1252 code page and can abort
# model initialization before the book audit starts. Configure the streams
# before importing or invoking either model.
configure_utf8_stdio()

# Import at module scope so PyInstaller collects the native/runtime dependencies
# for both modes into the same portable directory.
import torch
from torch.jit.mobile import _load_for_lite_interpreter
from ruaccent import load_accentor


def resource_root() -> Path:
    root = getattr(sys, "_MEIPASS", None)
    return Path(root).resolve() if root else Path(__file__).resolve().parent


def main() -> int:
    root = resource_root()
    if len(sys.argv) > 1 and sys.argv[1] == "--third-model":
        script = root / "audit_book_third_model.py"
        if not script.is_file():
            raise FileNotFoundError("Не найден модуль независимой модели ударений.")
        sys.argv = [str(script), *sys.argv[2:]]
        runpy.run_path(str(script), run_name="__main__")
        return 0

    script = root / "torch_lite_bridge.py"
    if not script.is_file():
        raise FileNotFoundError("Не найден мост официальной модели RuVoice.")
    # Kotlin starts the process with: <worker.exe> accentor.ptl homo.ptl
    sys.argv = [str(script), *sys.argv[1:]]
    runpy.run_path(str(script), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
