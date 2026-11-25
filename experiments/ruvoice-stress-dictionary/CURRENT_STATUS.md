# Текущий статус личного workflow RuVoice

Дата проверки: 2026-11-25.
Рабочая ветка: `stress-dictionary-pipeline`.

## Уже реализовано

- Локальная browser-страница `private_book_server.py`, привязанная к `127.0.0.1`; загрузка EPUB/TXT/HTML до 256 МБ и необязательного TXT с книжными replacements.
- Проверки Host/Origin и одноразового токена формы; HTTP access-log отключён.
- Входные EPUB и TXT временные, удаляются до выдачи ссылки на ZIP.
- Append-only мастер и история provenance хранятся вне Git: `~/.ruvoice-book-workflow` (Windows: `%USERPROFILE%\\.ruvoice-book-workflow`); локальная папка не зашифрована.
- SHA-256 обеспечивает идемпотентность повторной книги. Конфликтующие новые ударения не перезаписывают утверждённые записи.
- ZIP содержит дельту этой книги, полный cumulative snapshot, историю, отдельные per-book replacements, Import guide и review-отчёты.
- Кандидаты добавляются только после разрешённых source/context/spelling/conflict checks.
- OPF spine reading order поддержан; есть fallback для минимальных EPUB.
- Публичный корневой `.gitignore` блокирует новые файлы книг и локальные данные пользователя.

## Windows portable build — в разработке

- Добавлен resolver путей для исходного checkout и PyInstaller one-file bundle: ресурсы читаются из `sys._MEIPASS` внутри EXE.
- Добавлены unit tests на source/bundle path resolution.
- Windows launcher теперь сначала запускает `RuVoiceBookTool.exe`, если он лежит рядом; иначе пытается использовать установленный Python 3.11+.
- Workflow `Build RuVoice Book Tool for Windows` собирает one-file EXE, проверяет запуск локальной страницы и публикует ZIP `RuVoiceBookTool-Windows-x64` как Actions artifact.
- Windows workflow и обновлённый Python compile list ещё проходят CI. Пока smoke test не прошёл, ZIP не объявляется доступным/готовым.

## Последние подтверждённые тесты до Windows packaging

- Dictionary tools [run 45678874104](https://github.com/Eugene4190/RuVoice/actions/runs/45678874104) — success.
- На коде до portable-build обе проверки прошли: 61 основной Python unit test + 26 private paired-evaluation tests; Kotlin Full/Lite — success.
- Новые тесты пути и Windows EXE проверяются отдельными CI jobs.

## Что осталось до пользовательской приёмки

1. Успешно собрать Windows portable ZIP и пройти smoke test на чистом Windows runner.
2. Скачать ZIP, распаковать и запустить BAT двойным щелчком.
3. Обработать настоящую EPUB и проверить дельту, полный snapshot, replacements и отчёты.
4. Проверить качество ударений на этой книге, особенно неизвестные формы и омографы.
5. Расширить безопасное предложение новых контекстных replacements; текущий автоматический выбор ограничен curated-фразами, пользовательский TXT поддержан.
6. Импортировать дельту и replacements в RuVoice на телефоне.
7. Проверить чтение той же EPUB с одновременной озвучкой.
8. Повторить цикл на второй книге, проверив сохранение первой.

## Приватность и границы

- Репозиторий публичный; старый тестовый `private-files/8.Iskusstvo..epub` и часть review-материалов доступны через GitHub.
- Новые пользовательские книги через локальную страницу не отправляются в GitHub.
- Локальный мастер, ZIP и review data не зашифрованы.
- Пользовательские книги и их контент не добавлять в Git, Issues, PR и Actions artifacts/logs.
- `main`, production `Системный.txt`, глобальные replacements и APK assets не менялись.

## Состояние репозитория

- `main` не изменён.
- PR [#1](https://github.com/Eugene4190/RuVoice/pull/1) остаётся Draft, не слит.
