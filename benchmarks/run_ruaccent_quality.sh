#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "\${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="$REPO_ROOT/project/ruvoice-1.1.3-stage4.9"
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

cd "$PROJECT/native"
cargo build --release

cd "$REPO_ROOT"
CP="$WORK/onnxruntime.jar:$WORK/json.jar"
OUT="$WORK/ruaccent-quality-evaluation.jar"

kotlinc \
  -classpath "$CP" \
  "$PROJECT/app/src/main/java/ru/kost/ruvoice/text/RuAccentDownloadPolicy.kt" \
  "$PROJECT/app/src/main/java/ru/kost/ruvoice/text/RuAccentHttpDownloader.kt" \
  "$PROJECT/app/src/main/java/ru/kost/ruvoice/text/RuAccentInstallManifestPolicy.kt" \
  "$PROJECT/app/src/main/java/ru/kost/ruvoice/text/RuAccentInt8ModelManifest.kt" \
  "$PROJECT/app/src/main/java/ru/kost/ruvoice/text/RuAccentCharAccentPolicy.kt" \
  "$PROJECT/app/src/main/java/ru/kost/ruvoice/text/RuAccentOmographContext.kt" \
  "$PROJECT/app/src/main/java/ru/kost/ruvoice/text/IndependentStressCorrection.kt" \
  "$PROJECT/app/src/main/java/ru/kost/ruvoice/text/HfTokenizer.kt" \
  "$PROJECT/app/src/main/java/ru/kost/ruvoice/text/RuAccentOnnxCorrector.kt" \
  "$REPO_ROOT/benchmarks/evaluate_ruaccent_quality.kt" \
  -include-runtime -d "$OUT"

mkdir -p "$PROJECT/app/build"
java \
  -Djava.library.path="$PROJECT/native/target/release" \
  -cp "$OUT:$CP" \
  ru.kost.ruvoice.text.Evaluate_ruaccent_qualityKt \
  "$PROJECT/app/src/test/resources/homograph_eval/HomographResolutionEval.json" \
  "$PROJECT/tools/data/ruaccent_stress_usage_smoke.json" \
  "$PROJECT/tools/data/ruaccent_yo_smoke.json" \
  "$PROJECT/app/build/ruaccent_quality_report.json"
