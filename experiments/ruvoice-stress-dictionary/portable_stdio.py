#!/usr/bin/env python3
"""Keep the portable RuVoice worker's text protocol and diagnostics Unicode-safe."""
from __future__ import annotations

import os
import sys


def _configure_stream(name: str) -> None:
    stream = getattr(sys, name, None)
    if stream is None:
        return

    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        # Input must be valid UTF-8; output should preserve every Unicode message.
        errors = "strict" if name == "stdin" else "backslashreplace"
        reconfigure(encoding="utf-8", errors=errors)
        return

    encoding = getattr(stream, "encoding", None)
    normalized = str(encoding or "").lower().replace("_", "-")
    if normalized not in {"utf-8", "utf8"} and getattr(stream, "buffer", None) is not None:
        raise RuntimeError(
            f"Cannot configure {name} as UTF-8 (current encoding: {encoding!r})"
        )


def configure_utf8_stdio() -> None:
    """Configure this process and child Python processes to use UTF-8 streams."""
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    for name in ("stdin", "stdout", "stderr"):
        _configure_stream(name)
