#!/usr/bin/env python3
from __future__ import annotations

import io
import os
import sys
import unittest
from unittest.mock import patch

from portable_stdio import configure_utf8_stdio


class PortableStdioTests(unittest.TestCase):
    def test_windows_legacy_streams_are_reconfigured_for_unicode(self):
        input_bytes = "книга\n".encode("utf-8")
        stdin_buffer = io.BytesIO(input_bytes)
        stdout_buffer = io.BytesIO()
        stderr_buffer = io.BytesIO()
        streams = {
            "stdin": io.TextIOWrapper(stdin_buffer, encoding="cp1252"),
            "stdout": io.TextIOWrapper(stdout_buffer, encoding="cp1252"),
            "stderr": io.TextIOWrapper(stderr_buffer, encoding="cp1252"),
        }
        old_pythonutf8 = os.environ.get("PYTHONUTF8")
        old_pythonioencoding = os.environ.get("PYTHONIOENCODING")
        try:
            with (
                patch.object(sys, "stdin", streams["stdin"]),
                patch.object(sys, "stdout", streams["stdout"]),
                patch.object(sys, "stderr", streams["stderr"]),
            ):
                configure_utf8_stdio()
                self.assertEqual(sys.stdin.encoding.lower().replace("_", "-"), "utf-8")
                self.assertEqual(sys.stdin.readline(), "книга\n")
                self.assertEqual(sys.stdout.encoding.lower().replace("_", "-"), "utf-8")
                self.assertEqual(sys.stderr.encoding.lower().replace("_", "-"), "utf-8")
                sys.stdout.write("📖 Проверка ударения\n")
                sys.stdout.flush()
                sys.stderr.write("Ошибка: ёж 🦔\n")
                sys.stderr.flush()

            self.assertEqual(stdout_buffer.getvalue().decode("utf-8"), "📖 Проверка ударения\n")
            self.assertEqual(stderr_buffer.getvalue().decode("utf-8"), "Ошибка: ёж 🦔\n")
            self.assertEqual(os.environ["PYTHONUTF8"], "1")
            self.assertEqual(os.environ["PYTHONIOENCODING"], "utf-8")
        finally:
            for stream in streams.values():
                stream.close()
            if old_pythonutf8 is None:
                os.environ.pop("PYTHONUTF8", None)
            else:
                os.environ["PYTHONUTF8"] = old_pythonutf8
            if old_pythonioencoding is None:
                os.environ.pop("PYTHONIOENCODING", None)
            else:
                os.environ["PYTHONIOENCODING"] = old_pythonioencoding


if __name__ == "__main__":
    unittest.main()
