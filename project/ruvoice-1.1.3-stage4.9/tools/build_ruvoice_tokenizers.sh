#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="arm64-v8a"
PLATFORM="23"

if ! command -v cargo >/dev/null 2>&1 || ! command -v rustup >/dev/null 2>&1; then
  echo "Не найден Rust toolchain. Установи Rust через https://rustup.rs/" >&2
  exit 2
fi
if ! cargo ndk --help >/dev/null 2>&1; then
  echo "Не найден cargo-ndk. Установи его командой: cargo install cargo-ndk" >&2
  exit 2
fi

if ! rustup target list --installed | grep -qx 'aarch64-linux-android'; then
  echo "Добавляю Rust target aarch64-linux-android..."
  rustup target add aarch64-linux-android
fi

if [[ -z "${ANDROID_NDK_HOME:-}" && -z "${ANDROID_NDK_ROOT:-}" && -z "${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}" ]]; then
  echo "Android SDK/NDK не найден в переменных окружения. Укажи ANDROID_NDK_HOME или ANDROID_SDK_ROOT." >&2
  exit 2
fi

mkdir -p "$ROOT/app/src/main/jniLibs"
cd "$ROOT/native"
cargo ndk -t "$TARGET" -p "$PLATFORM" -o "$ROOT/app/src/main/jniLibs" build --release

LIB="$ROOT/app/src/main/jniLibs/$TARGET/libruvoice_tokenizers.so"
if [[ ! -s "$LIB" ]]; then
  echo "Сборка завершилась без $LIB" >&2
  exit 1
fi

echo "Готово: $LIB"
