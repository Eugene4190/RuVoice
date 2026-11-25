#!/usr/bin/env python3
"""Loopback-only private EPUB upload page; no cloud upload or book text logging."""
from __future__ import annotations
import argparse, html, os, secrets, sys, tempfile, zipfile
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
import build_book_dictionary
from personal_book_workflow import DEFAULT_PRIVATE_HOME, process_book

MAX_BYTES = 256 * 1024 * 1024
ALLOWED = {".epub", ".txt", ".html", ".htm"}


def validate_setup(private_home: Path, required_paths=None) -> Path:
    required = required_paths or (
        build_book_dictionary.DEFAULT_SYSTEM,
        build_book_dictionary.DEFAULT_POOL,
        build_book_dictionary.DEFAULT_AUDIT,
        build_book_dictionary.DEFAULT_RULES,
    )
    missing = [str(path) for path in required if not Path(path).is_file()]
    if missing:
        raise FileNotFoundError(
            "Не найдены файлы словарного pipeline. Запустите инструмент из полного checkout "
            "репозитория RuVoice. Отсутствуют: " + ", ".join(missing)
        )
    private_home = private_home.expanduser().resolve()
    private_home.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(private_home, 0o700)
    except OSError:
        pass
    try:
        fd, probe = tempfile.mkstemp(prefix=".ruvoice-write-check-", dir=private_home)
        os.close(fd)
        Path(probe).unlink(missing_ok=True)
    except OSError as exc:
        raise PermissionError(
            f"Нет прав на запись в приватную папку {private_home}: {exc}"
        ) from exc
    return private_home

def parse_multipart(content_type: str, body: bytes):
    envelope = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
    msg = BytesParser(policy=policy.default).parsebytes(envelope)
    if not msg.is_multipart():
        raise ValueError("Неверный формат загрузки")
    result = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if name:
            result[name] = (part.get_filename(), part.get_payload(decode=True) or b"")
    return result

def page(token, message="", download_href=None):
    feedback = f"<p>{html.escape(message)}</p>" if message else ""
    if download_href:
        feedback += f'<p><a href="{html.escape(download_href, quote=True)}">Скачать ZIP для RuVoice</a></p>'
    return f"""<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RuVoice — книга</title><style>body{{font:16px system-ui;max-width:700px;margin:8vh auto;padding:0 20px;line-height:1.55}}main{{border:1px solid #8888;border-radius:16px;padding:26px}}input,button{{font:inherit;margin:14px 0}}input[type=file]{{display:block;width:100%;padding:14px;box-sizing:border-box}}button{{padding:12px 20px}}.notice{{background:#8882;padding:12px;border-radius:10px}}</style>
<main><h1>Дополнение словаря RuVoice</h1><p>Выберите EPUB. Книга обрабатывается локально; накопитель сохраняется в приватной папке этого компьютера.</p>
<form method="post" action="/upload" enctype="multipart/form-data"><input type="hidden" name="token" value="{html.escape(token)}"><label>Книга (EPUB, TXT или HTML; до 256 МБ)</label><input type="file" name="book" accept=".epub,.txt,.html,.htm" required><label>Книжные контекстные замены (необязательно, TXT)</label><input type="file" name="replacements" accept=".txt"><button type="submit">Собрать ZIP</button></form>
{feedback}<p class="notice"><b>Приватность:</b> сервер доступен только на 127.0.0.1. Книга не отправляется в GitHub и удаляется после сборки. Текст книги не включается в ZIP.</p></main></html>""".encode("utf-8")

class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, home):
        super().__init__(address, Handler)
        self.home, self.token, self.downloads = home, secrets.token_urlsafe(32), {}

class Handler(BaseHTTPRequestHandler):
    server: Server
    def log_message(self, fmt, *args):
        return
    def local_host(self):
        return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
    def send_page(self, status, message="", download_href=None):
        data = page(self.server.token, message, download_href)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        if not self.local_host():
            return self.send_page(403, "Доступ разрешён только с этого компьютера.")
        path = urlparse(self.path).path
        if path == "/":
            return self.send_page(200)
        if path.startswith("/download/"):
            archive = self.server.downloads.get(unquote(path.split("/")[-1]))
            if not archive or not archive.is_file():
                return self.send_page(404, "Ссылка не найдена. Обработайте книгу снова.")
            data = archive.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f'attachment; filename="{archive.name}"')
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_page(404, "Страница не найдена.")
    def do_POST(self):
        if not self.local_host() or urlparse(self.path).path != "/upload":
            return self.send_page(403, "Доступ разрешён только с этого компьютера.")
        origin = self.headers.get("Origin")
        allowed_origins = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
        if origin and origin not in allowed_origins:
            return self.send_page(403, "Запрос с внешнего сайта отклонён.")
        upload = None
        replacement_upload = None
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > MAX_BYTES:
                raise ValueError("Размер файла должен быть не более 256 МБ.")
            ctype = self.headers.get("Content-Type", "")
            if not ctype.lower().startswith("multipart/form-data;"):
                raise ValueError("Неверный формат формы.")
            fields = parse_multipart(ctype, self.rfile.read(size))
            token = fields.get("token", (None, b""))[1].decode("utf-8", "replace")
            if not secrets.compare_digest(token, self.server.token):
                raise ValueError("Форма устарела. Обновите страницу.")
            filename, data = fields.get("book", (None, b""))
            suffix = Path(filename or "").suffix.lower()
            if not filename or not data or suffix not in ALLOWED:
                raise ValueError("Выберите EPUB, TXT или HTML.")
            private_home = self.server.home.expanduser().resolve()
            private_home.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                os.chmod(private_home, 0o700)
            except OSError:
                pass
            incoming = private_home / "incoming"
            incoming.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                os.chmod(incoming, 0o700)
            except OSError:
                pass
            fd, name = tempfile.mkstemp(prefix="upload-", suffix=suffix, dir=incoming)
            os.close(fd)
            upload = Path(name)
            upload.write_bytes(data)
            replacement_name, replacement_data = fields.get("replacements", (None, b""))
            if replacement_name and replacement_data:
                if Path(replacement_name).suffix.lower() != ".txt":
                    raise ValueError("Файл контекстных замен должен быть TXT.")
                fd, replacement_temp = tempfile.mkstemp(prefix="replacements-", suffix=".txt", dir=incoming)
                os.close(fd)
                replacement_upload = Path(replacement_temp)
                replacement_upload.write_bytes(replacement_data)
            result = process_book(
                upload, private_home=self.server.home, book_name=Path(filename).name,
                replacements=replacement_upload,
            )
            # Remove incoming files before sending the success response: once
            # the browser sees the download link, no temporary book data remains.
            upload.unlink(missing_ok=True)
            upload = None
            if replacement_upload is not None:
                replacement_upload.unlink(missing_ok=True)
                replacement_upload = None
            key = secrets.token_urlsafe(24)
            self.server.downloads[key] = Path(result["archive"])
            note = f"ZIP готов. Новых записей: {result['new_entry_count']}; всего в личном накопителе: {result['cumulative_entry_count']}."
            if result["already_processed"]:
                note += " (повторная книга, дубликаты не добавлены)"
            self.send_page(200, note, download_href=f"/download/{key}")
        except (ValueError, OSError, RuntimeError, KeyError, zipfile.BadZipFile, EOFError) as exc:
            self.send_page(400, str(exc))
        finally:
            if upload is not None:
                upload.unlink(missing_ok=True)
            if replacement_upload is not None:
                replacement_upload.unlink(missing_ok=True)

def main():
    parser = argparse.ArgumentParser(description="Локальная приватная страница загрузки книг RuVoice")
    parser.add_argument("--private-home", type=Path, default=DEFAULT_PRIVATE_HOME)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("порт должен быть от 1024 до 65535")
    try:
        home = validate_setup(args.private_home)
    except (OSError, FileNotFoundError, PermissionError) as exc:
        print(f"Не удалось запустить инструмент: {exc}", file=sys.stderr)
        return 1
    server = Server(("127.0.0.1", args.port), home)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Откройте {url}. Сервер доступен только на этом компьютере; Ctrl+C — остановить.")
    print(f"Приватная папка словаря и ZIP: {home}")
    if not args.no_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == "__main__":
    raise SystemExit(main())
