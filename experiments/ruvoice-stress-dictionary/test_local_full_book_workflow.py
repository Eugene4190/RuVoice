#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import local_full_book_workflow as workflow
from local_full_book_workflow import _jar_contains


class DesktopRuntimeJarValidationTests(unittest.TestCase):
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
