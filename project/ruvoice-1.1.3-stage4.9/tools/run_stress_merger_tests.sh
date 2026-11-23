#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
command -v kotlinc >/dev/null 2>&1 || { echo "Нужен kotlinc 1.9+" >&2; exit 2; }
TMP_JAR="$(mktemp -t ruvoice-stress-tests.XXXXXX.jar)"
trap 'rm -f "$TMP_JAR"' EXIT
kotlinc \
  "$ROOT/app/src/main/java/ru/kost/ruvoice/text/IndependentStressCorrection.kt" \
  "$ROOT/tools/test_stress_merger.kt" \
  -include-runtime -d "$TMP_JAR"
java -jar "$TMP_JAR"
