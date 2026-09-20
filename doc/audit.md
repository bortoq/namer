# Audit: namer/books (переименование книг fb2/fb2.zip/epub/pdf/djvu)

- Дата перепроверки: 2026-09-20. Область: только новые файлы `namer/books/*.py` + `tests/test_books_*.py`.
- Трекаемые `M`-изменения (`core.py`, `parser.py`, …) — предсуществующие, не кодера (тот же список, что до его работы; `git diff --stat` без изменений с прошлого аудита).
- Проверено чтением кода + функциональными пробами + прогонами: 63/63 book-теста, `ruff check` чисто, полная сюита 505 passed / 10 deselected.

## Вердикт: [APPROVED]

Все пункты прошлого [REJECTED] закрыты (каждый перепроверен прогоном, не только чтением):

| Блок кода | Тип | Статус перепроверки |
|---|---|---|
| `providers.py: search_openlibrary`, ISBN-ветка (Крит: авторы как OL-ключи) | Крит | Закрыт. Добавлен `_resolve_ol_author_names()` (первые 3 ключа, тот же fetcher, guarded); нерезолвящееся отбрасывается. Пробы: ключи → `('Frank Herbert',)`; битый author-doc → `()`. Регрессионные тесты `test_ol_isbn_authors_resolved_to_names`, `test_ol_isbn_unresolvable_keys_dropped` зелёные |
| `filename.py: _YEAR_RE` (`1984` съедался) | Warning | Закрыт. Fallback на очищенный stem. Проба: `'1984.fb2'` → `title='1984', year=1984`, `is_empty()==False` |
| `epub.py: parse_container_bytes` (нет ENTITY-гарда) | Warning | Закрыт. Гард добавлен (строчка 33, зеркало OPF). Пробы upper/lower-case ENTITY → `''` |
| `fb2.py` (срез рвал XML на больших файлах) | Warning | Закрыт. `_description_stub()` + `_parse_maybe_large()` в обоих путях (`fb2`, `fb2.zip`). Проба: 20 КБ тело при бюджете 300 Б → `title='Big'`, автор верный |
| `pdf.py` (XMP не парсился) | Warning | Закрыт. `parse_xmp_bytes()` (`rdf:li` и прямая формы, unescape сущностей); XMP побеждает мусорный Info и по автору тоже (`or is_garbage_text`). Проба: `Untitled/Microsoft Word` + XMP → `XT/XA` |
| `identify.py`, `pipeline.py`, `fusion.py` (ruff F401/F841) | Warning | Закрыт. `ruff check` по `namer/books` и всем book-тестам — чисто (заодно вычищены 3 аналогичных в старых тест-файлах) |
| roadmap / архитектура (v2 «канон только из сети») | Warning | Частично — решение архитектора. Кодер задокументировал и разблокировал сеть: `process_books_directory()` принимает `searchers=[...]` (fused-канон переопределяет локальное, проба зелёная), `known_title` прокинут, offline по умолчанию с явным docstring. Сам `doc/roadmap.md` по-прежнему отсутствует — сверить п.6 чек-листа не с чем; требуется действие архитектора, код вне его компетенции чист |
| `models.py: is_empty` | Opt | Закрыт. Явные isinstance-гарды + `try/except → True`. Проба: `title_hint=123` → `True`, без исключений |
| `djvu.py` (попольная копия Query) | Opt | Закрыт. Возврат `via` напрямую |
| `pipeline.py` (нет `known_title`) | Opt | Закрыт. Параметр добавлен и прокинут в `build_query` + `generate_book_name`; проба зелёная |
| `epub.py` OPF-fallback правил текст | Opt | Закрыт. `_inject_opf_ns()` правит только тег `<package>`; существующие тесты (фича без `xmlns:opf`) зелёные |

## Чек-лист (итог)

1. **Память/ресурсы** — ок: context managers везде, чтения в `ReadBudget`, сабпроцесс без shell с timeout, новых утечек/дескрипторов фиксы не внесли (стаб — срез байтов в памяти, XMP — те же уже прочитанные байты).
2. **Безопасность** — ок: ENTITY-гард теперь везде (container закрыт); OPF-fallback больше не мутирует контент; author-fetch — тот же http-клиент с timeout, без новых примитивов.
3. **Сложность** — ок: стаб O(cap), XMP O(2 МБ), author-resolve ≤3 запросов на файл и только в ISBN-ветке; скрытых циклов нет.
4. **Читаемость** — ок, ruff чист; AUDIT-комментарии на каждом фиксе.
5. **Тесты** — ок: 63/63 (54 старых + 9 новых в `tests/test_books_audit_fixes.py`, включая требуемый «ISBN-doc с authors-ключами даёт человеческие имена»).
6. **Roadmap** — без изменений: `doc/roadmap.md` отсутствует; отклонение v2 кодер смягчил opt-in сетью + docstring, но формальное решение — за архитектором.

## Приёмка

Условие прошлого аудита выполнено (Крит + тест). Блокеров нет — можно мёрджить книжный домен. Отдельно архитектору: создать `doc/roadmap.md` и зафиксировать offline-политику.
