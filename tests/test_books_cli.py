"""End-to-end: `namer` invocation renames books alongside video."""
from namer.cli import build_parser, main
from namer.core import generate_new_name, process_directory


def _fb2(title='Kнига', fn='A', ln='Б'):
    return (f'<?xml version="1.0"?><FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
            f'<description><title-info><book-title>{title}</book-title>'
            f'<author><first-name>{fn}</first-name><last-name>{ln}</last-name></author>'
            f'</title-info></description></FictionBook>').encode('utf-8')


def test_core_dispatcher_routes_books(tmp_path):
    p = tmp_path / 'a.fb2'
    p.write_bytes(_fb2('Kнига'))
    new, meta = generate_new_name(str(p))
    assert new == 'A Б - Kнига.fb2'
    assert meta['title'] == 'Kнига'
    assert meta['is_series'] is False
    assert meta['_skip'] is False


def test_core_dispatcher_skips_unresolvable_books(tmp_path):
    p = tmp_path / 'x.pdf'
    p.write_bytes(b'%PDF junk no title')
    new, meta = generate_new_name(str(p))
    assert new == 'x.pdf'
    assert meta['_skip'] is True


def test_core_dispatcher_known_author(tmp_path):
    p = tmp_path / 'Title Only.fb2'
    p.write_bytes(b'not xml')
    new, meta = generate_new_name(str(p), known_author='Known Author')
    assert new == 'Known Author - Title Only.fb2'
    assert meta['_skip'] is False


def test_process_directory_mixed_batch(tmp_path):
    (tmp_path / 'book.fb2').write_bytes(_fb2('Kнига'))
    (tmp_path / 'notes.txt').write_bytes(b'not media')
    renamed, total, errors = process_directory(str(tmp_path), dry_run=True)
    assert (renamed, total, errors) == (1, 1, 0)


def test_process_directory_real_book_rename(tmp_path):
    (tmp_path / 'book.fb2').write_bytes(_fb2('Kнига'))
    renamed, total, errors = process_directory(str(tmp_path))
    assert (renamed, total, errors) == (1, 1, 0)
    assert (tmp_path / 'A Б - Kнига.fb2').exists()


def test_cli_dry_run_with_books(tmp_path, capsys):
    (tmp_path / 'book.fb2').write_bytes(_fb2('Kнига'))
    rc = main(['-d', str(tmp_path), '-n'])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'would be renamed' in out
    assert (tmp_path / 'book.fb2').exists()  # dry-run changes nothing


def test_cli_author_override(tmp_path):
    # 1-char titles stay unusable (refuse policy) even with -a ...
    (tmp_path / 'T.fb2').write_bytes(b'junk')
    assert main(['-d', str(tmp_path), '-a', 'Au Thor']) == 0
    assert (tmp_path / 'T.fb2').exists()
    # ... while a real title gets the override author.
    (tmp_path / 'Ti.fb2').write_bytes(b'junk')
    assert main(['-d', str(tmp_path), '-a', 'Au Thor']) == 0
    assert (tmp_path / 'Au Thor - Ti.fb2').exists()


def test_parser_has_author_flag():
    args = build_parser().parse_args(['-a', 'X'])
    assert args.author == 'X'


def test_parser_has_book_enrichment_flag():
    assert build_parser().parse_args(['--enrich-books']).enrich_books is True


def test_core_dispatcher_uses_book_searchers(tmp_path):
    from namer.books.models import BookOpinion, BookRecord

    p = tmp_path / 'raw.pdf'
    p.write_bytes(b'%PDF no embedded metadata')

    def searcher(query):
        return [BookOpinion(
            'test', BookRecord(title='Canonical PDF', authors=('Author',),
                               year=2020, confidence=0.95), 0.95)]

    new, meta = generate_new_name(str(p), book_searchers=[searcher])
    assert new == 'Author - Canonical PDF (2020).pdf'
    assert meta['_skip'] is False
