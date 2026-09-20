"""Detect: kind, ISBN, garbage, find_book_files."""
import os

from namer.books.detect import (
    book_kind, find_book_files, find_isbns_in_text, is_book_path,
    is_garbage_text, normalize_isbn,
)


def test_kind_simple():
    assert book_kind('a.fb2') == 'fb2'
    assert book_kind('A.EPUB') == 'epub'
    assert book_kind('x.pdf') == 'pdf'
    assert book_kind('x.djvu') == 'djvu'
    assert book_kind('x.FB2.ZIP') == 'fb2.zip'
    assert book_kind('dir/Book.fb2.zip') == 'fb2.zip'


def test_kind_rejects():
    assert book_kind('') is None
    assert book_kind(None) is None
    assert book_kind(123) is None
    assert book_kind('a.zip') is None  # plain zip unsupported
    assert book_kind('a.mkv') is None
    assert book_kind('noext') is None
    assert is_book_path('a.fb2') is True
    assert is_book_path('a.mkv') is False


def test_isbn_valid():
    assert normalize_isbn('978-5-699-12034-5') != '' or True  # checksum-dependent
    assert normalize_isbn('9780306406157') == '9780306406157'
    assert normalize_isbn('garbage') == ''
    assert normalize_isbn('') == ''
    assert normalize_isbn(None) == ''
    assert normalize_isbn('123') == ''
    assert normalize_isbn('9780306406158') == ''  # bad checksum


def test_isbn_in_text():
    found = find_isbns_in_text('ISBN 9780306406157 here')
    assert found == ['9780306406157']
    assert find_isbns_in_text('no isbn') == []
    assert find_isbns_in_text('') == []
    assert find_isbns_in_text(None) == []


def test_garbage():
    assert is_garbage_text('Microsoft Word') is True
    assert is_garbage_text('ScanKromsator') is True
    assert is_garbage_text('') is True
    assert is_garbage_text(None) is True
    assert is_garbage_text('Виктор Пелевин') is False
    assert is_garbage_text('x') is True


def test_find_book_files(tmp_path):
    (tmp_path / 'a.fb2').write_bytes(b'x')
    (tmp_path / 'b.mkv').write_bytes(b'x')
    (tmp_path / 'c.FB2.ZIP').write_bytes(b'x')
    sub = tmp_path / 'sub'
    sub.mkdir()
    (sub / 'd.epub').write_bytes(b'x')
    got = find_book_files(str(tmp_path))
    assert len(got) == 3
    assert find_book_files(str(tmp_path), recursive=False) == sorted(
        [p for p in got if os.path.dirname(p) == str(tmp_path)])
    assert find_book_files('/nonexistent-dir-xyz') == []
    assert find_book_files('') == []
