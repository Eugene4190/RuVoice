#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="/tmp/ruvoice-install-manifest-policy-tests.jar"
kotlinc \
  "$ROOT/app/src/main/java/ru/kost/ruvoice/text/RuAccentInstallManifestPolicy.kt" \
  "$ROOT/app/src/main/java/ru/kost/ruvoice/text/RuAccentInt8ModelManifest.kt" \
  "$ROOT/tools/test_ruaccent_install_manifest_policy.kt" \
  -include-runtime -d "$OUT"
java -Dfile.encoding=UTF-8 -jar "$OUT"
