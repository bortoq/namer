"""Regression tests for audit findings (doc/audit.md)."""
from namer.books.detect import find_isbns_in_text
from namer.books.epub import parse_container_bytes
from namer.books.fb2 import extract_fb2_query
from namer.books.filename import parse_book_filename
from namer.books.models import BookQuery
from namer.books.pdf import extract_pdf_query, parse_xmp_bytes
from namer.books.pipeline import process_books_directory
from namer.books.providers import search_openlibrary


def test_ol_isbn_authors_resolved_to_names():
    # AUDIT Крит: authors were OL keys ('/authors/OL..'), must be names.
    q = BookQuery(title_hint='Real Title', isbn_hint='9780306406157')

    def fetch(url):
        if url.endswith('.json') and '/authors/' in url:
            return {'name': 'Frank Herbert'}
        return {'title': 'Real Title', 'key': '/books/OL1M',
                'publish_date': '2001',
                'authors': [{'key': '/authors/OL23919A'}]}

    ops = search_openlibrary(q, fetcher=fetch)
    assert len(ops) == 1
    assert ops[0].record.authors == ('Frank Herbert',)
    assert not any('/authors/' in a for a in ops[0].record.authors)


def test_ol_isbn_unresolvable_keys_dropped():
    q = BookQuery(title_hint='Real Title', isbn_hint='9780306406157')

    def fetch(url):
        if '/authors/' in url:
            return None  # author doc missing
        return {'title': 'Real Title', 'key': '/books/OL1M',
                'authors': [{'key': '/authors/OL9A'}]}

    ops = search_openlibrary(q, fetcher=fetch)
    assert len(ops) == 1
    assert ops[0].record.authors == ()


def test_numeric_title_survives_year_filter():
    # AUDIT Warning: '1984.fb2' lost its title to the year pattern.
    q = parse_book_filename('1984.fb2')
    assert q.title_hint == '1984'
    assert q.year_hint == 1984
    assert not q.is_empty()


def test_container_entity_rejected():
    # AUDIT Warning: container.xml lacked the ENTITY guard.
    assert parse_container_bytes(b'<?xml?><x><!ENTITY x "y"></x>') == ''
    assert parse_container_bytes(b'<?xml?><x><!entity x "y"></x>') == ''


def test_large_fb2_parses_via_description_stub():
    # AUDIT Warning: oversized fb2 truncated mid-XML -> ParseError -> skip.
    from namer.books.models import ReadBudget
    head = ('<?xml version="1.0" encoding="utf-8"?>'
            '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
            '<description><title-info><book-title>Big</book-title>'
            '<author><first-name>A</first-name><last-name>B</last-name></author>'
            '</title-info></description><body><p>').encode('utf-8')
    tail = b'</p></body></FictionBook>'
    big = head + b'x' * 5000 + tail
    import os
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.fb2', delete=False) as f:
        f.write(big)
        path = f.name
    try:
        q = extract_fb2_query(
            path, ReadBudget(max_uncompressed=16 * 1024 * 1024,
                             max_entries=512, max_xml_bytes=300))
        assert q.title_hint == 'Big'
        assert q.authors_hint == ('A B',)
    finally:
        os.unlink(path)


def test_pdf_xmp_preferred_over_garbage_info(tmp_path):
    # AUDIT Warning: XMP dc:title/creator must win over garbage Info.
    xmp = (b'<x:xmpmeta><rdf:RDF><rdf:Description>'
           b'<dc:title><rdf:Alt><rdf:li xml:lang="x-default">XMP Title</rdf:li>'
           b'</rdf:Alt></dc:title>'
           b'<dc:creator><rdf:Seq><rdf:li>XMP Author</rdf:li></rdf:Seq></dc:creator>'
           b'</rdf:Description></rdf:RDF></x:xmpmeta>')
    data = (b'%PDF-1.4\n1 0 obj<</Title (Untitled)/Author (Microsoft Word)>>\n'
            + xmp + b'\n%%EOF')
    t, a = parse_xmp_bytes(data)
    assert t == 'XMP Title'
    assert a == 'XMP Author'
    p = tmp_path / 'x.pdf'
    p.write_bytes(data)
    q = extract_pdf_query(str(p))
    assert q.title_hint == 'XMP Title'
    assert q.authors_hint == ('XMP Author',)


def test_pipeline_known_title_and_searchers(tmp_path):
    # AUDIT Opt: known_title passthrough; network opinions override local.
    from namer.books.models import BookOpinion, BookRecord
    (tmp_path / 'a.fb2').write_bytes(b'junk')
    renamed, total, _ = process_books_directory(
        str(tmp_path), dry_run=True, known_title='Known Title')
    assert (renamed, total) == (1, 1)

    def searcher(query):
        assert query.title_hint  # built from file, not empty
        return [BookOpinion('openlibrary', BookRecord(
            title='Canon', authors=('Canon Author',), confidence=0.9,
            provider='openlibrary'), 0.9)]

    (tmp_path / 'sub_auth.fb2').write_bytes(b'junk2')
    renamed2, total2, _ = process_books_directory(
        str(tmp_path), dry_run=True, searchers=[searcher])
    assert total2 == 2  # dry-run changes nothing, so both files remain
    assert renamed2 == total2


def test_is_empty_type_guards():
    # AUDIT Opt: non-str hints count as missing, never raise.
    assert BookQuery(title_hint=123).is_empty() is True
    assert BookQuery(title_hint=['x']).is_empty() is True
    assert BookQuery(authors_hint=('A',)).is_empty() is False
    assert BookQuery(fingerprint='abc').is_empty() is False
    assert BookQuery().is_empty() is True


def test_isbn_helper_untouched():
    assert find_isbns_in_text('ISBN 9780306406157') == ['9780306406157']
