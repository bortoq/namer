"""Book filename heuristic -> BookQuery hints. Pure offline, never raises."""
from __future__ import annotations

import os
import re
from typing import Optional

from namer.books.detect import find_isbns_in_text
from namer.books.models import BookQuery

_YEAR_RE = re.compile(r'(?<![0-9])((?:19|20)\d{2})(?![0-9])')
_BRACKET_AUTHOR_RE = re.compile(r'^\s*\[(?P<author>[^\[\]]{2,80})\]\s*(?P<title>.+?)\s*$')
_SERIES_NUM_RE = re.compile(
    r'^(?P<name>.*?)\s*(?:\(?(?:кн|т|том|ч|часть|vol|volume|book|bd|#)\.?\)?\s*)?#?(?P<num>\d{1,3})\s*$',
    re.IGNORECASE,
)
_EDITION_TAGS = re.compile(
    r'\b(?:readli\.net|litres|litmir|flibusta|sampler|ознакомительный\s*фрагмент|fb2|epub|pdf|djvu)\b',
    re.IGNORECASE,
)
_FILE_ID_RE = re.compile(r'[._ -]\d{5,}$')


def _strip_book_ext(basename: str) -> str:
    low = basename.lower()
    if low.endswith('.fb2.zip'):
        return basename[: -len('.fb2.zip')]
    root, _ = os.path.splitext(basename)
    return root


_PURE_INDEX_RE = re.compile(
    r'^(?:#|(?:\u2116)|(?:кн|т|том|ч|часть|vol|volume|book|bd)\.?)?\s*#?(\d{1,3})\s*$',
    re.IGNORECASE,
)


def parse_series_index_token(token: str) -> Optional[int]:
    """'02', '#2', 'т.2', 'Vol 3' -> int. None when token carries a series name.

    Only pure number/index tokens qualify here; 'Серия 03' must return None
    so the caller can split it into series+index via _SERIES_NUM_RE.
    """
    if not isinstance(token, str) or not token:
        return None
    t = token.strip()
    if not t:
        return None
    # a series name followed by a number is NOT a pure index token
    if re.search(r'[A-Za-zА-Яа-яЁё]', t):
        # allow only known prefix words + number ('Vol 3', 'т.2')
        m = _PURE_INDEX_RE.match(t)
        if not m:
            return None
        prefix = t[:m.start(1)].strip()
        if prefix and not re.fullmatch(
                r'(?:#|\u2116|кн\.?|т\.?|том|ч\.?|часть|vol\.?|volume|book|bd)',
                prefix, re.IGNORECASE):
            return None
        try:
            return int(m.group(1))
        except ValueError:
            return None
    m = re.fullmatch(r'#?(\d{1,3})', t)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def _clean_part(part: str) -> str:
    if not isinstance(part, str):
        return ''
    p = part.replace('_', ' ')
    p = _EDITION_TAGS.sub('', p)
    p = re.sub(r'\s+', ' ', p).strip(' .-')
    return p


def parse_book_filename(basename: str, source_format: str = '') -> BookQuery:
    """Parse 'Author - Series - 02 - Title (2010).fb2' -> hints. Never raises."""
    try:
        if not isinstance(basename, str) or not basename.strip():
            return BookQuery(source_format=source_format or '')
        stem = _strip_book_ext(basename.strip())
        # ISBN anywhere in the name is the strongest hint
        isbns = find_isbns_in_text(stem)
        isbn = isbns[0] if isbns else ''
        # year = last 19xx/20xx
        year = None
        try:
            years = _YEAR_RE.findall(stem)
            if years:
                year = int(years[-1])
        except (ValueError, IndexError):
            year = None
        name = _YEAR_RE.sub(' ', stem)
        # Repository/download IDs are common in otherwise useful PDF names
        # (``...design.834478``).  They are not part of the title and make
        # online catalogue matching unnecessarily brittle.
        name = _FILE_ID_RE.sub('', name)
        name = re.sub(r'\[.*?\]', ' ', name) if '[' in name and ']' in name and not _BRACKET_AUTHOR_RE.match(name) else name
        name = re.sub(r'\s+', ' ', name.replace('_', ' ')).strip(' .-')
        if not name:
            # AUDIT: numeric titles ('1984') were eaten by the year pattern.
            # Fall back to the raw stem so a year-like title survives.
            fb = _clean_part(stem)
            if fb:
                return BookQuery(title_hint=fb, isbn_hint=isbn, year_hint=year,
                                 source_format=source_format or '')
            return BookQuery(isbn_hint=isbn, year_hint=year, source_format=source_format or '')
        # [Author] Title
        m = _BRACKET_AUTHOR_RE.match(name)
        if m:
            author = _clean_part(m.group('author'))
            title = _clean_part(m.group('title'))
            return BookQuery(
                title_hint=title, authors_hint=(author,) if author else (),
                isbn_hint=isbn, year_hint=year, source_format=source_format or '')
        parts = [_clean_part(p) for p in re.split(r'\s+-\s+', name)]
        parts = [p for p in parts if p]
        if not parts:
            return BookQuery(isbn_hint=isbn, year_hint=year, source_format=source_format or '')
        if len(parts) >= 4:
            idx = parse_series_index_token(parts[2])
            if idx is not None:
                return BookQuery(
                    title_hint=' - '.join(parts[3:]), authors_hint=(parts[0],),
                    series_hint=parts[1], series_index_hint=idx,
                    isbn_hint=isbn, year_hint=year, source_format=source_format or '')
            return BookQuery(
                title_hint=' - '.join(parts[1:]), authors_hint=(parts[0],),
                isbn_hint=isbn, year_hint=year, source_format=source_format or '')
        if len(parts) == 3:
            idx = parse_series_index_token(parts[1])
            if idx is not None:
                # 'Author - 02 - Title': series unknown, index known
                return BookQuery(
                    title_hint=parts[2], authors_hint=(parts[0],),
                    series_index_hint=idx,
                    isbn_hint=isbn, year_hint=year, source_format=source_format or '')
            m2 = _SERIES_NUM_RE.match(parts[1])
            if m2 and m2.group('name').strip():
                try:
                    return BookQuery(
                        title_hint=parts[2], authors_hint=(parts[0],),
                        series_hint=m2.group('name').strip(),
                        series_index_hint=int(m2.group('num')),
                        isbn_hint=isbn, year_hint=year, source_format=source_format or '')
                except ValueError:
                    pass
            return BookQuery(
                title_hint=' - '.join(parts[1:]), authors_hint=(parts[0],),
                isbn_hint=isbn, year_hint=year, source_format=source_format or '')
        if len(parts) == 2:
            idx = parse_series_index_token(parts[0])
            if idx is not None:
                return BookQuery(
                    title_hint=parts[1], series_index_hint=idx,
                    isbn_hint=isbn, year_hint=year, source_format=source_format or '')
            return BookQuery(
                title_hint=parts[1], authors_hint=(parts[0],),
                isbn_hint=isbn, year_hint=year, source_format=source_format or '')
        return BookQuery(
            title_hint=parts[0], isbn_hint=isbn, year_hint=year,
            source_format=source_format or '')
    except Exception:
        return BookQuery(source_format=source_format if isinstance(source_format, str) else '')
