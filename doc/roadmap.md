# Roadmap namer — единственный источник истины по архитектуре

*Владелец: Architect. Статус: видео-домен стабилен; книжный домен реализован
(`namer/books/`, 63 теста) и принят аудитом; открыты два решения ниже (раздел 8).*

Связанные документы: `doc/architecture-identify.md` (детали L0–L3 видео),
`doc/development.md` (гайд разработчика), `doc/usage.md` (CLI),
`doc/audit.md` (акты приёмки).

---

## 1. Видео-домен (стабилен, не трогать)

Слои L0–L3, инварианты и data flow — см. `doc/architecture-identify.md`.
Кратко для связности:

| Слой | Модуль | Контракт |
|---|---|---|
| L0 сырой вход | `namer/parser.py` | `parse_file(path) -> dict` — тонкий адаптер над L1, побайтово guarded `tests/test_parse_adapter.py` |
| L1 typed identify | `namer/identify/` | `identify_filename(IdentifyInput) -> Identity`, offline, детерминирован, без сети |
| L2 evidence | `namer/provider_opinion.py`, `namer/providers.py` | `ProviderOpinion(provider, values, abstain)`, duck-совместим с legacy `Feed` |
| L2 арбитраж | `namer/fusion.py` | `fuse() ≡ vote()` по победителю и решению; отличается только posterior `confidence` |
| L3 политика | `namer/core.py` | спорные season/episode → отказ (skip), не угадывание; no-clobber rename |

**Инварианты видео (закон):** `parse_file ≡ identify`-проекция; `fuse ≡ vote`;
не угадывать дорогие поля; атомарный no-clobber (`link+unlink`, fallback
`renameat2(RENAME_NOREPLACE)`); `reserved`-множество против внутрибатчевых коллизий.

---

## 2. Книжный домен: цель и границы

**Цель:** переименование книг `fb2 / fb2.zip / epub / pdf / djvu` по пользовательскому
шаблону, канон — автор/название/серия/год из сети, локальное — только ключи поиска.

**Non-goals:** OCR; конвертация форматов; запись метаданных внутрь файлов;
перемещение по библиотеке; изменение видео-пайплайна.

**Архитектурное решение (v2, обязательно):**
локальные экстракторы производят только грязный `BookQuery` (подсказки для поиска),
канонические значения для шаблона живут только в `BookRecord` из провайдеров.
Временное отклонение (зафиксировано аудитом, на решение — раздел 8):
`generate_book_name(allow_local=True)` и `process_books_directory(searchers=None)`
умеют офлайн-режим через provisional local-record; сеть — opt-in.

---

## 3. Структура модулей (реализовано, LOW COUPLING)

```
namer/books/__init__.py   # фасад: BOOK_EXTENSIONS, book_kind, is_book_path,
                          # identify_book, build_query, fuse_opinions,
                          # generate_book_name, render_book_name,
                          # process_books_directory, TEMPLATE_BOOK(_SERIES)
namer/books/models.py     # ReadBudget, BookQuery, BookRecord, BookOpinion, BookIdentity
namer/books/detect.py     # kind/ext (.fb2.zip — compound), normalize_isbn (checksum),
                          # find_isbns_in_text, is_garbage_text, find_book_files
namer/books/filename.py   # эвристика: Автор - Серия - 02 - Название (+год, ISBN);
                          # числовые названия не съедаются годом (1984)
namer/books/fb2.py        # title-info (book-title/author/sequence/date/lang),
                          # publish-info isbn; document-info/* игнорируется
                          # (автор ФАЙЛА ≠ автор книги); большие файлы — description-стаб
namer/books/epub.py       # container.xml → OPF → dc:title/creator(scheme=ISBN)/
                          # language/date/publisher + calibre:series(_index);
                          # переводчики (trl) отбрасываются; xmlns:opf-инъекция
namer/books/pdf.py        # Info (/Title/Author) + XMP (dc:title/creator, приоритет над
                          # мусорным Info) + ISBN из текстового слоя (optional pypdf,
                          # иначе raw-скан); stoplist сканеров/Word
namer/books/djvu.py       # ANTa-скан + optional djvused (без shell, с timeout),
                          # fallback — filename
namer/books/identify.py   # merge_queries(embedded+filename+known_*) → identify_book
namer/books/providers.py  # search_openlibrary (ISBN → title+author; авторы резолвятся
                          # из /authors/*.json, bounded ≤3), search_googlebooks;
                          # fetcher инжектится, любая сетевая/JSON-ошибка → []
namer/books/fusion.py     # fuse_opinions: ISBN-согласие ≥2 → ~0.99; согласие
                          # title+author → +; одиночный title-only без ISBN → None
namer/books/naming.py     # TEMPLATE_BOOK(_SERIES), render/generate/provisional_record
namer/books/pipeline.py   # process_books_directory → (renamed, total, errors),
                          # rename через core.rename_file, батч не падает
```

**Запрет связности:** `namer/books/*` не импортирует видео-слой
(`parser`, `identify/`, `providers`, `fusion`, `tmdb`, `tvmaze`, `wikipedia`,
`ffprobe`, `enricher`). Разрешены: `stdlib`, `namer.core` (только
`_sanitize_filename`, `rename_file`). Единственная точка coupling наружу —
опциональный однострочный диспетчер в `core.generate_new_name` (см. раздел 7),
видео-сигнатуры не меняются.

---

## 4. Интерфейсы и контракты

```python
ReadBudget(max_uncompressed=16МБ, max_entries=512, max_xml_bytes=2МБ, timeout_sec=5.0)

BookQuery  # ГРЯЗНЫЕ hints, НЕ значения для шаблона.
  # title_hint, authors_hint, series_hint, series_index_hint, isbn_hint,
  # lang_hint, year_hint, fingerprint, source_format
  # PRE: любые типы/мусор. POST: is_empty()/has_isbn() никогда не бросают.
  # INV: пустой запрос в сеть не уходит.

BookRecord # КАНОН для шаблона.
  # title, authors, series, series_index, year, language, isbn13, publisher,
  # provider (openlibrary|googlebooks|local), provider_id, confidence ∈ [0,1]
  # INV: confidence вне [0,1] → ValueError; title длиной ≥2 для рендера.

BookOpinion(provider, record, confidence ∈ [0,1])

BookIdentity(status ∈ {identified, ambiguous, unresolved}, title, authors,
             series(+index), year, language, isbn, ext, query, record,
             warnings, evidence)
  # usable ⇔ status == identified и len(title) ≥ 2.
  # ISBN без названия → ambiguous («нужен сетевой lookup»).

BookExtractor (протокол): extract(path, budget) -> BookQuery
  # PRE: путь существует. POST: []-эквивалент (пустой Query) при отсутствии меты;
  # никогда не пишет на диск, не ходит в сеть, соблюдает budget.

BookProvider (протокол): search(query) -> list[BookOpinion]
  # PRE: query непуст. POST: [] при miss/ошибке; исключений наружу нет.

identify_book(path, known_title='', known_author='') -> BookIdentity
  # offline, детерминирован; known_* побеждают hints, но не сеть.

fuse_opinions([BookOpinion]) -> BookRecord | None
  # ISBN-согласие сильнее всего; конфликт/одиночный слабый → None (skip).

generate_book_name(path, pattern='', known_title='', known_author='',
                   opinions=None, allow_local=True) -> (basename, BookIdentity)
  # opinions (сеть) через fuse переопределяют локальное; без opinions —
  # provisional local (deviation, раздел 8). Нет title ≥2 / нет нужного поля
  # под шаблон / неизвестный плейсхолдер → вернуть исходный basename + skip.

process_books_directory(dir, pattern='', known_title='', known_author='',
                        dry_run, recursive, verbose,
                        searchers=None, allow_local=True) -> (renamed, total, errors)
  # searchers=[search_openlibrary, search_googlebooks] включает канон-из-сети.
  # Переименование только через core.rename_file (атомарно, no-clobber, reserved).
```

**Канон поиска по форматам:** fb2 — лучший (title-info + publish-info isbn);
epub — второй (OPF DC + calibre); pdf — Info не заслуживает доверия, ключ — ISBN
из текстового слоя + XMP; djvu — почти всегда только filename (+ANTa/djvused если есть).
`document-info/author` (fb2) и `/Author`-сканера (pdf) — в stoplist, никогда не авторы.

---

## 5. Data Flow

```
path ── book_kind() ──┬── video-ext ──> существующий L0–L3 (без изменений)
                      └── book-ext ──> extractor(kind).extract ─┐
                                         filename.parse ───────┤→ merge → BookQuery
                                         known_* ──────────────┘        │
                                                                        v
                                              searchers (opt-in): openlibrary / googlebooks
                                                                        │ search(query)
                                                                        v
                                              [BookOpinion] → fuse_opinions → BookRecord
                                                                        │ (или provisional local)
                                                                        v
                                              render(template, record) → sanitize →
                                              → rename_file (атомарно, no-clobber)
                                              miss/conflict/нет полей → SKIP (файл на месте)
```

---

## 6. Шаблоны книг

```
TEMPLATE_BOOK        = '{author} - {title} ({year}).{ext}'
TEMPLATE_BOOK_SERIES = '{author} - {series} - {series_index:02d} - {title}.{ext}'
```

Поля: `{author}` (= authors[0]), `{authors}`, `{title}`, `{series}`,
`{series_index}`, `{year}`, `{lang|language}`, `{isbn}`, `{publisher}`, `{ext}`
(compound `fb2.zip` сохраняется целиком). Пустые `()`/`(0)` вычищаются как у видео.
Шаблон требует отсутствующее поле (`series_index`/`series`/`isbn`) или содержит
неизвестный плейсхолдер → отказ, не угадывание. Шаблон без `{ext}` → отказ
(защита от потери расширения).

---

## 7. Безопасность, масштаб, тесты

**Безопасность:** zip-bomb — `ReadBudget` (размер/число записей/суммарный размер);
XXE — `<!ENTITY`-гард на fb2/OPF/container; traversal невозможен (читаются только
именованные записи, распаковки нет); `djvused` — список аргументов, без shell,
с timeout; PDF — без `/Launch`/`/JS`, лимит 2 МБ; сеть — timeout 5с, чтение ≤512 КБ,
без секретов (ключи не нужны); rename — только no-clobber примитивы ядра.

**Масштаб:** экстракторы линейны и зарезаны бюджетом; author-resolve ≤3 запросов
и только в ISBN-ветке; файлы независимы — батч последователен, один плохой файл
батч не роняет (`errors` счётчик, exit-код для CI — на вызывающей стороне).

**Тесты (реализовано):** `tests/test_books_*.py` — 63 теста (detect, filename,
fb2, epub, pdf/djvu, identify+fusion+providers с моками, naming, pipeline,
audit-регрессии). Полная сюита: 505 passed / 10 deselected. Видео-инварианты
не затронуты (книжный код — только новые файлы).

**Врезка в ядро (одна строка, не применена — ждёт решения из раздела 8):**
```python
# core.generate_new_name, в начало:
from namer.books import is_book_path
from namer.books.naming import generate_book_name as _book_name
if is_book_path(file_path):
    nm, bi = _book_name(file_path, pattern=pattern, known_title=known_title,
                        known_author='', opinions=None)
    meta = {'title': bi.title, 'is_series': False, 'ext': bi.ext,
            '_skip': not bi.usable, '_skip_reason': ';'.join(bi.warnings)}
    return nm, meta
```

---

## 8. Открытые решения (требуют вердикта Architect → правка сюда)

1. **Offline vs канон-из-сети.** Реализован компромисс: сеть opt-in через
   `searchers`, по умолчанию provisional local. Строгая v2 требует
   «канон только из сети + skip без неё». Решить и зафиксировать итог здесь.
2. **CLI:** прокинуть книжный режим (`-a/--author`, авто-детект по расширению,
   передача `searchers` + флага `--enrich-books`) — после решения п.1.
3. **P6 (вне MVP):** кэш ответов сети (TTL), rate-limit, enrich по fingerprint
   для сканов PDF/DjVu без ISBN.

*История: книги спроектированы как изолированный домен (аналог L0–L3: L1 — экстракторы,
L2 — providers+fusion, L3 — naming/pipeline с refuse-политикой); приёмка — `doc/audit.md`.*
