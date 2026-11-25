#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from local_full_book_workflow import _jar_contains


class DesktopRuntimeJarValidationTests(unittest.TestCase):
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
