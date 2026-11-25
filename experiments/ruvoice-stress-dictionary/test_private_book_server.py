import unittest

from private_book_server import page, parse_multipart


class PrivateUploadFormTests(unittest.TestCase):
    def test_multipart_parser_reads_token_and_book(self):
        boundary = "ruvoice-test-boundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="token"\r\n\r\n'
            "secret-token\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="book"; filename="my-book.epub"\r\n'
            "Content-Type: application/epub+zip\r\n\r\n"
        ).encode() + b"fake-epub-bytes" + f"\r\n--{boundary}--\r\n".encode()
        fields = parse_multipart(f"multipart/form-data; boundary={boundary}", body)
        self.assertEqual(fields["token"], (None, b"secret-token"))
        self.assertEqual(fields["book"], ("my-book.epub", b"fake-epub-bytes"))

    def test_page_escapes_token_and_shows_download_link(self):
        rendered = page('"><script>alert(1)</script>', "ZIP готов", "/download/key").decode()
        self.assertNotIn('value=""><script>', rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn('href="/download/key"', rendered)


if __name__ == "__main__":
    unittest.main()
