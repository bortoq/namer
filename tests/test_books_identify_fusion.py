"""Identify + providers (mocked) + fusion."""
from namer.books.fusion import fuse_opinions
from namer.books.identify import build_query, identify_book, merge_queries
from namer.books.models import BookOpinion, BookQuery, BookRecord
from namer.books.providers import search_googlebooks, search_openlibrary


def _rec(title='T', authors=('A',), isbn='', conf=0.9, provider='openlibrary'):
    return BookRecord(title=title, authors=authors, isbn13=isbn,
                      provider=provider, confidence=conf)


def test_merge_prefers_primary():
    p = BookQuery(title_hint='ET', authors_hint=('EA',), isbn_hint='9780306406157')
    f = BookQuery(title_hint='FT', authors_hint=('FA',))
    m = merge_queries(p, f)
    assert m.title_hint == 'ET'
    assert m.isbn_hint == '9780306406157'
    m2 = merge_queries(BookQuery(), f)
    assert m2.title_hint == 'FT'


def test_identify_fb2(tmp_path):
    data = ('<?xml version="1.0"?><FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
            '<description><title-info><book-title>Книга</book-title>'
            '<author><first-name>А</first-name><last-name>Б</last-name></author>'
            '</title-info></description></FictionBook>').encode('utf-8')
    p = tmp_path / 'k.fb2'
    p.write_bytes(data)
    ident = identify_book(str(p))
    assert ident.status == 'identified'
    assert ident.title == 'Книга'
    assert ident.ext == 'fb2'


def test_identify_unsupported_and_empty():
    assert identify_book('/x.mkv').status == 'unresolved'
    assert identify_book('').status == 'unresolved'
    assert identify_book(None).status == 'unresolved'
    q = build_query('')
    assert q.is_empty()


def test_identify_known_override(tmp_path):
    p = tmp_path / 'k.fb2'
    p.write_bytes(b'not xml')
    ident = identify_book(str(p), known_title='КТ', known_author='КА')
    assert ident.title == 'КТ'
    assert ident.authors == ['КА']


def test_fusion_isbn_agreement():
    o1 = BookOpinion('openlibrary', _rec('T', ('A',), '9780306406157', 0.9), 0.9)
    o2 = BookOpinion('googlebooks', _rec('T', ('A',), '9780306406157', 0.9, 'googlebooks'), 0.9)
    r = fuse_opinions([o1, o2])
    assert r is not None and r.isbn13 == '9780306406157'


def test_fusion_title_author_agreement():
    o1 = BookOpinion('openlibrary', _rec('Dune', ('Herbert',), '', 0.8), 0.8)
    o2 = BookOpinion('googlebooks', _rec('Dune!', ('Herbert',), '', 0.8, 'googlebooks'), 0.8)
    assert fuse_opinions([o1, o2]) is not None


def test_fusion_refuses_weak_single():
    o = BookOpinion('openlibrary', _rec('T', (), '', 0.6), 0.6)
    assert fuse_opinions([o]) is None
    assert fuse_opinions([]) is None
    assert fuse_opinions(None) is None


def test_providers_mocked_isbn():
    q = BookQuery(title_hint='X', isbn_hint='9780306406157')
    doc = {'title': 'Real', 'key': '/books/OL1M', 'publish_date': '2001'}
    ops = search_openlibrary(q, fetcher=lambda url: doc if 'isbn' in url else None)
    assert len(ops) == 1 and ops[0].record.title == 'Real'
    g = search_googlebooks(
        q, fetcher=lambda url: {'items': [{'id': 'g1', 'volumeInfo': {
            'title': 'Real', 'authors': ['A'], 'publishedDate': '2001',
            'industryIdentifiers': [{'type': 'ISBN_13', 'identifier': '9780306406157'}]}}]})
    assert len(g) == 1 and g[0].record.isbn13 == '9780306406157'


def test_providers_bad_network():
    q = BookQuery(title_hint='T', authors_hint=('A',))
    assert search_openlibrary(q, fetcher=lambda u: (_ for _ in ()).throw(OSError())) == []
    assert search_googlebooks(q, fetcher=lambda u: 'junk') == []
    assert search_openlibrary(BookQuery()) == []
    assert search_googlebooks(BookQuery()) == []
