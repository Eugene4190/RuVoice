import contextlib
import http.client
import io
import os
import re
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import private_book_server
from private_book_server import Server, Handler, page, parse_multipart, validate_setup


class PrivateUploadFormTests(unittest.TestCase):
    def test_multipart_parser_reads_token_book_and_optional_replacements(self):
        boundary = "ruvoice-test-boundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="token"\r\n\r\n'
            "secret-token\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="book"; filename="my-book.epub"\r\n'
            "Content-Type: application/epub+zip\r\n\r\n"
        ).encode() + b"fake-epub-bytes" + f"\r\n--{boundary}\r\n".encode() + (
            'Content-Disposition: form-data; name="replacements"; filename="rules.txt"\r\n'
            "Content-Type: text/plain\r\n\r\n"
        ).encode() + b"word = w+ord" + f"\r\n--{boundary}--\r\n".encode()
        fields = parse_multipart(f"multipart/form-data; boundary={boundary}", body)
        self.assertEqual(fields["token"], (None, b"secret-token"))
        self.assertEqual(fields["book"], ("my-book.epub", b"fake-epub-bytes"))
        self.assertEqual(fields["replacements"], ("rules.txt", b"word = w+ord"))

    def test_startup_preflight_checks_required_files_and_private_writability(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            required = root / "pipeline.txt"
            required.write_text("ready", encoding="utf-8")
            private = root / "private"
            result = validate_setup(private, required_paths=[required])
            self.assertEqual(result, private.resolve())
            self.assertTrue(private.is_dir())
            self.assertFalse(list(private.glob(".ruvoice-write-check-*")))
            if os.name == "posix":
                self.assertEqual(private.stat().st_mode & 0o777, 0o700)
            with self.assertRaises(FileNotFoundError):
                validate_setup(root / "bad-private", required_paths=[root / "missing.txt"])

    def test_startup_error_is_reported_and_returns_nonzero(self):
        stderr = io.StringIO()
        with (
            patch("private_book_server.validate_setup", side_effect=FileNotFoundError("pipeline missing")),
            patch("sys.argv", ["private_book_server.py", "--no-browser"]),
            contextlib.redirect_stderr(stderr),
        ):
            result = private_book_server.main()
        self.assertEqual(result, 1)
        self.assertIn("Не удалось запустить инструмент", stderr.getvalue())

    def test_page_escapes_token_and_shows_download_link(self):
        rendered = page('"><script>alert(1)</script>', "ZIP готов", "/download/key").decode()
        self.assertNotIn('value=""><script>', rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn('href="/download/key"', rendered)

    def test_invalid_epub_returns_clear_error_and_removes_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "private"
            server = Server(("127.0.0.1", 0), home)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
                conn.request("GET", "/")
                response = conn.getresponse()
                html_page = response.read().decode("utf-8")
                token = re.search(r'name="token" value="([^"]+)"', html_page).group(1)
                boundary = "ruvoice-invalid-epub"
                body = (
                    f"--{boundary}\r\n"
                    'Content-Disposition: form-data; name="token"\r\n\r\n'
                    f"{token}\r\n"
                    f"--{boundary}\r\n"
                    'Content-Disposition: form-data; name="book"; filename="broken.epub"\r\n'
                    "Content-Type: application/epub+zip\r\n\r\n"
                ).encode() + b"not-a-valid-zip" + f"\r\n--{boundary}--\r\n".encode()
                with patch(
                    "private_book_server.process_book",
                    side_effect=zipfile.BadZipFile("Invalid EPUB archive"),
                ):
                    conn.request(
                        "POST", "/upload", body=body,
                        headers={
                            "Content-Type": f"multipart/form-data; boundary={boundary}",
                            "Origin": f"http://127.0.0.1:{server.server_port}",
                        },
                    )
                    response = conn.getresponse()
                    error_page = response.read().decode("utf-8")
                self.assertEqual(response.status, 400)
                self.assertIn("Invalid EPUB archive", error_page)
                self.assertEqual(list((home / "incoming").glob("upload-*")), [])
                conn.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_local_http_upload_returns_zip_and_deletes_temporary_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "private"
            server = Server(("127.0.0.1", 0), home)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            seen = {}
            try:
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
                conn.request("GET", "/")
                response = conn.getresponse()
                html_page = response.read().decode("utf-8")
                self.assertEqual(response.status, 200)
                token_match = re.search(r'name="token" value="([^"]+)"', html_page)
                self.assertIsNotNone(token_match)
                token = token_match.group(1)

                def fake_process(upload, *, private_home, book_name, replacements=None):
                    seen["upload"] = Path(upload)
                    seen["replacement"] = Path(replacements) if replacements else None
                    seen["book_name"] = book_name
                    self.assertEqual(Path(upload).read_bytes(), b"synthetic-epub")
                    self.assertEqual(Path(replacements).read_bytes(), b"synthetic-rules")
                    package_dir = Path(private_home) / "packages"
                    package_dir.mkdir(parents=True, exist_ok=True)
                    archive_path = package_dir / "result.zip"
                    with zipfile.ZipFile(archive_path, "w") as archive:
                        archive.writestr("IMPORT.txt", "test")
                    return {
                        "archive": str(archive_path),
                        "new_entry_count": 2,
                        "cumulative_entry_count": 7,
                        "ledger_coverage_percent": 100.0,
                        "replacement_rule_count": 3,
                        "already_processed": False,
                    }

                boundary = "ruvoice-local-http-test"
                body = (
                    f"--{boundary}\r\n"
                    'Content-Disposition: form-data; name="token"\r\n\r\n'
                    f"{token}\r\n"
                    f"--{boundary}\r\n"
                    'Content-Disposition: form-data; name="book"; filename="A.epub"\r\n'
                    "Content-Type: application/epub+zip\r\n\r\n"
                ).encode() + b"synthetic-epub" + f"\r\n--{boundary}\r\n".encode() + (
                    'Content-Disposition: form-data; name="replacements"; filename="A_rules.txt"\r\n'
                    "Content-Type: text/plain\r\n\r\n"
                ).encode() + b"synthetic-rules" + f"\r\n--{boundary}--\r\n".encode()

                with patch("private_book_server.process_book", side_effect=fake_process):
                    conn.request(
                        "POST", "/upload", body=body,
                        headers={
                            "Content-Type": f"multipart/form-data; boundary={boundary}",
                            "Origin": f"http://127.0.0.1:{server.server_port}",
                        },
                    )
                    response = conn.getresponse()
                    result_page = response.read().decode("utf-8")
                self.assertEqual(response.status, 200)
                self.assertIn("ZIP готов", result_page)
                self.assertIn("слов для ударения: 2", result_page)
                self.assertIn("контекстных правил: 3", result_page)
                self.assertEqual(seen["book_name"], "A.epub")
                self.assertFalse(seen["upload"].exists())
                self.assertFalse(seen["replacement"].exists())
                link = re.search(r'href="(/download/[^"]+)"', result_page)
                self.assertIsNotNone(link)

                conn.request("GET", link.group(1))
                downloaded = conn.getresponse()
                payload = downloaded.read()
                self.assertEqual(downloaded.status, 200)
                self.assertEqual(downloaded.getheader("Content-Type"), "application/zip")
                with zipfile.ZipFile(__import__("io").BytesIO(payload)) as archive:
                    self.assertIn("IMPORT.txt", archive.namelist())
                conn.close()

                if hasattr(home, "stat"):
                    self.assertEqual(home.stat().st_mode & 0o777, 0o700)
                    self.assertEqual((home / "incoming").stat().st_mode & 0o777, 0o700)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
