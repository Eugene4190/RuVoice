#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="/tmp/ruvoice-http-download-tests.jar"
kotlinc \
  "$ROOT/app/src/main/java/ru/kost/ruvoice/text/RuAccentDownloadPolicy.kt" \
  "$ROOT/app/src/main/java/ru/kost/ruvoice/text/RuAccentHttpDownloader.kt" \
  "$ROOT/tools/test_ruaccent_http_downloader.kt" \
  -include-runtime -d "$OUT"
java -Dfile.encoding=UTF-8 -jar "$OUT"
