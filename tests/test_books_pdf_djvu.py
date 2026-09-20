"""PDF + DjVu extractors incl. garbage filtering and ISBN."""
from namer.books.djvu import extract_via_djvused, parse_djvu_meta_bytes
from namer.books.pdf import (
    extract_pdf_query, parse_pdf_info_bytes, split_authors,
)

PDF_MIN = (b'%PDF-1.4\n1 0 obj<</Title (Real Book Title)/Author (Ivan Petrov)'
           b'/Creator (Acrobat)>>\nstartxref\n%%EOF')


def test_pdf_info_scan():
    t, a = parse_pdf_info_bytes(PDF_MIN)
    assert t == 'Real Book Title'
    assert a == 'Ivan Petrov'
    assert parse_pdf_info_bytes(b'') == ('', '')
    assert parse_pdf_info_bytes(None) == ('', '')
    assert parse_pdf_info_bytes(b'%PDF no info') == ('', '')


def test_pdf_escaped_parens():
    data = b'/Title (A \\(test\\) book)'
    t, _ = parse_pdf_info_bytes(data)
    assert t == 'A (test) book'


def test_split_authors():
    assert split_authors('Ivanov, Petrov and Sidorov') == ('Ivanov', 'Petrov', 'Sidorov')
    assert split_authors('Microsoft Word') == ()
    assert split_authors('') == ()
    assert split_authors(None) == ()


def test_pdf_garbage_filtered(tmp_path):
    p = tmp_path / 'g.pdf'
    p.write_bytes(b'%PDF-1.4\n1 0 obj<</Title (Untitled)/Author (Microsoft Word)>>\n%%EOF')
    q = extract_pdf_query(str(p))
    assert q.title_hint == ''
    assert q.authors_hint == ()


def test_pdf_isbn_from_text(tmp_path):
    p = tmp_path / 'i.pdf'
    p.write_bytes(b'%PDF-1.4\nISBN 9780306406157\n%%EOF')
    q = extract_pdf_query(str(p))
    assert q.isbn_hint == '9780306406157'


def test_pdf_edges():
    assert extract_pdf_query('').is_empty()
    assert extract_pdf_query(None).is_empty()
    assert extract_pdf_query('/nonexistent-x.pdf').is_empty()


def test_djvu_meta_scan():
    data = '(title "Dune" author "Frank Herbert") ISBN 9780306406157'.encode('latin-1')
    q = parse_djvu_meta_bytes(data)
    assert q.title_hint == 'Dune'
    assert 'Frank Herbert' in q.authors_hint
    assert q.isbn_hint == '9780306406157'
    assert parse_djvu_meta_bytes(b'').is_empty()
    assert parse_djvu_meta_bytes(None).is_empty()


def test_djvu_no_tool_or_file(tmp_path):
    # missing binary path -> empty, never raises
    q = extract_via_djvused(str(tmp_path / 'no.djvu'))
    assert q.is_empty()
    from namer.books.djvu import extract_djvu_query
    assert extract_djvu_query('').is_empty()
    assert extract_djvu_query('/nonexistent-x.djvu').is_empty()
    p = tmp_path / 'x.djvu'
    p.write_bytes(b'AT&TFORM garbage no meta')
    assert extract_djvu_query(str(p)).is_empty()
