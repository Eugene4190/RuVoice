#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import local_full_book_workflow as workflow
from local_full_book_workflow import _jar_contains, _java_failure_summary


class DesktopRuntimeJarValidationTests(unittest.TestCase):
    def test_junit_assertion_is_preserved_instead_of_only_the_end_of_stack_trace(self):
        log = "\n".join(
            ["RUVOICE_AUDIT_FAILURE=compareOriginal :: source/output alignment failed"] +
            [f"\tat test.Frame({index})" for index in range(50)]
        )
        summary = _java_failure_summary(log)
        self.assertIn("RUVOICE_AUDIT_FAILURE=compareOriginal :: source/output alignment failed", summary)
        self.assertIn("test.Frame(3)", summary)
        self.assertNotIn("test.Frame(49)", summary)

    def test_java_failure_summary_falls_back_to_last_lines_without_junit_marker(self):
        log = "\n".join(f"line-{index}" for index in range(50))
        summary = _java_failure_summary(log)
        self.assertIn("line-49", summary)
        self.assertIn("line-15", summary)
        self.assertNotIn("line-0", summary)

    def test_frozen_onefile_uses_side_by_side_engine_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = root / "_MEIPASS"
            executable = root / "dist"
            (executable / "engine").mkdir(parents=True)
            resolved = workflow.resolve_engine_root(
                root / "source",
                frozen=True,
                bundle_root=bundle,
                executable_dir=executable,
            )
            self.assertEqual(resolved, executable.resolve())

    def test_frozen_build_prefers_engine_embedded_in_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = root / "_MEIPASS"
            executable = root / "dist"
            (bundle / "engine").mkdir(parents=True)
            (executable / "engine").mkdir(parents=True)
            resolved = workflow.resolve_engine_root(
                root / "source",
                frozen=True,
                bundle_root=bundle,
                executable_dir=executable,
            )
            self.assertEqual(resolved, bundle.resolve())

    def test_source_checkout_keeps_repository_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            resolved = workflow.resolve_engine_root(
                root,
                frozen=False,
                bundle_root=None,
                executable_dir=root / "bin",
            )
            self.assertEqual(resolved, root.resolve())

    def test_local_runner_invokes_the_junit_wrapping_desktop_main(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            book = root / "book.epub"
            book.write_bytes(b"epub-stub")
            work = root / "work"
            work.mkdir()
            report = root / "paired.json"
            paths = {
                "java": root / "java.exe",
                "project": root / "project",
                "classes": root / "classes",
                "libs": root / "lib",
                "silero": root / "silero",
                "eyo": root / "eyo_safe.txt",
                "baseline_silero_json": root / "silero_ru.json",
                "torch_script": root / "torch_lite_bridge.py",
                "torch_exe": root / "RuVoiceTorchBridge.exe",
                "native": root / "native",
            }

            def run_junit(command, **kwargs):
                report.write_text('{"book_sha256":"expected-book-sha"}', encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            with patch.object(workflow.subprocess, "run", side_effect=run_junit) as run:
                workflow._run_java(
                    paths, book, report, work, root / "private-home",
                    "expected-book-sha", root / "replacements.txt", root / "overrides.txt",
                )

            command = run.call_args.args[0]
            self.assertEqual(command[-1], workflow.JVM_ENTRYPOINT)
            self.assertEqual(
                workflow.JVM_ENTRYPOINT,
                "ru.kost.ruvoice.text.UploadedEpubPairedEvaluationMain",
            )
            env = run.call_args.kwargs["env"]
            self.assertEqual(
                env["RUVOICE_TORCH_BRIDGE_LOG"],
                str(work / "torch-lite-bridge.log"),
            )

    def test_worker_diagnostics_are_appended_when_the_original_ruvoice_pass_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            book = root / "book.epub"
            book.write_bytes(b"epub-stub")
            work = root / "work"
            work.mkdir()
            report = root / "paired.json"
            paths = {
                "java": root / "java.exe",
                "project": root / "project",
                "classes": root / "classes",
                "libs": root / "lib",
                "silero": root / "silero",
                "eyo": root / "eyo_safe.txt",
                "baseline_silero_json": root / "silero_ru.json",
                "torch_script": root / "torch_lite_bridge.py",
                "torch_exe": root / "RuVoiceModelWorker.exe",
                "native": root / "native",
            }

            def fail_after_worker_log(command, **kwargs):
                env = kwargs["env"]
                Path(env["RUVOICE_TORCH_BRIDGE_LOG"]).write_text(
                    "TORCH_BRIDGE_DIAGNOSTIC=REQUEST_BEGIN line=1 op=accentor words=2\\n"
                    "TORCH_BRIDGE_DIAGNOSTIC=REQUEST_ERROR line=1 RuntimeError: invalid input\\n",
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="")

            with patch.object(workflow.subprocess, "run", side_effect=fail_after_worker_log):
                with self.assertRaises(RuntimeError) as raised:
                    workflow._run_java(
                        paths, book, report, work, root / "private-home",
                        "expected-book-sha", root / "replacements.txt", root / "overrides.txt",
                    )
            self.assertIn("TORCH_LITE_BRIDGE_DIAGNOSTICS", str(raised.exception))
            self.assertIn("REQUEST_ERROR", str(raised.exception))
            self.assertIn("invalid input", str(raised.exception))

    def test_third_model_worker_receives_mode_flag(self):
        completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        paths = {"third_model": Path("worker.exe")}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paired = root / "paired.json"
            occurrences = root / "occurrences.tsv"
            overrides = root / "reviewed.txt"
            output = root / "third"
            with patch.object(workflow.subprocess, "run", return_value=completed) as run:
                workflow._run_third_model(paths, paired, occurrences, overrides, output)
            command = run.call_args.args[0]
            self.assertEqual(command[0], "worker.exe")
            self.assertEqual(command[1], "--third-model")
            self.assertIn("--paired-json", command)
            self.assertIn("--quality-occurrences", command)

    def test_desktop_classpath_prioritizes_real_json_over_android_mockable_jar(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            classes = root / "classes"
            libs = root / "lib"
            libs.mkdir()
            json_jar = libs / "json-20240303.jar"
            android_jar = libs / "mockable-android-35.jar"
            with zipfile.ZipFile(json_jar, "w") as archive:
                archive.writestr("org/json/JSONObject.class", b"real-json")
            with zipfile.ZipFile(android_jar, "w") as archive:
                archive.writestr("org/json/JSONObject.class", b"mockable-json")
                archive.writestr("android/util/Log.class", b"android-log")

            classpath = workflow._desktop_java_classpath(classes, libs)
            entries = classpath.split(workflow.os.pathsep)
            self.assertEqual(entries[0], str(classes))
            self.assertEqual(entries[1], str(json_jar))
            self.assertLess(entries.index(str(json_jar)), entries.index(str(android_jar)))

    def test_desktop_classpath_rejects_android_json_without_real_json_library(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            classes = root / "classes"
            libs = root / "lib"
            libs.mkdir()
            with zipfile.ZipFile(libs / "mockable-android-35.jar", "w") as archive:
                archive.writestr("org/json/JSONObject.class", b"mockable-json")
                archive.writestr("android/util/Log.class", b"android-log")
            with self.assertRaises(FileNotFoundError):
                workflow._desktop_java_classpath(classes, libs)

    def test_detects_expected_class_inside_runtime_jar(self):
        with tempfile.TemporaryDirectory() as temp:
            jar = Path(temp) / "runtime.jar"
            with zipfile.ZipFile(jar, "w") as archive:
                archive.writestr("ru/kost/ruvoice/text/RuAccentBridgeKt.class", b"stub")
            self.assertTrue(_jar_contains(jar, "ru/kost/ruvoice/text/RuAccentBridgeKt.class"))
            self.assertFalse(_jar_contains(jar, "org/junit/runner/JUnitCore.class"))

    def test_rejects_a_non_jar_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "not-a-jar.jar"
            path.write_text("not a zip", encoding="utf-8")
            self.assertFalse(_jar_contains(path, "anything.class"))


if __name__ == "__main__":
    unittest.main()
