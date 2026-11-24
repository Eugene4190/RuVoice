# Run marker

This file is a one-time trigger for the **Build automatic RuVoice stress dictionary** workflow. The workflow downloads the current Russian Wiktionary Wiktextract dump, runs the official AOT + Wiktionary consensus correction generator in an isolated temporary checkout, and commits only the generated importable TXT and provenance reports back to this branch.

Large source dumps and temporary model files remain ignored and are not committed.

Retry trigger: 2026-11-24, full Russian AOT dataset path and minimum-form sanity check.
