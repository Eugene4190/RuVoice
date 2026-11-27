#!/usr/bin/env python3
"""Apply exactly one reviewed book-only phrase hint to a staged Silero JSON asset.

The large tools/phrases_extra.txt is an experimental collection and must not be
applied wholesale during a book-specific evaluation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

WORD = "сети"
PHRASE = "сети значений"
VARIANT = "с+ети"


def apply(path: Path) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    phrases = data.setdefault("phrases", {})
    entries = phrases.setdefault(WORD, [])
    matches = [entry for entry in entries if len(entry) >= 2 and entry[0] == PHRASE]
    if matches:
        if any(entry[1] != VARIANT for entry in matches):
            raise ValueError(f"Conflicting existing phrase entry for {PHRASE!r}: {matches}")
        # De-duplicate only this exact phrase; leave all other entries untouched.
        kept = [entry for entry in entries if not (len(entry) >= 2 and entry[0] == PHRASE)]
        kept.append([PHRASE, VARIANT])
        phrases[WORD] = sorted(kept, key=lambda item: -len(item[0]))
        changed = len(kept) != len(entries) or len(matches) != 1
    else:
        entries.append([PHRASE, VARIANT])
        phrases[WORD] = sorted(entries, key=lambda item: -len(item[0]))
        changed = True
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("silero_json", type=Path)
    args = parser.parse_args()
    changed = apply(args.silero_json)
    print(f"BOOK_PHRASE_OVERRIDE={'UPDATED' if changed else 'ALREADY_PRESENT'} word={WORD} phrase={PHRASE!r} variant={VARIANT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
