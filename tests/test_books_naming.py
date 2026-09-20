"""Naming: templates, validation, generate_book_name."""
from namer.books.models import BookOpinion, BookRecord
from namer.books.naming import (
    generate_book_name, provisional_record, render_book_name,
    template_uses,
)


def _rec(**kw):
    d = dict(title='Чапаев', authors=('Пелевин',), confidence=0.9)
    d.update(kw)
    return BookRecord(**d)


def test_template_uses():
    assert template_uses('{author} - {title}.{ext}', 'author') is True
    assert template_uses('{author} - {title}.{ext}', 'isbn') is False
    assert template_uses('{series_index:02d}', 'series_index') is True
    assert template_uses('', 'title') is False
    assert template_uses(None, 'title') is False


def test_render_plain_and_series():
    n = render_book_name(_rec(year=1996), 'fb2')
    assert n == 'Пелевин - Чапаев (1996).fb2'
    n2 = render_book_name(_rec(series='S', series_index=2), 'epub')
    assert n2 == 'Пелевин - S - 02 - Чапаев.epub'


def test_render_missing_fields_refuses():
    assert render_book_name(_rec(series='S', series_index=None),
                            'fb2', '{author} - {series} - {series_index:02d} - {title}.{ext}') is None
    assert render_book_name(_rec(title='x'), 'fb2') is None  # title too short
    assert render_book_name('not-a-record', 'fb2') is None
    assert render_book_name(_rec(), 'fb2', '{unknown_field}.{ext}') is None
    assert render_book_name(_rec(), 'fb2', '{author} - {title}.{ext} {isbn}') is None  # no isbn


def test_render_empty_author_no_dangling_dash():
    # junk epub/filename-only with no author must not produce '- title.ext'
    n = render_book_name(_rec(title='manual', authors=()), 'epub')
    assert n == 'manual.epub'
    n2 = render_book_name(_rec(title='T2', authors=()), 'fb2', '{author} - {title}.{ext}')
    assert n2 == 'T2.fb2'


def test_render_sanitizes():
    n = render_book_name(_rec(title='А/Б: В?'), 'fb2', '{title}.{ext}')
    assert '/' not in n and '?' not in n
    assert n.endswith('.fb2')


def test_provisional():
    from namer.books.models import BookIdentity, BookQuery
    ident = BookIdentity(status='identified', query=BookQuery(title_hint='T' * 1))
    assert provisional_record(ident) is None  # 1-char title
    ident2 = BookIdentity(status='identified',
                          query=BookQuery(title_hint='Книга', authors_hint=('А',)))
    r = provisional_record(ident2)
    assert r is not None and r.provider == 'local'


def test_generate_offline_fb2(tmp_path):
    data = ('<?xml version="1.0"?><FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
            '<description><title-info><book-title>Книга</book-title>'
            '<author><first-name>А</first-name><last-name>Б</last-name></author>'
            '</title-info></description></FictionBook>').encode('utf-8')
    p = tmp_path / 'a.fb2'
    p.write_bytes(data)
    new, ident = generate_book_name(str(p))
    assert new == 'А Б - Книга.fb2'
    assert ident.usable


def test_generate_network_overrides_local(tmp_path):
    p = tmp_path / 'Автор - Локальное.fb2'
    p.write_bytes(b'junk')
    ops = [BookOpinion('openlibrary', _rec(title='Канон', authors=('К А',), provider='openlibrary'), 0.9)]
    new, ident = generate_book_name(str(p), opinions=ops)
    assert 'Канон' in new
    assert ident.record.provider == 'openlibrary'


def test_generate_unresolvable_returns_basename(tmp_path):
    p = tmp_path / 'x.pdf'
    p.write_bytes(b'%PDF junk no title')
    new, ident = generate_book_name(str(p))
    assert new == 'x.pdf'
    assert not ident.usable
    assert generate_book_name('')[0] == ''


def test_generate_custom_pattern(tmp_path):
    p = tmp_path / 'Автор - Название.fb2'
    p.write_bytes(b'junk')
    new, _ = generate_book_name(str(p), pattern='{title}.{ext}')
    assert new == 'Название.fb2'
