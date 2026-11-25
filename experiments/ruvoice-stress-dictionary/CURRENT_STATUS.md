# Текущий статус личного workflow RuVoice

Дата проверки: 2026-11-25.
Рабочая ветка: `stress-dictionary-pipeline`.
Код и Windows portable build: `501cc1e8957cac0a078ead1a5397b58144358850`.

## Уже реализовано

- Локальная browser-страница `private_book_server.py`, привязанная к `127.0.0.1`; загрузка EPUB/TXT/HTML до 256 МБ и необязательного TXT с книжными replacements.
- Проверки Host/Origin и одноразового токена формы; HTTP access-log отключён.
- Входные EPUB и TXT временные, удаляются до выдачи ссылки на ZIP.
- Append-only мастер и история provenance хранятся вне Git: `%USERPROFILE%\\.ruvoice-book-workflow` на Windows (по умолчанию). Локальная папка не зашифрована.
- SHA-256 обеспечивает идемпотентность повторной книги. Конфликтующие новые ударения не перезаписывают утверждённые записи.
- ZIP содержит дельту этой книги, полный cumulative snapshot, историю, отдельные per-book replacements, Import guide и review-отчёты.
- Кандидаты добавляются только после разрешённых source/context/spelling/conflict checks.
- OPF spine reading order поддержан; есть fallback для минимальных EPUB.
- Публичный корневой `.gitignore` блокирует новые файлы EPUB/MOBI/FB2 и локальные данные пользователя.

## Windows portable build — готов

- One-file EXE собран с PyInstaller; отдельная установка Python пользователю не нужна.
- Launcher `Start_RuVoice_Book_Tool_Windows.bat` запускает EXE и открывает локальную страницу в браузере.
- [Windows build run 45684945444](https://github.com/Eugene4190/RuVoice/actions/runs/45684945444) — **success**. На чистом Windows runner прошёл сквозной smoke-test: EXE стартует, отдаёт страницу, принимает synthetic EPUB, выполняет обработку, скачивает ZIP, проверяет обязательные файлы пакета и создаёт приватный append-only master. Временная загруженная EPUB удаляется.
- Артефакт: `RuVoiceBookTool-Windows-x64`, 9,729,033 bytes, retention 30 дней. Его можно скачать на странице run выше, в секции Artifacts.
- Архив содержит `RuVoiceBookTool.exe`, BAT launcher и `START_HERE.txt`.

## Автоматические проверки

На версии кода `501cc1e8957cac0a078ead1a5397b58144358850`:

- [Dictionary tools run 45684945447](https://github.com/Eugene4190/RuVoice/actions/runs/45684945447) — **success**, включая новые тесты resolver путей для source checkout/frozen bundle.
- [Windows portable build run 45684945444](https://github.com/Eugene4190/RuVoice/actions/runs/45684945444) — **success**, в том числе сквозной synthetic EPUB → ZIP smoke-test.
- [Kotlin Full/Lite run 45684945387](https://github.com/Eugene4190/RuVoice/actions/runs/45684945387) — выполняется на момент записи; это JVM-тесты, а не APK build.
- Тесты A → B → повтор B, конфликтной защиты, восстановления транзакции, OPF spine, per-book replacements, ZIP и localhost upload/download проходят на синтетических данных.

Автоматические тесты не заменяют запуск настоящей пользовательской EPUB и ручной импорт/прослушивание на телефоне.

## Что осталось до пользовательской приёмки

1. Скачать Windows ZIP, распаковать и запустить BAT двойным щелчком.
2. Обработать настоящую EPUB и проверить ZIP, отчёты, количество новых записей и локальную папку.
3. Проверить качество ударений на этой книге, особенно неизвестные формы и омографы.
4. Расширить автоматическое безопасное предложение новых контекстных replacements. Сейчас автоматически выбираются только ограниченные curated-фразы; пользовательский TXT поддержан.
5. Импортировать дельту и replacements в RuVoice на телефоне.
6. Открыть ту же EPUB в RuVoice и проверить порядок текста и одновременную озвучку.
7. Повторить реальный цикл на второй книге, проверив сохранение первого списка.

## Приватность и границы

- Репозиторий публичный; старый тестовый `private-files/8.Iskusstvo..epub` и часть review-материалов доступны через GitHub.
- Новые пользовательские книги через локальную страницу не отправляются в GitHub.
- Локальный мастер, ZIP и review data не зашифрованы.
- Пользовательские книги и их контент не добавлять в Git, Issues, PR, Actions artifacts или логи.
- `main`, production `Системный.txt`, глобальные replacements и APK assets не менялись.

## Состояние репозитория

- `main` не изменён.
- PR [#1](https://github.com/Eugene4190/RuVoice/pull/1) остаётся Draft, не слит.
