#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="/tmp/ruvoice-char-accent-policy-tests.jar"
kotlinc "$ROOT/app/src/main/java/ru/kost/ruvoice/text/RuAccentCharAccentPolicy.kt" \
  "$ROOT/tools/test_ruaccent_char_accent_policy.kt" -include-runtime -d "$OUT"
java -Dfile.encoding=UTF-8 -jar "$OUT"
