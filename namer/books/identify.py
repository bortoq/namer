"""Offline book identification: extractors -> merged BookQuery -> BookIdentity.

No network here. Canonical display values arrive later via providers+fusion;
without opinions the pipeline uses a provisional local record (see naming).
"""
from __future__ import annotations

import os
from typing import Optional

from namer.books.detect import book_kind
from namer.books.djvu import extract_djvu_query
from namer.books.epub import extract_epub_query
from namer.books.fb2 import extract_fb2_query, extract_fb2zip_query
from namer.books.filename import parse_book_filename
from namer.books.models import BookIdentity, BookQuery, ReadBudget
from namer.books.pdf import extract_pdf_query


def merge_queries(primary: BookQuery, fallback: BookQuery) -> BookQuery:
    """Fill empty fields of *primary* from *fallback*. Never raises."""
    try:
        if not isinstance(primary, BookQuery):
            return fallback if isinstance(fallback, BookQuery) else BookQuery()
        if not isinstance(fallback, BookQuery):
            return primary
        authors = primary.authors_hint or fallback.authors_hint or ()
        return BookQuery(
            title_hint=primary.title_hint or fallback.title_hint,
            authors_hint=authors,
            series_hint=primary.series_hint or fallback.series_hint,
            series_index_hint=(primary.series_index_hint
                               if primary.series_index_hint is not None
                               else fallback.series_index_hint),
            isbn_hint=primary.isbn_hint or fallback.isbn_hint,
            lang_hint=primary.lang_hint or fallback.lang_hint,
            year_hint=(primary.year_hint
                       if primary.year_hint is not None else fallback.year_hint),
            fingerprint=primary.fingerprint or fallback.fingerprint,
            source_format=primary.source_format or fallback.source_format,
        )
    except Exception:
        return primary if isinstance(primary, BookQuery) else BookQuery()


def build_query(path: str, known_title: str = '',
                known_author: str = '',
                budget: Optional[ReadBudget] = None) -> BookQuery:
    """Dispatch by kind, merge embedded + filename + known_*. Never raises."""
    try:
        b = budget or ReadBudget()
        if not isinstance(path, str) or not path:
            return BookQuery()
        kind = book_kind(path)
        if kind is None:
            return BookQuery()
        try:
            if kind == 'fb2':
                embedded = extract_fb2_query(path, b)
            elif kind == 'fb2.zip':
                embedded = extract_fb2zip_query(path, b)
            elif kind == 'epub':
                embedded = extract_epub_query(path, b)
            elif kind == 'pdf':
                embedded = extract_pdf_query(path, b)
            elif kind == 'djvu':
                embedded = extract_djvu_query(path, b)
            else:
                embedded = BookQuery(source_format=kind)
        except Exception:
            embedded = BookQuery(source_format=kind)
        try:
            fn = parse_book_filename(os.path.basename(path), kind)
        except Exception:
            fn = BookQuery(source_format=kind)
        q = merge_queries(embedded, fn)
        # explicit user overrides win for title/authors
        try:
            kt = (known_title or '').strip()[:300]
            ka = (known_author or '').strip()[:120]
        except Exception:
            kt, ka = '', ''
        if kt or ka:
            q = BookQuery(
                title_hint=kt or q.title_hint,
                authors_hint=(ka,) if ka else q.authors_hint,
                series_hint=q.series_hint,
                series_index_hint=q.series_index_hint,
                isbn_hint=q.isbn_hint, lang_hint=q.lang_hint,
                year_hint=q.year_hint, fingerprint=q.fingerprint,
                source_format=q.source_format or kind,
            )
        if not q.source_format:
            q = BookQuery(
                title_hint=q.title_hint, authors_hint=q.authors_hint,
                series_hint=q.series_hint, series_index_hint=q.series_index_hint,
                isbn_hint=q.isbn_hint, lang_hint=q.lang_hint,
                year_hint=q.year_hint, fingerprint=q.fingerprint,
                source_format=kind)
        return q
    except Exception:
        return BookQuery()


def identify_book(path: str, known_title: str = '',
                  known_author: str = '',
                  budget: Optional[ReadBudget] = None) -> BookIdentity:
    """Offline identity. identified needs title>=2 or ISBN. Never raises."""
    try:
        if not isinstance(path, str) or not path:
            return BookIdentity(status='unresolved', warnings=['empty path'])
        kind = book_kind(path)
        if kind is None:
            return BookIdentity(status='unresolved', warnings=['unsupported extension'])
        q = build_query(path, known_title, known_author, budget)
        warnings: list = []
        evidence: list = []
        try:
            if q.title_hint:
                evidence.append(f'{"embedded" if q.source_format else "filename"}:title={q.title_hint[:80]}')
            if q.authors_hint:
                evidence.append(f'authors={", ".join(q.authors_hint)[:80]}')
            if q.isbn_hint:
                evidence.append(f'isbn={q.isbn_hint}')
        except Exception:
            pass
        title = (q.title_hint or '').strip()
        if q.has_isbn() and (len(title) >= 2 or not title):
            # ISBN alone is enough to query the network; offline status is
            # identified only when a title exists, else ambiguous (needs net).
            status = 'identified' if len(title) >= 2 else 'ambiguous'
            if len(title) < 2:
                warnings.append('isbn without title — network lookup required')
        elif len(title) >= 2:
            status = 'identified'
        else:
            status = 'unresolved'
            warnings.append('no usable title — file left in place')
        return BookIdentity(
            status=status,
            title=title,
            authors=list(q.authors_hint or ()),
            series=(q.series_hint or ''),
            series_index=q.series_index_hint,
            year=q.year_hint,
            language=(q.lang_hint or ''),
            isbn=(q.isbn_hint or ''),
            ext=kind,
            query=q,
            record=None,
            warnings=warnings,
            evidence=evidence,
        )
    except Exception:
        return BookIdentity(status='unresolved', warnings=['internal error'])
