#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$HERE" rev-parse --show-toplevel)"
CACHE="$HERE/.cache"
RAW="$HERE/data/raw"
WIKT_GZ="${WIKT_GZ:-$RAW/raw-wiktextract-data.jsonl.gz}"
AOT_REPO="$CACHE/morph_dict"
VENV="$CACHE/venv"
PY="$VENV/bin/python"
WIKT_URL="https://kaikki.org/ruwiktionary/raw-wiktextract-data.jsonl.gz"
UPSTREAM_URL="https://github.com/kost-t-human/ruvoice-tts.git"
AOT_URL="https://github.com/sokirko74/morph_dict.git"

for command in git curl python3 gzip sha256sum; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Не найдена команда: $command" >&2
    exit 1
  }
done

mkdir -p "$CACHE" "$RAW" "$HERE/output" "$HERE/reports"

if [[ ! -s "$WIKT_GZ" ]] || ! gzip -t "$WIKT_GZ" >/dev/null 2>&1; then
  echo "Скачиваю сжатый raw Wiktextract JSONL (~272.5 МБ по снимку от 2026-11-01)."
  curl --fail --location --retry 3 --continue-at - "$WIKT_URL" -o "$WIKT_GZ"
fi
gzip -t "$WIKT_GZ" || {
  echo "Загруженный архив повреждён: $WIKT_GZ" >&2
  exit 2
}

if [[ ! -d "$AOT_REPO/.git" ]]; then
  echo "Загружаю словарь AOT..."
  git clone --depth 1 "$AOT_URL" "$AOT_REPO"
else
  git -C "$AOT_REPO" fetch --depth 1 origin
  git -C "$AOT_REPO" reset --hard FETCH_HEAD
fi

MORPHS="$(find "$AOT_REPO" -type f -name morphs.json -print -quit)"
GRAMTAB="$(find "$AOT_REPO" -type f -name gramtab.json -print -quit)"
if [[ -z "$MORPHS" || -z "$GRAMTAB" ]]; then
  echo "В скачанном morph_dict не найдены morphs.json и gramtab.json." >&2
  echo "Укажите данные AOT вручную и проверьте структуру репозитория." >&2
  exit 3
fi
AOT_DIR="$(dirname "$MORPHS")"
if [[ ! -f "$AOT_DIR/gramtab.json" ]]; then
  AOT_DIR="$(dirname "$GRAMTAB")"
fi
if [[ ! -f "$AOT_DIR/morphs.json" || ! -f "$AOT_DIR/gramtab.json" ]]; then
  echo "morphs.json и gramtab.json должны лежать в одном каталоге." >&2
  exit 3
fi

if [[ ! -x "$PY" ]]; then
  python3 -m venv "$VENV"
fi
if ! "$PY" -c "import silero_stress" >/dev/null 2>&1; then
  echo "Устанавливаю silero-stress в изолированное окружение..."
  "$PY" -m pip install --upgrade pip
  "$PY" -m pip install silero-stress
fi

WORK="$(mktemp -d "/tmp/ruvoice-stress.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
UPSTREAM="$WORK/ruvoice-tts"

echo "Получаю чистую копию официального RuVoice во временную папку..."
git clone --depth 1 --single-branch --branch master "$UPSTREAM_URL" "$UPSTREAM"
UPSTREAM_SHA="$(git -C "$UPSTREAM" rev-parse HEAD)"

echo "Строю формы AOT и Викисловаря..."
(
  cd "$UPSTREAM"
  "$PY" tools/aot_forms.py "$AOT_DIR"
  # The current Kaikki download is raw Wiktextract JSONL in gzip format.
  # Patch only this disposable upstream checkout so the official parser streams gzip without a 2.3 GB unpack.
  "$PY" - <<'PY'
from pathlib import Path
p = Path("tools/wikt_forms.py")
s = p.read_text(encoding="utf-8")
s = s.replace("import json, os, sys, collections, re", "import gzip, json, os, sys, collections, re")
old = "    with open(SRC, encoding='utf-8') as src:"
new = '    opener = gzip.open if SRC.endswith(".gz") else open\n    with opener(SRC, "rt", encoding="utf-8") as src:'
if old not in s:
    raise SystemExit("Не удалось безопасно адаптировать wikt_forms.py к gzip")
p.write_text(s.replace(old, new), encoding="utf-8")
PY
  "$PY" tools/wikt_forms.py "$WIKT_GZ"
  "$PY" tools/aot_survey.py
  # Перезаписывается только tools/stress_fixes.txt во временном клоне, не в твоём репозитории.
  "$PY" tools/stress_fixes.py build
)

ARGS=()
STAGE_FIXES="$REPO_ROOT/project/ruvoice-1.1.3-stage4.9/tools/stress_fixes.txt"
if [[ -f "$STAGE_FIXES" ]]; then
  ARGS+=(--source-list "$STAGE_FIXES")
fi
ARGS+=(--consensus-source-list "$UPSTREAM/tools/stress_fixes.txt")

if [[ -f "$UPSTREAM/app/build/stress_candidates.txt" ]]; then
  ARGS+=(--candidates "$UPSTREAM/app/build/stress_candidates.txt")
fi
if [[ -f "$UPSTREAM/app/build/stress_fixes_new.txt" ]]; then
  ARGS+=(--review-candidates "$UPSTREAM/app/build/stress_fixes_new.txt")
fi

"$PY" "$HERE/build_dictionary.py" "${ARGS[@]}" \
  --output "$HERE/output/RuVoice_AutoStress.txt" \
  --report "$HERE/reports/RuVoice_AutoStress_review.tsv" \
  --manifest "$HERE/reports/run_manifest.json"

printf '{\n  "upstream_repository": "%s",\n  "upstream_commit": "%s",\n  "aot_repository": "%s",\n  "wikt_dump": "%s"\n}\n' \
  "$UPSTREAM_URL" "$UPSTREAM_SHA" "$AOT_URL" "$WIKT_GZ" \
  > "$HERE/reports/source_versions.json"
WIKT_SHA256="$(sha256sum "$WIKT_GZ" | cut -d ' ' -f 1)"
printf '{\n  "url": "%s",\n  "sha256": "%s",\n  "compressed_bytes": %s\n}\n' \
  "$WIKT_URL" "$WIKT_SHA256" "$(wc -c < "$WIKT_GZ" | tr -d ' ')" \
  > "$HERE/reports/wiktionary_source.json"

echo
echo "Готово. Все постоянные результаты сохранены в:"
echo "  $HERE/output/"
echo "  $HERE/reports/"
echo "Промежуточные исходники и скачанные корпуса остаются в .cache/ и data/raw/ и не коммитятся."
