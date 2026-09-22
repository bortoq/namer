"""EPUB extractor incl. calibre series, translators, edges."""
import zipfile

from namer.books.epub import (
    extract_epub_query, parse_container_bytes, parse_opf_bytes,
)

OPF = '''<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/">
<metadata>
<dc:title>Дюна</dc:title>
<dc:creator opf:role="aut">Фрэнк Герберт</dc:creator>
<dc:creator opf:role="trl">Переводчик</dc:creator>
<dc:identifier opf:scheme="ISBN">9780306406157</dc:identifier>
<dc:language>ru</dc:language>
<dc:date>1965-01-01</dc:date>
<dc:publisher>АСТ</dc:publisher>
<meta name="calibre:series" content="Хроники"/>
<meta name="calibre:series_index" content="1"/>
</metadata></package>'''.encode('utf-8')

CONT = '''<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>'''.encode('utf-8')


def _make_epub(path, opf=OPF, cont=CONT):
    with zipfile.ZipFile(str(path), 'w') as z:
        z.writestr('META-INF/container.xml', cont)
        z.writestr('OEBPS/content.opf', opf)
        z.writestr('cover.jpg', b'\xff' * 10)


def test_opf_full():
    q = parse_opf_bytes(OPF)
    assert q.title_hint == 'Дюна'
    assert q.authors_hint == ('Фрэнк Герберт',)  # translator dropped
    assert q.isbn_hint == '9780306406157'
    assert q.series_hint == 'Хроники'
    assert q.series_index_hint == 1
    assert q.year_hint == 1965


def test_opf_edges():
    assert parse_opf_bytes(b'').is_empty()
    assert parse_opf_bytes(None).is_empty()
    assert parse_opf_bytes(b'junk').is_empty()
    assert parse_container_bytes(CONT) == 'OEBPS/content.opf'
    assert parse_container_bytes(b'') == ''
    assert parse_container_bytes(b'junk') == ''
    assert parse_container_bytes(None) == ''


def test_epub_file(tmp_path):
    p = tmp_path / 'd.epub'
    _make_epub(p)
    q = extract_epub_query(str(p))
    assert q.title_hint == 'Дюна'
    assert q.series_hint == 'Хроники'
    assert extract_epub_query(str(tmp_path / 'missing.epub')).is_empty()
    assert extract_epub_query('').is_empty()


def test_epub_many_resources_does_not_hide_metadata(tmp_path):
    p = tmp_path / 'many.epub'
    with zipfile.ZipFile(str(p), 'w') as z:
        z.writestr('META-INF/container.xml', CONT)
        z.writestr('OEBPS/content.opf', OPF)
        for i in range(600):
            z.writestr(f'OEBPS/Images/{i}.jpg', b'x')
    q = extract_epub_query(str(p))
    assert q.title_hint == 'Дюна'


def test_epub_no_opf(tmp_path):
    p = tmp_path / 'e.epub'
    with zipfile.ZipFile(str(p), 'w') as z:
        z.writestr('a.txt', b'hi')
    assert extract_epub_query(str(p)).is_empty()
    bad = tmp_path / 'bad.epub'
    bad.write_bytes(b'not zip')
    assert extract_epub_query(str(bad)).is_empty()
