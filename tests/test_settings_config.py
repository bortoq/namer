"""Single config source: config.ini + namer/settings.py defaults."""
import os

from namer import settings
from namer.settings import (
    load_config,
    load_defaults,
    parse_extensions,
    parse_positive_float,
    parse_positive_int,
    parse_replacements,
)


def test_module_defaults_video():
    assert '.mkv' in settings.VIDEO_EXTENSIONS
    assert '.iso' in settings.VIDEO_EXTENSIONS
    assert len(settings.VIDEO_EXTENSIONS) == 14
    assert settings.TEMPLATE_MOVIE == '{title} ({year}) {mod}.{ext}'
    assert settings.TEMPLATE_SERIES == '{season:02d}.{episode:02d}. {ep_title}.{ext}'
    assert settings.MAX_CONCURRENT_FILES == 4


def test_module_defaults_books():
    assert settings.BOOK_EXTENSIONS == {'.fb2', '.fb2.zip', '.epub', '.pdf', '.djvu'}
    assert settings.TEMPLATE_BOOK == '{author} - {title} ({year}).{ext}'
    assert settings.TEMPLATE_BOOK_SERIES == (
        '{author} - {series} - {series_index:02d} - {title}.{ext}')
    assert settings.BOOK_MAX_UNCOMPRESSED_MB == 16
    assert settings.BOOK_MAX_ENTRIES == 512
    assert settings.BOOK_MAX_XML_KB == 2048
    assert settings.BOOK_TIMEOUT_SEC == 5.0


def test_module_defaults_chars():
    for bad in '\\/:*?"<>|':
        assert bad in settings.INVALID_CHARS
    assert '\x00' in settings.INVALID_CHARS and '\x1f' in settings.INVALID_CHARS
    assert settings.INVALID_CHAR_REPLACEMENTS['?'] == '？'
    assert settings.INVALID_CHAR_REPLACEMENTS['"'] == ('“', '”')


def test_repo_config_matches_code_defaults():
    # config.ini ships values identical to code defaults: behaviour unchanged.
    assert load_config() == load_defaults()


def test_missing_file_falls_back(tmp_path):
    cfg = load_config(str(tmp_path / 'nope.ini'))
    assert cfg == load_defaults()


def test_broken_file_falls_back(tmp_path):
    p = tmp_path / 'bad.ini'
    p.write_bytes(b'\x00\xff not [ini \x00')
    assert load_config(str(p)) == load_defaults()
    p.write_text('[rename]\nmax_concurrent_files = nope\n[limits]\ntimeout_sec = -3\n')
    cfg = load_config(str(p))
    assert cfg['max_concurrent_files'] == 4
    assert cfg['timeout_sec'] == 5.0
    # valid half of a half-broken file still applies
    p.write_text('[rename]\nmax_concurrent_files = 8\n[limits]\ntimeout_sec = nope\n')
    cfg = load_config(str(p))
    assert (cfg['max_concurrent_files'], cfg['timeout_sec']) == (8, 5.0)


def test_custom_override(tmp_path):
    p = tmp_path / 'c.ini'
    p.write_text(
        '[video]\nextensions = .mkv, .MP4\ntemplate_movie = {title}.{ext}\n'
        '[books]\nextensions = .fb2\n'
        '[rename]\nmax_concurrent_files = 2\n'
        '[chars]\nreplacements = ?:Q\n')
    cfg = load_config(str(p))
    assert cfg['video_extensions'] == {'.mkv', '.mp4'}
    assert cfg['book_extensions'] == {'.fb2'}
    assert cfg['template_movie'] == '{title}.{ext}'
    assert cfg['max_concurrent_files'] == 2
    assert cfg['invalid_char_replacements'] == {'?': 'Q'}
    # untouched sections keep defaults
    assert cfg['template_series'] == settings.TEMPLATE_SERIES


def test_parsers_edges():
    d = frozenset({'.x'})
    assert parse_extensions('', d) is d
    assert parse_extensions(None, d) is d
    assert parse_extensions(' , ', d) is d
    assert parse_extensions('.FB2.ZIP, .pdf', d) == {'.fb2.zip', '.pdf'}
    assert parse_positive_int('0', 4) == 4
    assert parse_positive_int('-2', 4) == 4
    assert parse_positive_int('abc', 4) == 4
    assert parse_positive_int(None, 4) == 4
    assert parse_positive_int(' 7 ', 4) == 7
    assert parse_positive_float('0', 1.5) == 1.5
    assert parse_positive_float('2.5', 1.5) == 2.5
    assert parse_positive_float('xx', 1.5) == 1.5
    r = parse_replacements('::X; a:b; bad; toolong:k; ":Q', {'k': 'v'})
    assert r == {':': 'X', 'a': 'b', '"': 'Q'}
    assert parse_replacements('', {'k': 'v'}) == {'k': 'v'}
    assert parse_replacements(None, {'k': 'v'}) == {'k': 'v'}


def test_books_reexport_books_settings():
    from namer.books.detect import BOOK_EXTENSIONS
    from namer.books.naming import TEMPLATE_BOOK, TEMPLATE_BOOK_SERIES
    assert BOOK_EXTENSIONS is settings.BOOK_EXTENSIONS
    assert TEMPLATE_BOOK is settings.TEMPLATE_BOOK
    assert TEMPLATE_BOOK_SERIES is settings.TEMPLATE_BOOK_SERIES


def test_read_budget_consistent_with_settings():
    from namer.books.models import ReadBudget
    b = ReadBudget()
    assert b.max_uncompressed == settings.BOOK_MAX_UNCOMPRESSED_MB * 1024 * 1024
    assert b.max_entries == settings.BOOK_MAX_ENTRIES
    assert b.max_xml_bytes == settings.BOOK_MAX_XML_KB * 1024
    assert b.timeout_sec == settings.BOOK_TIMEOUT_SEC


def test_config_path_resolution():
    assert settings.CONFIG_PATH.endswith('config.ini')
    assert os.path.isfile(settings.CONFIG_PATH)
