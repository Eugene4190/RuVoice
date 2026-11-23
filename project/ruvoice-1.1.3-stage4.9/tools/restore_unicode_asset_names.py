#!/usr/bin/env python3
"""Restore asset filenames encoded as #Uhhhh sequences in repository exports.

The dictionary payloads are not modified. Only file names are converted so the
Android AssetManager and tests can open the documented UTF-8 paths.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIRS = (
    ROOT / "app/src/main/assets/dicts/stress",
    ROOT / "app/src/main/assets/dicts/replace",
)
ESCAPE = re.compile(r"#U([0-9A-Fa-f]{4,6})")


def decode_name(name: str) -> str:
    def replace(match: re.Match[str]) -> str:
        codepoint = int(match.group(1), 16)
        if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
            raise ValueError(f"Invalid Unicode code point in filename: {match.group(0)}")
        return chr(codepoint)

    return ESCAPE.sub(replace, name)


def main() -> None:
    changed = 0
    for directory in ASSET_DIRS:
        if not directory.is_dir():
            raise SystemExit(f"Required dictionary asset directory is missing: {directory}")
        for source in sorted(directory.iterdir()):
            if not source.is_file() or "#U" not in source.name:
                continue
            target = source.with_name(decode_name(source.name))
            if target.exists():
                raise SystemExit(f"Refusing to overwrite existing asset: {target}")
            source.rename(target)
            print(f"Restored filename: {source.name} -> {target.name}")
            changed += 1

    required = (
        ROOT / "app/src/main/assets/dicts/stress/Системный.txt",
        ROOT / "app/src/main/assets/dicts/replace/Системный.txt",
    )
    for path in required:
        if not path.is_file() or path.stat().st_size == 0:
            raise SystemExit(f"Required system dictionary is missing or empty: {path}")
        print(f"Verified {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")
    print(f"Unicode asset filename restoration complete ({changed} renamed).")


if __name__ == "__main__":
    main()
