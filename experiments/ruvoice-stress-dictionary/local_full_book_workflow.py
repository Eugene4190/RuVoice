#!/usr/bin/env python3
"""Run the original RuVoice production engine locally and package book-scoped user lists."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from book_tool_paths import resolve_app_paths

REPO_ROOT, TOOL_DIR = resolve_app_paths(__file__)


def resolve_engine_root(
    repo_root: Path,
    *,
    frozen: bool,
    bundle_root: Path | None,
    executable_dir: Path,
) -> Path:
    """Find a side-by-side engine folder in a PyInstaller one-file or portable ZIP build."""
    if not frozen:
        return Path(repo_root).resolve()
    candidates = [Path(value).resolve() for value in (bundle_root, executable_dir) if value is not None]
    for candidate in candidates:
        if (candidate / "engine").is_dir():
            return candidate
    # Prefer a stable location beside the executable so the missing-engine message is actionable.
    return Path(executable_dir).resolve()


APP_ROOT = resolve_engine_root(
    REPO_ROOT,
    frozen=bool(getattr(sys, "frozen", False)),
    bundle_root=Path(sys._MEIPASS) if getattr(sys, "_MEIPASS", None) else None,
    executable_dir=Path(sys.executable).resolve().parent,
)
ENGINE = APP_ROOT / "engine"
# Kotlin object main wraps JUnitCore and runs the original production RuVoice paired test.
JVM_ENTRYPOINT = "ru.kost.ruvoice.text.UploadedEpubPairedEvaluationMain"
REFERENCE_SHA256 = "114161f5c91caa7c39419c5b7979e34e5a1d34a9e84f21683f63131bd3a49119"
LOCK = threading.RLock()
CYR_WORD = re.compile(r"^[а-яё]+$", re.IGNORECASE)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_stem(value: str) -> str:
    value = Path(value).stem
    value = re.sub(r"[^A-Za-zА-Яа-яЁё0-9_-]+", "_", value).strip("_-")
    return (value or "Book")[:34]


def ensure_private(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def read_stress_entries(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            raise ValueError("Файл ударений содержит строку неверного формата.")
        word, marked = parts
        key = word.casefold()
        if not CYR_WORD.fullmatch(word) or marked.count("+") != 1 or marked.replace("+", "").casefold() != key:
            raise ValueError("Файл ударений содержит некорректную запись.")
        if key in result and result[key] != marked:
            raise ValueError("Файл ударений содержит конфликтующие варианты одного слова.")
        result[key] = marked
    return result


def _jar_contains(path: Path, entry: str) -> bool:
    """Check a JVM archive without extracting it into the runtime directory."""
    try:
        with zipfile.ZipFile(path) as archive:
            return entry in archive.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def _desktop_java_classpath(classes: Path, libs: Path) -> str:
    """Put the real org.json implementation before Android's mockable framework jar.

    The Android mockable jar also contains org.json classes whose methods return JVM
    defaults. A wildcard classpath makes class loading order unspecified and can make
    JSONObject.getJSONObject() return None during the desktop audit.
    """
    class_dir = Path(classes)
    lib_dir = Path(libs)
    jars = sorted(
        (path for path in lib_dir.glob("*.jar") if path.is_file()),
        key=lambda path: path.name.casefold(),
    )
    json_libraries = [
        path for path in jars
        if path.name.casefold().startswith("json-")
        and _jar_contains(path, "org/json/JSONObject.class")
    ]
    if not lib_dir.is_dir():
        # Unit tests may inject only a synthetic classpath without a materialized bundle.
        return os.pathsep.join((str(class_dir), str(lib_dir / "*")))
    if not json_libraries:
        raise FileNotFoundError(
            "Не найдена отдельная JVM-библиотека org.json; Android mockable-jar "
            "не может заменять реализацию JSON."
        )
    preferred_json = json_libraries[0]
    ordered_jars = [preferred_json] + [path for path in jars if path != preferred_json]
    return os.pathsep.join([str(class_dir), *(str(path) for path in ordered_jars)])


def _require_runtime() -> dict[str, Path]:
    # One PyInstaller worker handles both official Silero Lite inference and the
    # independent character model. Avoid shipping two copies of the very large Torch runtime.
    model_worker = ENGINE / "bridges" / "worker" / "RuVoiceModelWorker.exe"
    paths = {
        "java": ENGINE / "jre" / "bin" / "java.exe",
        "classes": ENGINE / "desktop-audit" / "classes",
        "libs": ENGINE / "desktop-audit" / "lib",
        "project": ENGINE / "project",
        "silero": ENGINE / "silero-models",
        "eyo": ENGINE / "eyo_safe.txt",
        "baseline_silero_json": ENGINE / "project" / "app" / "src" / "main" / "assets" / "silero" / "silero_ru.json",
        "torch_exe": model_worker,
        "torch_script": ENGINE / "bridges" / "torch_lite_bridge.py",
        "third_model": model_worker,
        "native": ENGINE / "ruaccent-native",
        "aot": ENGINE / "aot" / "data" / "Russian",
        "system_stress": ENGINE / "project" / "app" / "src" / "main" / "assets" / "dicts" / "stress" / "Системный.txt",
        "system_replace": ENGINE / "project" / "app" / "src" / "main" / "assets" / "dicts" / "replace" / "Системный.txt",
        "hard_e": ENGINE / "project" / "app" / "src" / "main" / "assets" / "hard_e.txt",
        "context_rules": ENGINE / "reference" / "book_context_acceptances.tsv",
        "reference_overrides": ENGINE / "reference" / "book_reviewed_overrides.txt",
        "reference_replacements": ENGINE / "reference" / "book_reviewed_replacements.txt",
        "audit_scripts": ENGINE / "audit-scripts",
    }
    for key in ("java", "eyo", "baseline_silero_json", "torch_exe", "torch_script", "third_model", "system_stress", "system_replace", "hard_e"):
        if not paths[key].is_file():
            raise FileNotFoundError(f"Не найден компонент локального движка RuVoice: {paths[key].name}")
    for key in ("classes", "libs", "project", "silero", "native", "aot"):
        if not paths[key].is_dir():
            raise FileNotFoundError(f"Не найдена папка локального движка RuVoice: {paths[key].name}")
    main_class = paths["classes"].joinpath(*JVM_ENTRYPOINT.split(".")).with_suffix(".class")
    if not main_class.is_file():
        raise FileNotFoundError("Не собран основной класс полного аудита оригинального RuVoice.")
    paired_test_class = paths["classes"] / "ru" / "kost" / "ruvoice" / "text" / "UploadedEpubPairedEvaluationTest.class"
    if not paired_test_class.is_file():
        raise FileNotFoundError("Не собран JUnit-класс полного прохода оригинального RuVoice.")

    jars = [path for path in paths["libs"].glob("*.jar") if path.is_file()]
    if not jars:
        raise FileNotFoundError("Не найдены JVM-зависимости локального RuVoice.")
    # Fail before a book is accepted unless the real JSON implementation is available.
    _desktop_java_classpath(paths["classes"], paths["libs"])
    bridge_class = paths["classes"] / "ru" / "kost" / "ruvoice" / "text" / "RuAccentBridgeKt.class"
    if not bridge_class.is_file() and not any(
        _jar_contains(jar, "ru/kost/ruvoice/text/RuAccentBridgeKt.class") for jar in jars
    ):
        raise FileNotFoundError("Не собран отдельный JVM-мост RUAccent.")
    required_jar_entries = {
        "org/junit/runner/JUnitCore.class": "Не включена библиотека JUnit для запуска полного аудита.",
        "org/json/JSONObject.class": "Не включена библиотека JSON для обмена между JVM-процессами.",
        "ai/onnxruntime/OrtEnvironment.class": "Не включён настольный ONNX Runtime для Windows.",
        "android/util/Log.class": "Не включены Android API-заглушки для JVM-движка.",
    }
    for entry, message in required_jar_entries.items():
        if not any(_jar_contains(jar, entry) for jar in jars):
            raise FileNotFoundError(message)

    for key in ("audit_scripts",):
        if not paths[key].is_dir():
            raise FileNotFoundError(f"Не найдена папка локального движка RuVoice: {paths[key].name}")
    for filename in ("full_book_ruvoice_quality.py", "package_ruvoice_import.py"):
        if not (paths["audit_scripts"] / filename).is_file():
            raise FileNotFoundError(f"Не найден модуль полного аудита: {filename}")
    for key in ("reference_overrides", "reference_replacements"):
        if not paths[key].is_file():
            raise FileNotFoundError(f"Не найден проверенный книжный ресурс: {paths[key].name}")
    project_assets = paths["project"] / "app" / "src" / "main" / "assets"
    project_inputs = (
        project_assets / "morph.bin",
        project_assets / "hard_e.txt",
        paths["project"] / "tools" / "data" / "ruvoice_stress_book_regressions.json",
        paths["project"] / "tools" / "data" / "ruaccent_yo_book_regressions.json",
    )
    for input_path in project_inputs:
        if not input_path.is_file():
            raise FileNotFoundError(f"Не найден ресурс production RuVoice: {input_path.name}")
    for model_name in ("accentor.ptl", "homo.ptl"):
        if not (paths["silero"] / model_name).is_file():
            raise FileNotFoundError(f"Не найдена официальная модель RuVoice: {model_name}")
    if os.name == "nt" and not (paths["native"] / "ruvoice_tokenizers.dll").is_file():
        raise FileNotFoundError("Не найдена Windows JNI-библиотека ruvoice_tokenizers.dll")
    return paths


def _java_failure_summary(log_text: str, *, max_chars: int = 6000) -> str:
    """Prefer the JUnit assertion that caused failure over the tail of its stack trace."""
    lines = log_text.splitlines()
    failure_indexes = [
        index for index, line in enumerate(lines)
        if "RUVOICE_AUDIT_FAILURE=" in line
    ]
    if failure_indexes:
        blocks: list[str] = []
        for index in failure_indexes[:5]:
            # The JUnit failure header contains the test name and assertion message.
            # Include a few following frames, but don't dump the complete book audit log.
            blocks.append("\n".join(lines[index:index + 5]))
        summary = "\n".join(blocks)
    else:
        summary = "\n".join(lines[-35:])
    return summary[-max_chars:]


def _run_java(paths: dict[str, Path], book: Path, report: Path, work: Path, private_home: Path,
              book_sha: str, replacements: Path, overrides: Path, auto_overrides: Path | None = None) -> None:
    env = os.environ.copy()
    project = paths["project"]
    torch_bridge_log = work / "torch-lite-bridge.log"
    torch_bridge_log.unlink(missing_ok=True)
    env.update({
        "RUVOICE_PROJECT_DIR": str(project),
        "RUVOICE_BOOK_PATH": str(book.resolve()),
        "RUVOICE_REPORT_PATH": str(report.resolve()),
        "RUVOICE_SILERO_ASSETS": str(paths["silero"]),
        "RUVOICE_OFFICIAL_EYO_ASSET": str(paths["eyo"]),
        "RUVOICE_BASELINE_SILERO_JSON": str(paths["baseline_silero_json"]),
        "RUVOICE_TORCH_BRIDGE": str(paths["torch_script"]),
        "RUVOICE_TORCH_BRIDGE_EXE": str(paths["torch_exe"]),
        "RUVOICE_TORCH_BRIDGE_LOG": str(torch_bridge_log),
        "RUVOICE_BOOK_OVERRIDES": str(overrides),
        "RUVOICE_BOOK_REPLACEMENTS": str(replacements),
        "RUVOICE_RUACCENT_MODEL_CACHE": str(private_home / "models" / "ruaccent"),
        "RUACCENT_NATIVE_DIR": str(paths["native"]),
    })
    env.pop("RUVOICE_AUTO_BOOK_OVERRIDES", None)
    if auto_overrides is not None:
        env["RUVOICE_AUTO_BOOK_OVERRIDES"] = str(auto_overrides)
    classpath = _desktop_java_classpath(paths["classes"], paths["libs"])
    env["RUACCENT_BRIDGE_CLASSPATH"] = classpath
    java = paths["java"]
    command = [
        str(java), "-Xmx4g", "-Dfile.encoding=UTF-8", "-Djava.library.path=" + str(paths["native"]),
        "-cp", classpath, JVM_ENTRYPOINT,
    ]
    log = work / ("second-pass.log" if auto_overrides is not None else "first-pass.log")
    with log.open("w", encoding="utf-8", errors="replace") as stream:
        completed = subprocess.run(
            command, cwd=project, env=env, stdout=stream, stderr=subprocess.STDOUT,
            text=True, check=False,
        )
    if completed.returncode != 0:
        failure_details = _java_failure_summary(log.read_text(encoding="utf-8", errors="replace"))
        if torch_bridge_log.is_file():
            bridge_details = torch_bridge_log.read_text(encoding="utf-8", errors="replace")[-12000:]
            if bridge_details:
                failure_details += "\n\nTORCH_LITE_BRIDGE_DIAGNOSTICS:\n" + bridge_details
        raise RuntimeError("Полный проход оригинального RuVoice завершился ошибкой.\n" + failure_details)
    if not report.is_file():
        raise RuntimeError("Оригинальный RuVoice не создал отчёт полного прохода.")
    paired = json.loads(report.read_text(encoding="utf-8"))
    report_sha = paired.get("book_sha256")
    if report_sha != book_sha:
        raise RuntimeError(
            "Отчёт RuVoice относится не к загруженной книге: "
            f"input_sha256={book_sha}, report_sha256={report_sha}, file={book.name}."
        )


def _run_quality_module(paths: dict[str, Path], work: Path, paired: Path, output: Path,
                       context_rules: Path | None = None) -> None:
    audit_scripts = ENGINE / "audit-scripts"
    if str(audit_scripts) not in sys.path:
        sys.path.insert(0, str(audit_scripts))
    import full_book_ruvoice_quality

    argv = [
        "full_book_ruvoice_quality.py",
        "--paired-json", str(paired),
        "--aot-dir", str(paths["aot"]),
        "--system-dictionary", str(paths["system_stress"]),
        "--output-dir", str(output),
    ]
    if context_rules is not None and context_rules.is_file():
        argv.extend(["--context-rules", str(context_rules)])
    old_argv = sys.argv
    try:
        sys.argv = argv
        result = full_book_ruvoice_quality.main()
    finally:
        sys.argv = old_argv
    if result != 0:
        raise RuntimeError("Контекстная проверка словоупотреблений завершилась ошибкой.")


def _run_third_model(paths: dict[str, Path], paired: Path, occurrences: Path, reviewed: Path, output: Path) -> None:
    command = [
        str(paths["third_model"]),
        "--third-model",
        "--paired-json", str(paired),
        "--quality-occurrences", str(occurrences),
        "--reviewed-overrides", str(reviewed),
        "--output-dir", str(output),
        "--batch-size", "8",
        "--max-chars", "220",
    ]
    completed = subprocess.run(command, cwd=ENGINE, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        message = "\n".join(completed.stdout.splitlines()[-15:] + completed.stderr.splitlines()[-15:])
        raise RuntimeError("Независимая проверка ударений завершилась ошибкой.\n" + message[-3000:])


def _merge_replacements(reference: Path, user: Path | None, is_reference: bool, target: Path) -> None:
    lines: list[str] = []
    if is_reference and reference.is_file():
        lines.extend(reference.read_text(encoding="utf-8-sig").splitlines())
    if user is not None:
        lines.extend(user.read_text(encoding="utf-8-sig").splitlines())
    keys: dict[str, str] = {}
    output: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not key.strip() or not value.strip():
            raise ValueError("Файл контекстных замен содержит строку неверного формата.")
        canonical = key.strip().casefold()
        if canonical in keys:
            if keys[canonical] != value.strip():
                raise ValueError("Конфликтующие контекстные замены. Исправьте файл и загрузите книгу снова.")
            continue
        keys[canonical] = value.strip()
        output.append(f"{key.strip()} = {value.strip()}")
    target.write_text("\n".join(output) + ("\n" if output else ""), encoding="utf-8")


def _update_private_history(private_home: Path, book_sha: str, book_name: str, archive: Path,
                            summary: dict[str, Any], stress_path: Path, replacements_path: Path) -> tuple[int, int, bool, Path]:
    state = private_home / "state"
    packages = private_home / "packages"
    lists = private_home / "Book_Dictionaries"
    for path in (state, packages, lists):
        ensure_private(path)
    history_file = state / "book_history.json"
    try:
        history = json.loads(history_file.read_text(encoding="utf-8")) if history_file.is_file() else {"schema_version": 1, "books": {}}
    except (ValueError, OSError):
        history = {"schema_version": 1, "books": {}}
    books = history.setdefault("books", {})
    previously_seen = book_sha in books
    stress_target = lists / f"{safe_stem(book_name)}_{book_sha[:8]}_Stress.txt"
    replace_target = lists / f"{safe_stem(book_name)}_{book_sha[:8]}_Replacements.txt"
    shutil.copyfile(stress_path, stress_target)
    shutil.copyfile(replacements_path, replace_target)
    books[book_sha] = {
        "book_name": book_name,
        "processed_utc": datetime.now(timezone.utc).isoformat(),
        "stress_entries": summary.get("total_imported_stress_overrides", 0),
        "replacement_rules": summary.get("imported_context_replacement_rules", 0),
        "archive": archive.name,
    }
    history_file.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    package_target = packages / archive.name
    if package_target.resolve() != archive.resolve():
        if package_target.is_file() and sha256_file(package_target) != sha256_file(archive):
            stem, suffix = package_target.stem, package_target.suffix
            version = 2
            while (packages / f"{stem}_v{version}{suffix}").exists():
                version += 1
            package_target = packages / f"{stem}_v{version}{suffix}"
        if not package_target.exists():
            shutil.copyfile(archive, package_target)
    cumulative = sum(int(row.get("stress_entries", 0)) for row in books.values())
    return (
        0 if previously_seen else int(summary.get("total_imported_stress_overrides", 0)),
        cumulative,
        previously_seen,
        package_target,
    )


def process_book(book: Path, *, private_home: Path, book_name: str | None = None,
                 replacements: Path | None = None) -> dict[str, Any]:
    book = Path(book).resolve()
    display_name = Path(book_name or book.name).name
    if not book.is_file() or book.suffix.lower() != ".epub":
        raise ValueError("Полный аудит произношения сейчас принимает EPUB.")
    paths = _require_runtime()
    digest = sha256_file(book)
    is_reference = digest == REFERENCE_SHA256
    private_home = Path(private_home).expanduser().resolve()
    ensure_private(private_home)
    work_parent = private_home / "work"
    ensure_private(work_parent)
    work = Path(tempfile.mkdtemp(prefix=digest[:12] + "-", dir=work_parent))
    try:
        manual_overrides = work / "manual_overrides.txt"
        if is_reference:
            shutil.copyfile(paths["reference_overrides"], manual_overrides)
        else:
            manual_overrides.write_text("# Для этой книги нет заранее заданных исправлений.\n", encoding="utf-8")
        book_replacements = work / "book_replacements.txt"
        _merge_replacements(paths["reference_replacements"], replacements, is_reference, book_replacements)

        paired = work / "paired.json"
        _run_java(paths, book, paired, work, private_home, digest, book_replacements, manual_overrides)

        first_quality = work / "first-quality"
        _run_quality_module(paths, work, paired, first_quality, paths["context_rules"] if is_reference else None)
        occurrences = first_quality / "WholeBook_RuVoice_AllOccurrences.tsv"
        if not occurrences.is_file():
            raise RuntimeError("Не создан полный реестр словоупотреблений первой проверки.")
        third = work / "third-model"
        _run_third_model(paths, paired, occurrences, manual_overrides, third)
        auto_overrides = third / "Book_Three_Model_Confirmed_Overrides.txt"
        if not auto_overrides.is_file():
            raise RuntimeError("Независимая модель не создала список подтверждённых кандидатов.")

        has_auto_stress = bool(read_stress_entries(auto_overrides))
        if has_auto_stress:
            # The first paired run already validates manual word/phrase overlays.
            # Only newly generated automatic rules require another full production pass.
            _run_java(paths, book, paired, work, private_home, digest, book_replacements, manual_overrides, auto_overrides)
            final_quality = work / "final-quality"
            _run_quality_module(paths, work, paired, final_quality, paths["context_rules"] if is_reference else None)
        else:
            # No new automatic correction was created. The reviewed stream in the first
            # paired run is already the final state; do not repeat identical neural inference.
            final_quality = first_quality
        final_replacements = final_quality / "Book_Importable_Replacements.txt"
        shutil.copyfile(book_replacements, final_replacements)

        summary_path = final_quality / "WholeBook_RuVoice_Quality_Summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary.get("ledger_coverage_percent") != 100.0:
            raise RuntimeError("Полный реестр не покрывает 100% словоупотреблений — ZIP не создан.")
        if summary.get("tokens_from_ruvoice") != summary.get("occurrences_in_quality_ledger"):
            raise RuntimeError("Число проверенных записей не совпадает с числом токенов RuVoice.")

        import package_ruvoice_import
        work_archive = work / f"{safe_stem(display_name)}_{digest[:8]}_RuVoice.zip"
        package_result = package_ruvoice_import.package(
            book_path=book, quality_dir=final_quality,
            replacements_path=final_replacements, output=work_archive,
        )
        new_count, cumulative_count, previously_seen, archive = _update_private_history(
            private_home, digest, display_name, work_archive,
            json.loads(summary_path.read_text(encoding="utf-8")),
            final_quality / "Book_Importable_Stress_Overrides.txt",
            final_replacements,
        )
        return {
            "archive": str(archive),
            "new_entry_count": package_result["stress_entries"],
            "cumulative_entry_count": cumulative_count,
            "already_processed": previously_seen,
            "book_sha256": digest,
            "ledger_coverage_percent": package_result["ledger_coverage_percent"],
            "replacement_rule_count": package_result["replacement_rules"],
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)
