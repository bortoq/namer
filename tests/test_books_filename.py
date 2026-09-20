"""Filename heuristic incl. cyrillic, series, isbn, edges."""
from namer.books.filename import parse_book_filename, parse_series_index_token


def test_author_title():
    q = parse_book_filename('Пелевин - Чапаев и Пустота.fb2')
    assert q.title_hint == 'Чапаев и Пустота'
    assert q.authors_hint == ('Пелевин',)


def test_author_series_index_title():
    q = parse_book_filename('Пелевин - Диалектика - 02 - Книга.fb2')
    assert q.authors_hint == ('Пелевин',)
    assert q.series_hint == 'Диалектика'
    assert q.series_index_hint == 2
    assert q.title_hint == 'Книга'


def test_series_number_inside():
    q = parse_book_filename('Автор - Серия 03 - Название.epub')
    assert q.series_hint == 'Серия'
    assert q.series_index_hint == 3
    assert q.title_hint == 'Название'


def test_title_only():
    q = parse_book_filename('Одиночество в сети.pdf')
    assert q.title_hint == 'Одиночество в сети'
    assert q.authors_hint == ()


def test_bracket_author():
    q = parse_book_filename('[Толстой] Война и мир.djvu')
    assert q.authors_hint == ('Толстой',)
    assert 'Война' in q.title_hint


def test_year_extracted():
    q = parse_book_filename('Автор - Название (2010).fb2')
    assert q.year_hint == 2010
    assert '2010' not in q.title_hint


def test_isbn_extracted():
    q = parse_book_filename('Book 9780306406157 - Author - Title.fb2')
    assert q.isbn_hint == '9780306406157'


def test_compound_ext():
    q = parse_book_filename('Автор - Название.fb2.zip', 'fb2.zip')
    assert q.title_hint == 'Название'
    assert q.source_format == 'fb2.zip'


def test_edges():
    assert parse_book_filename('').is_empty()
    assert parse_book_filename(None).is_empty()
    assert parse_book_filename('   ').is_empty()
    assert parse_book_filename(123).is_empty()


def test_series_token():
    assert parse_series_index_token('02') == 2
    assert parse_series_index_token('#2') == 2
    assert parse_series_index_token('т.2') == 2
    assert parse_series_index_token('Vol 3') == 3
    assert parse_series_index_token('Название') is None
    assert parse_series_index_token('') is None
    assert parse_series_index_token(None) is None
