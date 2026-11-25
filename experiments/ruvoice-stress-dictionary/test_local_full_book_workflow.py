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
