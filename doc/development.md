# namer — руководство разработчика

## Быстрый старт

```bash
# все тесты
python3 -m pytest -q

# проверка компиляции всех модулей
python3 -m compileall -q namer

# локальный запуск без установки (только предпросмотр)
python3 -m namer -n -d /path/to/videos
```

## Структура

Видео-конвейер:

| Модуль | Ответственность |
|---|---|
| `namer/parser.py` | Механический разбор имени: сезон, эпизод, год, качество, расширение, название. |
| `namer/identify/` | L1-идентификация: `identify_filename()` -> `Identity` (офлайн, с уверенностью). |
| `namer/language.py` | Коды языков Wikipedia и детект по скрипту (чистая функция, офлайн). |
| `namer/quality.py` | Токены качества (`QualityInfo`, `parse_quality`). |
| `namer/provider_opinion.py` | Общая схема провайдеров (`ProviderOpinion`), совместима с legacy-`Feed`. |
| `namer/providers.py` | Мнения провайдеров (имя файла, каталог, файл, wikipedia, tvmaze, tmdb). |
| `namer/fusion.py` | Байесовское слияние мнений -> `Verdict` (`Decision L3`). |
| `namer/voting.py` | Исходное взвешенное голосование; `fuse()` — drop-in эквивалент. |
| `namer/core.py` | Полный конвейер, политика, рендер шаблонов, атомарное переименование. |
| `namer/scanner.py` | Рекурсивный поиск видеофайлов. |
| `namer/cli.py` | Аргументы и точка входа. |

Книжный домен (`namer/books/`, изолирован от видео-слоя):

| Модуль | Ответственность |
|---|---|
| `namer/books/models.py` | `BookQuery` (грязные подсказки), `BookRecord` (канон для шаблона), `BookOpinion`, `BookIdentity`, `ReadBudget`. |
| `namer/books/detect.py` | Тип файла (включая составное `.fb2.zip`), нормализация ISBN с чек-суммой, фильтр мусора, поиск файлов книг. |
| `namer/books/filename.py` | Эвристика `Автор - Серия - 02 - Название` из имени файла. |
| `namer/books/fb2.py` | `fb2` и `fb2.zip`: `title-info`, `publish-info`; стаб `description` для больших файлов. |
| `namer/books/epub.py` | `container.xml` -> OPF (`dc:*`, серия calibre). |
| `namer/books/pdf.py` | Info, XMP (приоритет), ISBN из текстового слоя (optional `pypdf`). |
| `namer/books/djvu.py` | Скан `ANTa`, optional `djvused` (без shell, с timeout). |
| `namer/books/identify.py` | Слияние hints -> `BookIdentity` (офлайн, без сети). |
| `namer/books/providers.py` | Поиск OpenLibrary / GoogleBooks; fetcher инжектится, ошибки -> `[]`. |
| `namer/books/fusion.py` | `fuse_opinions()`: согласие по ISBN сильнее всего; слабый одиночный ответ — отказ. |
| `namer/books/naming.py` | Шаблоны книг, `generate_book_name()`, provisional local-запись. |
| `namer/books/pipeline.py` | Пакетное переименование книг; сеть opt-in через `searchers`. |

Архитектура верхнего уровня: `doc/roadmap.md`; детали видео-слоёв:
`doc/architecture-identify.md`.

## Ключевые инварианты

Видео:

1. **`parse_file` — тонкий адаптер.** Поля берутся из
   `identify_filename(IdentifyInput)`; плоский dict — проекция.
   Охраняется `tests/test_parse_adapter.py` (побайтовая эквивалентность).
2. **`fuse()` ≡ `vote()`** по победителю и решению за счёт общих кластеризации
   и правил; отличается только posterior-`confidence`.
   Охраняется `tests/test_fusion.py`.
3. **Запрет угадывания дорогих полей** (сезон/эпизод). Неоднозначность — отказ.
4. **Без перезаписи.** Переименование атомарно и не затирает существующие записи.

Книги:

5. **Разделение запроса и канона.** Экстракторы дают только грязный `BookQuery`;
   в шаблон идёт только `BookRecord` (сеть либо помеченная provisional-запись).
6. **Функции не бросают исключений** на грязном входе: пустой запрос,
   `unresolved`-идентичность, пропуск файла вместо падения батча.
7. **Лимиты чтения** (`ReadBudget`): размер, число записей архива, XML-байты,
   timeout внешнего процесса. Превышение — fallback, не ошибка.

## Тесты

| Файл | Покрытие |
|---|---|
| `tests/test_parser.py` | примитивы парсера |
| `tests/test_identify.py` | L1-слой |
| `tests/test_parse_adapter.py` | дифференциал parse_file ↔ legacy |
| `tests/test_language.py` | коды языков и детект |
| `tests/test_providers.py` | мнения провайдеров |
| `tests/test_voting.py` | консенсус |
| `tests/test_fusion.py` | схема, слияние, эквивалентность |
| `tests/test_core.py` | сквозной конвейер и политика |
| `tests/test_enricher.py`, `tests/test_tvmaze.py`, `tests/test_wikipedia_episodes.py` | сетевые провайдеры (замоканы) |
| `tests/test_books_detect.py`, `tests/test_books_filename.py` | тип файлов, ISBN, эвристика имени |
| `tests/test_books_fb2.py`, `tests/test_books_epub.py`, `tests/test_books_pdf_djvu.py` | экстракторы форматов |
| `tests/test_books_identify_fusion.py` | идентификация, провайдеры (замоканы), слияние |
| `tests/test_books_naming.py`, `tests/test_books_pipeline.py` | шаблоны, пакетное переименование |
| `tests/test_books_audit_fixes.py` | регрессии из `doc/audit.md` |
| `tests/test_books_cli.py` | сквозной вызов `namer` с книгами |

Полная сюита: `python3 -m pytest` (514 passed / 10 deselected; книг — 72).

## Внесение изменений

1. Добавить падающий тест, называющий требуемое поведение.
2. Реализовать по тестам; сохранить инварианты 1–7 выше.
3. Запустить `python3 -m pytest -q`; регрессий — ноль.
4. При касании решений `fuse()` перепрогнать корпус эквивалентности,
   чтобы drop-in гарантия сохранилась.
5. Книжный код не импортирует видео-слой; общие только санитайз
   (`core._sanitize_filename`) и `core.rename_file`.
