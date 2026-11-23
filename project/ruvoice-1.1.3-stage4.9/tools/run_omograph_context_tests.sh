#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${TMPDIR:-/tmp}/ruvoice-omograph-context-tests.jar"
kotlinc \
  "$ROOT/app/src/main/java/ru/kost/ruvoice/text/RuAccentOmographContext.kt" \
  "$ROOT/tools/test_ruaccent_omograph_context.kt" \
  -include-runtime -d "$OUT"
java -jar "$OUT"
