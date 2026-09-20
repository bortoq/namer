"""Namer configuration — single source of truth for all tunables (video + books).

Values come from ``config.ini`` (repo root, or ``$NAMER_CONFIG``) with code
defaults as fallback. A missing/unreadable/malformed file is never an error:
the offending value — or the whole file — falls back to the default below.

Only stdlib is used; this module must not import anything from ``namer``.
"""

import configparser
import os

# ── Code defaults (authoritative fallback) ───────────────────────────────
_DEFAULT_VIDEO_EXTENSIONS = frozenset({
    '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm',
    '.m4v', '.m2ts', '.ts', '.mpg', '.mpeg', '.vob', '.iso',
})
_DEFAULT_BOOK_EXTENSIONS = frozenset({
    '.fb2', '.fb2.zip', '.epub', '.pdf', '.djvu',
})
_DEFAULT_TEMPLATE_MOVIE = '{title} ({year}) {mod}.{ext}'
_DEFAULT_TEMPLATE_SERIES = '{season:02d}.{episode:02d}. {ep_title}.{ext}'
_DEFAULT_TEMPLATE_BOOK = '{author} - {title} ({year}).{ext}'
_DEFAULT_TEMPLATE_BOOK_SERIES = (
    '{author} - {series} - {series_index:02d} - {title}.{ext}'
)
_DEFAULT_MAX_CONCURRENT_FILES = 4
_DEFAULT_MAX_UNCOMPRESSED_MB = 16
_DEFAULT_MAX_ENTRIES = 512
_DEFAULT_MAX_XML_KB = 2048
_DEFAULT_TIMEOUT_SEC = 5.0
_DEFAULT_INVALID = '\\/:*?"<>|'
_DEFAULT_REPLACEMENTS = {
    '?': '？',
    '*': '×',
    ':': '∶',
    '/': '∕',
    '\\': '∖',
    '"': ('“', '”'),
    '<': '‹',
    '>': '›',
}
_CONTROL_CHARS = frozenset(chr(c) for c in range(0x20))

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.environ.get('NAMER_CONFIG') or os.path.join(
    _REPO_ROOT, 'config.ini')


def _read_ini(path: str):
    """Return a ConfigParser or None when missing/unreadable/broken."""
    try:
        if not isinstance(path, str) or not path:
            return None
        if not os.path.isfile(path):
            return None
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.read(path, encoding='utf-8')
        return cfg
    except Exception:
        return None


def _get(cfg, section: str, option: str, fallback: str = '') -> str:
    """Guarded string fetch; fallback on any problem. Never raises."""
    try:
        if cfg is None:
            return fallback
        value = cfg.get(section, option, fallback=fallback)
        return value if isinstance(value, str) else fallback
    except Exception:
        return fallback


def parse_extensions(raw: str, default: frozenset) -> frozenset:
    """Comma-separated extensions -> frozenset. Default on garbage."""
    try:
        if not isinstance(raw, str) or not raw.strip():
            return default
        parts = frozenset(p.strip().lower() for p in raw.split(','))
        parts = frozenset(p for p in parts if p)
        return parts if parts else default
    except Exception:
        return default


def parse_positive_int(raw: str, default: int) -> int:
    """Guarded int > 0, else default."""
    try:
        value = int(str(raw).strip())
        return value if value > 0 else default
    except Exception:
        return default


def parse_positive_float(raw: str, default: float) -> float:
    """Guarded float > 0, else default."""
    try:
        value = float(str(raw).strip())
        return value if value > 0 else default
    except Exception:
        return default


def parse_replacements(raw: str, default: dict) -> dict:
    """'old:new; ...' pairs -> {bad: good|'open|close'}. Default on garbage.

    The key is always the FIRST character, followed by a ':' separator, so
    ':' itself can be a key ('::∶'). A '|' in the replacement means an
    (open, close) pair.
    """
    try:
        if not isinstance(raw, str) or not raw.strip():
            return dict(default)
        out: dict = {}
        for chunk in raw.split(';'):
            chunk = chunk.strip()
            if len(chunk) < 3 or chunk[0] in ' |' or chunk[1] != ':':
                continue
            bad, good = chunk[0], chunk[2:].strip()
            if not good:
                continue
            out[bad] = tuple(good.split('|', 1)) if '|' in good else good
        return out if out else dict(default)
    except Exception:
        return dict(default)


def load_config(ini_path: str = '') -> dict:
    """Parse *ini_path* (default: config.ini) into plain values. Never raises.

    Pure apart from file read: safe entry point for tests. Every value falls
    back to the code default independently, so a half-broken file still
    contributes its valid half.
    """
    try:
        cfg = _read_ini(ini_path or CONFIG_PATH)
        replacements = parse_replacements(
            _get(cfg, 'chars', 'replacements', ''), _DEFAULT_REPLACEMENTS)
        invalid = _get(cfg, 'chars', 'invalid', _DEFAULT_INVALID)
        if not isinstance(invalid, str) or not invalid:
            invalid = _DEFAULT_INVALID
        # Control chars are always forbidden, even if the file omits them.
        invalid_set = frozenset(invalid) | _CONTROL_CHARS
        return {
            'video_extensions': parse_extensions(
                _get(cfg, 'video', 'extensions', ''),
                _DEFAULT_VIDEO_EXTENSIONS),
            'book_extensions': parse_extensions(
                _get(cfg, 'books', 'extensions', ''),
                _DEFAULT_BOOK_EXTENSIONS),
            'template_movie': (
                _get(cfg, 'video', 'template_movie', '') or _DEFAULT_TEMPLATE_MOVIE),
            'template_series': (
                _get(cfg, 'video', 'template_series', '') or _DEFAULT_TEMPLATE_SERIES),
            'template_book': (
                _get(cfg, 'books', 'template_book', '') or _DEFAULT_TEMPLATE_BOOK),
            'template_book_series': (
                _get(cfg, 'books', 'template_book_series', '')
                or _DEFAULT_TEMPLATE_BOOK_SERIES),
            'max_concurrent_files': parse_positive_int(
                _get(cfg, 'rename', 'max_concurrent_files', ''),
                _DEFAULT_MAX_CONCURRENT_FILES),
            'max_uncompressed_mb': parse_positive_int(
                _get(cfg, 'limits', 'max_uncompressed_mb', ''),
                _DEFAULT_MAX_UNCOMPRESSED_MB),
            'max_entries': parse_positive_int(
                _get(cfg, 'limits', 'max_entries', ''),
                _DEFAULT_MAX_ENTRIES),
            'max_xml_kb': parse_positive_int(
                _get(cfg, 'limits', 'max_xml_kb', ''),
                _DEFAULT_MAX_XML_KB),
            'timeout_sec': parse_positive_float(
                _get(cfg, 'limits', 'timeout_sec', ''),
                _DEFAULT_TIMEOUT_SEC),
            'invalid_chars': invalid_set,
            'invalid_char_replacements': replacements,
        }
    except Exception:
        return load_defaults()


def load_defaults() -> dict:
    """Code defaults without touching the filesystem. Never raises."""
    return {
        'video_extensions': _DEFAULT_VIDEO_EXTENSIONS,
        'book_extensions': _DEFAULT_BOOK_EXTENSIONS,
        'template_movie': _DEFAULT_TEMPLATE_MOVIE,
        'template_series': _DEFAULT_TEMPLATE_SERIES,
        'template_book': _DEFAULT_TEMPLATE_BOOK,
        'template_book_series': _DEFAULT_TEMPLATE_BOOK_SERIES,
        'max_concurrent_files': _DEFAULT_MAX_CONCURRENT_FILES,
        'max_uncompressed_mb': _DEFAULT_MAX_UNCOMPRESSED_MB,
        'max_entries': _DEFAULT_MAX_ENTRIES,
        'max_xml_kb': _DEFAULT_MAX_XML_KB,
        'timeout_sec': _DEFAULT_TIMEOUT_SEC,
        'invalid_chars': frozenset(_DEFAULT_INVALID) | _CONTROL_CHARS,
        'invalid_char_replacements': dict(_DEFAULT_REPLACEMENTS),
    }


# ── Public constants (read once at import) ────────────────────────────────
_config = load_config()

# ── Video file extensions ────────────────────────────────────────────────
VIDEO_EXTENSIONS = _config['video_extensions']

# ── Book file extensions ─────────────────────────────────────────────────
BOOK_EXTENSIONS = _config['book_extensions']

# ── Rename templates ─────────────────────────────────────────────────────
# These are Python format-strings. Available placeholders:
#
#   Video: {title} {dot_title} {season} {episode} {ext} {year} {quality}
#          {dot_quality} {resolution} {source} {codec} {audio} {hdr} {mod}
#          {ep_title} {audio_lang} {sub_lang} {channels}
#   Books: {author} {authors} {title} {series} {series_index} {year}
#          {lang} {language} {isbn} {publisher} {ext}
#
TEMPLATE_MOVIE = _config['template_movie']
TEMPLATE_SERIES = _config['template_series']
TEMPLATE_BOOK = _config['template_book']
TEMPLATE_BOOK_SERIES = _config['template_book_series']

# ── Concurrency ──────────────────────────────────────────────────────────
# How many files are processed in parallel.  Lookups are I/O-bound
# (network requests with timeouts), so a handful of workers hides
# per-request latency; keep it small to stay polite to the APIs.
MAX_CONCURRENT_FILES = _config['max_concurrent_files']

# ── Parser safety budgets (books) ────────────────────────────────────────
BOOK_MAX_UNCOMPRESSED_MB = _config['max_uncompressed_mb']
BOOK_MAX_ENTRIES = _config['max_entries']
BOOK_MAX_XML_KB = _config['max_xml_kb']
BOOK_TIMEOUT_SEC = _config['timeout_sec']

# ── Invalid filename characters ──────────────────────────────────────────
# Characters forbidden in filenames (Windows NTFS/FAT/exFAT and POSIX).
INVALID_CHARS = _config['invalid_chars']

# Unicode lookalikes for forbidden characters, so a readable name survives
# instead of being mangled into underscores.  A value may be:
#   - a string: the character is replaced 1:1;
#   - an (open, close) pair: the first occurrence becomes *open*, the
#     second *close*, and so on — paired quotes come out as “...” rather
#     than “...“.
# Forbidden characters without an entry fall back to '_' (see core.py).
#
#   forbidden  →  replacement                  example
#   ?          →  ？ fullwidth question mark    Lost S02E21 - ？.mp4
#   *          →  × heavy asterisk              Сборник ×××.mp3
#   :          →  ∶ ratio sign                  Лекция 1∶ Введение.mkv
#   /          →  ∕ division slash              Проект 2026∕07.docx
#   \          →  ∖ set minus                   Папка ∖ Архив.zip
#   "          →  “ ” smart double quotes       Фильм “Матрица”.mkv
#   <          →  ‹ single left angle           Эпизод ‹Режиссерская версия›.mkv
#   >          →  › single right angle
INVALID_CHAR_REPLACEMENTS = _config['invalid_char_replacements']

del _config
