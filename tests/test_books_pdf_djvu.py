"""PDF + DjVu extractors incl. garbage filtering and ISBN."""
from namer.books.djvu import extract_via_djvused, parse_djvu_meta_bytes
from namer.books.pdf import (
    extract_pdf_query, parse_pdf_info_bytes, split_authors,
    _text_title_authors,
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


def test_text_pdf_cover_author_before_title():
    title, authors = _text_title_authors(
        'CHRISTOPHER W. TOTTEN\nARCHITECTURAL APPROACH TO\n'
        'LEVEL\nDESIGN\n2ND EDITION\n')
    assert title == 'ARCHITECTURAL APPROACH TO LEVEL DESIGN'
    assert authors == ('CHRISTOPHER W. TOTTEN',)


def test_ocr_cover_skips_tagline_and_finds_author_below_title():
    title, authors = _text_title_authors(
        'для профессионалов\nВнутреннее устройство\nLINUX\nБрайан Уорд\n'
    )
    assert title == 'Внутреннее устройство Linux'
    assert authors == ('Брайан Уорд',)


def test_ocr_cover_author_before_multiline_title():
    title, authors = _text_title_authors(
        'Марх Симан\nКод, который\nумещается\nв голове\nЭвристики\n'
    )
    assert title == 'Код, который умещается в голове'
    assert authors == ('Марх Симан',)


def test_cover_edition_layouts_choose_title_not_series_or_authors():
    title, authors = _text_title_authors(
        '4th Edition\nAndrew S. Tanenbaum,\nHerbert Bos\n'
        'MODERNMODERN\nOPERATING SYSTEMSOPERATING SYSTEMS')
    assert title == 'Modern Operating systems'
    assert authors == ('Andrew S. Tanenbaum', 'Herbert Bos')
    title, authors = _text_title_authors(
        'КЛАССИКА COMPUTER SCIENCE\nАРХИТЕКТУРА\nКОМПЬЮТЕРА\n'
        '6-Е ИЗДАНИЕ\nЭ. ТАНЕНБАУМ\nТ. ОСТИН')
    assert title == 'Архитектура Компьютера'
    assert authors == ('Э. ТАНЕНБАУМ', 'Т. ОСТИН')


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


def test_pdf_ocr_text_is_used_when_local_text_is_empty(tmp_path, monkeypatch):
    import namer.books.pdf as pdf

    p = tmp_path / 'scan.pdf'
    p.write_bytes(b'%PDF-1.4 scan')
    monkeypatch.setattr(pdf, '_try_pypdf', lambda path: ('', '', ''))
    monkeypatch.setattr(pdf, '_try_pdftotext', lambda path: '')
    monkeypatch.setattr(pdf, '_ocr_space_result',
                        lambda path: pdf.OCRResult('THE BOOK TITLE\nJane Author\n', status='success'))
    q = extract_pdf_query(str(p))
    assert q.title_hint == 'The book title'
    assert q.authors_hint == ('Jane Author',)
    assert any('THE BOOK TITLE' in item for item in q.diagnostics)


def test_pdf_ocr_replaces_filename_metadata(tmp_path, monkeypatch):
    import namer.books.pdf as pdf

    p = tmp_path / 'Tilul70 [Converted].pdf'
    p.write_bytes(b'%PDF-1.4 scan')
    monkeypatch.setattr(pdf, '_try_pypdf',
                        lambda path: ('Tilul70 [Converted]', '', ''))
    monkeypatch.setattr(pdf, '_try_pdftotext', lambda path: '')
    monkeypatch.setattr(pdf, '_ocr_space_result', lambda path: pdf.OCRResult(
        'Внутреннее устройство Линукс\nБрайан Уорд', status='success'))
    q = extract_pdf_query(str(p))
    assert q.title_hint == 'Внутреннее устройство Линукс'
    assert q.authors_hint == ('Брайан Уорд',)


def test_pdf_ocr_replaces_placeholder_author(tmp_path, monkeypatch):
    import namer.books.pdf as pdf

    p = tmp_path / 'mostipan - titul.indd.pdf'
    p.write_bytes(b'%PDF-1.4 scan')
    monkeypatch.setattr(pdf, '_try_pypdf',
                        lambda path: ('titul.indd', 'mostipan', ''))
    monkeypatch.setattr(pdf, '_try_pdftotext', lambda path: '')
    monkeypatch.setattr(pdf, '_ocr_space_result', lambda path: pdf.OCRResult(
        'Марх Симан\nКод, который\nумещается\nв голове', status='success'))
    q = extract_pdf_query(str(p))
    assert q.title_hint == 'Код, который умещается в голове'
    assert q.authors_hint == ('Марх Симан',)


def test_umi_ocr_local_http_adapter(monkeypatch):
    import json
    import namer.books.pdf as pdf

    monkeypatch.setattr(pdf, '_first_page_images', lambda path, pages: [b'png'])
    calls = []

    class Response:
        def __init__(self, data): self.data = data
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, _limit): return self.data

    def fake_urlopen(request, timeout=0):
        calls.append(request)
        if request.full_url.endswith('get_options'):
            return Response(b'{"ocr.language":{"optionsList":[["rus","Russian"]]}}')
        return Response(json.dumps({
            'code': 100, 'data': 'Внутреннее устройство Линукс',
        }).encode())

    monkeypatch.setattr(pdf.urllib.request, 'urlopen', fake_urlopen)
    assert pdf._try_umi_ocr('scan.pdf') == 'Внутреннее устройство Линукс'
    assert len(calls) == 2


def test_ocr_space_uses_public_demo_key_without_configuration(monkeypatch):
    import namer.books.pdf as pdf
    import namer.books.ocr as ocr

    monkeypatch.delenv('NAMER_DISABLE_OCR', raising=False)
    monkeypatch.delenv('OCR_SPACE_API_KEY', raising=False)
    monkeypatch.setattr(pdf, '_first_pages_pdf', lambda path, pages: b'%PDF-mini')
    seen = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, _limit): return b'{"ParsedResults":[{"ParsedText":"Title"}]}'

    def fake_urlopen(request, timeout=0):
        headers = {k.lower(): v for k, v in request.header_items()}
        seen['key'] = headers.get('apikey')
        seen['engine2'] = b'name="OCREngine"\r\n\r\n2' in request.data
        return Response()

    monkeypatch.setattr(ocr.urllib.request, 'urlopen', fake_urlopen)
    assert pdf._try_ocr_space('scan.pdf') == 'Title'
    assert seen['key'] == 'helloworld'
    assert seen['engine2'] is True


def test_ocr_space_caches_successful_result(monkeypatch):
    import namer.books.ocr as ocr

    monkeypatch.delenv('NAMER_DISABLE_OCR', raising=False)
    monkeypatch.setattr(ocr, '_BACKOFF_UNTIL', 0)
    calls = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, _limit): return b'{"ParsedResults":[{"ParsedText":"Cached title"}]}'

    def fake_urlopen(*args, **kwargs):
        calls.append(args)
        return Response()

    monkeypatch.setattr(ocr.urllib.request, 'urlopen', fake_urlopen)
    first = ocr.ocr_space_text(b'%PDF cached-pages')
    second = ocr.ocr_space_text(b'%PDF cached-pages')
    assert first.status == 'success'
    assert second.status == 'cached'
    assert second.text == 'Cached title'
    assert len(calls) == 1


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
