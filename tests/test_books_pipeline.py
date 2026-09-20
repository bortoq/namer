"""Pipeline: batch dry-run + real rename, no clobber."""
from namer.books.pipeline import process_books_directory


def _fb2(title='Книга', author_fn='А', author_ln='Б'):
    return (f'<?xml version="1.0"?><FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
            f'<description><title-info><book-title>{title}</book-title>'
            f'<author><first-name>{author_fn}</first-name><last-name>{author_ln}</last-name></author>'
            f'</title-info></description></FictionBook>').encode('utf-8')


def test_dry_run(tmp_path):
    (tmp_path / 'a.fb2').write_bytes(_fb2('Книга1'))
    (tmp_path / 'b.epub').write_bytes(b'junk-epub')
    renamed, total, errors = process_books_directory(str(tmp_path), dry_run=True)
    assert total == 2
    assert renamed == 1  # only fb2 with title
    assert errors == 0
    assert (tmp_path / 'a.fb2').exists()  # dry-run changes nothing


def test_real_rename_and_idempotent(tmp_path):
    (tmp_path / 'a.fb2').write_bytes(_fb2('Книга'))
    renamed, total, errors = process_books_directory(str(tmp_path), dry_run=False)
    assert (renamed, total, errors) == (1, 1, 0)
    assert (tmp_path / 'А Б - Книга.fb2').exists()
    renamed2, total2, _ = process_books_directory(str(tmp_path), dry_run=False)
    assert renamed2 == 0 and total2 == 1  # already named


def test_empty_and_missing():
    assert process_books_directory('/nonexistent-xyz') == (0, 0, 0)
    assert process_books_directory('') == (0, 0, 0)
    assert process_books_directory(None) == (0, 0, 0)
