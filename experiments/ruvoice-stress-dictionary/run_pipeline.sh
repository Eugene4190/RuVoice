#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$HERE" rev-parse --show-toplevel)"
CACHE="$HERE/.cache"
RAW="$HERE/data/raw"
WIKT_JSONL="\${WIKT_JSONL:-$RAW/kaikki.org-dictionary-Russian.jsonl}"
AOT_REPO="$CACHE/morph_dict"
VENV="$CACHE/venv"
PY="$VENV/bin/python"
WIKT_URL="https://kaikki.org/dictionary/Russian/kaikki.org-dictionary-Russian.jsonl"
UPSTREAM_URL="https://github.com/kost-t-human/ruvoice-tts.git"
AOT_URL="https://github.com/sokirko74/morph_dict.git"

for command in git curl python3; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Не найдена команда: $command" >&2
    exit 1
  }
done

mkdir -p "$CACHE" "$RAW" "$HERE/output" "$HERE/reports"

if [[ ! -f "$WIKT_JSONL" ]]; then
  if [[ "\${DOWNLOAD_WIKT:-0}" == "1" ]]; then
    echo "Скачиваю словарный корпус Kaikki (~900 МБ)."
    curl --fail --location --retry 3 --continue-at - "$WIKT_URL" -o "$WIKT_JSONL"
  else
    cat >&2 <<EOF
Не найден дамп Викисловаря:
  $WIKT_JSONL

Файл большой (около 900 МБ) и не включается в Git.
Положите JSONL туда или запустите:
  DOWNLOAD_WIKT=1 $0

Можно указать другой путь через WIKT_JSONL=/путь/к/файлу.jsonl.
EOF
    exit 2
  fi
fi

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
  "$PY" tools/wikt_forms.py "$WIKT_JSONL"
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

"$PY" "$HERE/build_dictionary.py" "\${ARGS[@]}" \
  --output "$HERE/output/RuVoice_AutoStress.txt" \
  --report "$HERE/reports/RuVoice_AutoStress_review.tsv" \
  --manifest "$HERE/reports/run_manifest.json"

printf '{\n  "upstream_repository": "%s",\n  "upstream_commit": "%s",\n  "aot_repository": "%s",\n  "wikt_dump": "%s"\n}\n' \
  "$UPSTREAM_URL" "$UPSTREAM_SHA" "$AOT_URL" "$WIKT_JSONL" \
  > "$HERE/reports/source_versions.json"

echo
echo "Готово. Все постоянные результаты сохранены в:"
echo "  $HERE/output/"
echo "  $HERE/reports/"
echo "Промежуточные исходники и скачанные корпуса остаются в .cache/ и data/raw/ и не коммитятся."
