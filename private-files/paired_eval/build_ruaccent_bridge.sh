#!/usr/bin/env bash
set -euo pipefail

ROOT="${GITHUB_WORKSPACE}/project/ruvoice-1.1.3-stage4.9"
WORK="${RUNNER_TEMP}/ruvoice-paired-bridge"
mkdir -p "$WORK"

MAVEN="https://repo1.maven.org/maven2"
ORT_VERSION="1.22.0"
JSON_VERSION="20240303"

curl --fail --location --retry 3 --silent --show-error \
  "$MAVEN/com/microsoft/onnxruntime/onnxruntime/$ORT_VERSION/onnxruntime-$ORT_VERSION.jar" \
  --output "$WORK/onnxruntime.jar"
curl --fail --location --retry 3 --silent --show-error \
  "$MAVEN/org/json/json/$JSON_VERSION/json-$JSON_VERSION.jar" \
  --output "$WORK/json.jar"

cd "$ROOT/native"
cargo build --release

cd "$ROOT"
CP="$WORK/onnxruntime.jar:$WORK/json.jar"
OUT="$GITHUB_WORKSPACE/private-files/paired_eval/ruaccent-bridge.jar"

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
  "$GITHUB_WORKSPACE/private-files/paired_eval/RuAccentBridge.kt" \
  -include-runtime -d "$OUT"

echo "ONNXRUNTIME_JAR=$WORK/onnxruntime.jar" >> "$GITHUB_ENV"
echo "JSON_JAR=$WORK/json.jar" >> "$GITHUB_ENV"
echo "RUACCENT_BRIDGE_CLASSPATH=$OUT:$WORK/onnxruntime.jar:$WORK/json.jar" >> "$GITHUB_ENV"
echo "RUACCENT_NATIVE_DIR=$ROOT/native/target/release" >> "$GITHUB_ENV"
ls -lh "$OUT" "$WORK/onnxruntime.jar" "$WORK/json.jar"
