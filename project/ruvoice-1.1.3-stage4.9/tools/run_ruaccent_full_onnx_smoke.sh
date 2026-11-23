#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

ORT_VERSION="1.32.0"
JSON_VERSION="20240303"
MAVEN="https://repo.maven.apache.org/maven2"

curl --fail --location --silent --show-error \
  "$MAVEN/com/microsoft/onnxruntime/onnxruntime/$ORT_VERSION/onnxruntime-$ORT_VERSION.jar" \
  --output "$WORK/onnxruntime.jar"
curl --fail --location --silent --show-error \
  "$MAVEN/org/json/json/$JSON_VERSION/json-$JSON_VERSION.jar" \
  --output "$WORK/json.jar"

cd "$ROOT/native"
cargo build --release

cd "$ROOT"
CP="$WORK/onnxruntime.jar:$WORK/json.jar"
OUT="$WORK/ruaccent-real-model-smoke.jar"

kotlinc \
  -classpath "$CP" \
  "app/src/main/java/ru/kost/ruvoice/text/RuAccentDownloadPolicy.kt" \
  "app/src/main/java/ru/kost/ruvoice/text/RuAccentHttpDownloader.kt" \
  "app/src/main/java/ru/kost/ruvoice/text/RuAccentInstallManifestPolicy.kt" \
  "app/src/main/java/ru/kost/ruvoice/text/RuAccentInt8ModelManifest.kt" \
  "app/src/main/java/ru/kost/ruvoice/text/RuAccentCharAccentPolicy.kt" \
  "app/src/main/java/ru/kost/ruvoice/text/RuAccentOmographContext.kt" \
  "app/src/main/java/ru/kost/ruvoice/text/IndependentStressCorrection.kt" \
  "app/src/main/java/ru/kost/ruvoice/text/HfTokenizer.kt" \
  "app/src/main/java/ru/kost/ruvoice/text/RuAccentOnnxCorrector.kt" \
  "tools/test_ruaccent_full_onnx_smoke.kt" \
  -include-runtime -d "$OUT"

java \
  -Djava.library.path="$ROOT/native/target/release" \
  -cp "$OUT:$CP" \
  ru.kost.ruvoice.text.Test_ruaccent_full_onnx_smokeKt
