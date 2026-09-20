"""FB2 / FB2.ZIP extractor."""
import zipfile

from namer.books.fb2 import extract_fb2_query, extract_fb2zip_query, parse_fb2_bytes

FB2_MIN = '''<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
<description><title-info>
<book-title>Чапаев и Пустота</book-title>
<author><first-name>Виктор</first-name><last-name>Пелевин</last-name></author>
<sequence name="Романы" number="3"/>
<date value="1996-01-01">1996</date>
<lang>ru</lang>
</title-info><publish-info><isbn>9780306406157</isbn></publish-info></description>
<body><p>text</p></body></FictionBook>'''.encode('utf-8')

FB2_DOC_AUTHOR = '''<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
<description><title-info><book-title>Книга</book-title>
<author><first-name>А</first-name><last-name>Автор</last-name></author>
</title-info><document-info><author><nickname>ScanMan</nickname></author>
<id>some-uuid</id></document-info></description>
<body><p>t</p></body></FictionBook>'''.encode('utf-8')


def test_fb2_full():
    q = parse_fb2_bytes(FB2_MIN)
    assert q.title_hint == 'Чапаев и Пустота'
    assert q.authors_hint == ('Виктор Пелевин',)
    assert q.series_hint == 'Романы'
    assert q.series_index_hint == 3
    assert q.year_hint == 1996
    assert q.lang_hint == 'ru'
    assert q.isbn_hint == '9780306406157'


def test_fb2_ignores_document_info_author():
    q = parse_fb2_bytes(FB2_DOC_AUTHOR)
    assert q.authors_hint == ('А Автор',)
    assert 'ScanMan' not in str(q.authors_hint)


def test_fb2_edges():
    assert parse_fb2_bytes(b'').is_empty()
    assert parse_fb2_bytes(None).is_empty()
    assert parse_fb2_bytes(b'not xml at all {{{').is_empty()
    assert parse_fb2_bytes(b'<?xml?><x><!ENTITY x "y"></x>').is_empty()
    assert parse_fb2_bytes('str-not-bytes').is_empty()


def test_fb2_file(tmp_path):
    p = tmp_path / 'b.fb2'
    p.write_bytes(FB2_MIN)
    q = extract_fb2_query(str(p))
    assert q.title_hint == 'Чапаев и Пустота'
    assert extract_fb2_query(str(tmp_path / 'missing.fb2')).is_empty()
    assert extract_fb2_query('').is_empty()
    assert extract_fb2_query(None).is_empty()


def test_fb2zip(tmp_path):
    zp = tmp_path / 'b.fb2.zip'
    with zipfile.ZipFile(str(zp), 'w') as z:
        z.writestr('book.fb2', FB2_MIN)
    q = extract_fb2zip_query(str(zp))
    assert q.title_hint == 'Чапаев и Пустота'
    assert q.source_format == 'fb2.zip'
    # no fb2 inside
    zp2 = tmp_path / 'empty.zip'
    with zipfile.ZipFile(str(zp2), 'w') as z:
        z.writestr('readme.txt', b'hi')
    assert extract_fb2zip_query(str(zp2)).is_empty()
    assert extract_fb2zip_query(str(tmp_path / 'no.zip')).is_empty()
    # bad zip bytes with .fb2.zip name
    bad = tmp_path / 'bad.fb2.zip'
    bad.write_bytes(b'not a zip')
    assert extract_fb2zip_query(str(bad)).is_empty()
