"""Book filename rendering from BookRecord. Pure except sanitize import."""
from __future__ import annotations

import os
import re
import string
from typing import Optional

from namer.books.fusion import candidate_score, fuse_opinions
from namer.books.identify import identify_book
from namer.books.models import BookIdentity, BookRecord
from namer.settings import TEMPLATE_BOOK, TEMPLATE_BOOK_SERIES

_BOOK_FIELDS = frozenset({
    'author', 'authors', 'title', 'series', 'series_index',
    'year', 'lang', 'language', 'isbn', 'publisher', 'ext',
})


def template_uses(template: str, field: str) -> bool:
    try:
        if not isinstance(template, str) or not isinstance(field, str):
            return False
        for _, name, _, _ in string.Formatter().parse(template):
            if name == field:
                return True
        return False
    except Exception:
        return False


def _sanitize(name: str) -> str:
    try:
        from namer.core import _sanitize_filename
        return _sanitize_filename(name)
    except Exception:
        return re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', name).strip('. ')


def record_to_meta(record: BookRecord, ext: str) -> dict:
    """BookRecord -> flat template dict. Never raises."""
    try:
        authors = list(record.authors or [])
        author = authors[0] if authors else ''
        return {
            'author': author,
            'authors': ', '.join(authors),
            'title': record.title or '',
            'series': record.series or '',
            'series_index': record.series_index if record.series_index is not None else 0,
            'year': record.year if record.year is not None else 0,
            'lang': record.language or '',
            'language': record.language or '',
            'isbn': record.isbn13 or '',
            'publisher': record.publisher or '',
            'ext': ext or '',
        }
    except Exception:
        return {'author': '', 'authors': '', 'title': '', 'series': '',
                'series_index': 0, 'year': 0, 'lang': '', 'language': '',
                'isbn': '', 'publisher': '', 'ext': ext or ''}


def _cleanup_rendered(name: str) -> str:
    try:
        name = re.sub(r'\s*\[\s*\]\s*', '', name)
        name = re.sub(r'\s*\(\s*\)\s*', '', name)
        name = re.sub(r'\s*\(\s*0\s*\)\s*', '', name)
        # AUDIT-DEMO: empty {author} leaves a dangling leading dash
        # (' - manual.epub'); strip separator artifacts at the edges.
        name = re.sub(r'^\s*-\s*', '', name)
        name = re.sub(r'\s*-\s*$', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        name = re.sub(r'[. ]$', '', name)
        return _sanitize(name)
    except Exception:
        return ''


def render_book_name(record: BookRecord, ext: str, pattern: str = '') -> Optional[str]:
    """Render template from record. None when invalid/missing. Never raises."""
    try:
        if not isinstance(record, BookRecord):
            return None
        title = (record.title or '').strip()
        if len(title) < 2:
            return None
        template = pattern.strip() if isinstance(pattern, str) and pattern.strip() else ''
        if not template:
            if (record.series or '').strip() and record.series_index is not None:
                template = TEMPLATE_BOOK_SERIES
            else:
                template = TEMPLATE_BOOK
        # unknown placeholder -> refuse (do not guess)
        try:
            used = {name for _, name, _, _ in string.Formatter().parse(template) if name}
        except ValueError:
            return None
        if not used.issubset(_BOOK_FIELDS):
            return None
        if template_uses(template, 'series_index') and record.series_index is None:
            return None
        if template_uses(template, 'series') and not (record.series or '').strip():
            return None
        if template_uses(template, 'isbn') and not (record.isbn13 or '').strip():
            return None
        meta = record_to_meta(record, ext)
        try:
            rendered = template.format(**meta)
        except (KeyError, IndexError, ValueError):
            return None
        rendered = _cleanup_rendered(rendered)
        if not rendered or '.' not in os.path.basename(rendered):
            return None
        return rendered
    except Exception:
        return None


def provisional_record(identity: BookIdentity) -> Optional[BookRecord]:
    """Local-only record from offline hints, provenance 'local'. Never raises."""
    try:
        if not isinstance(identity, BookIdentity) or identity.query is None:
            return None
        q = identity.query
        title = (q.title_hint or '').strip()
        if len(title) < 2 and not q.has_isbn():
            return None
        if len(title) < 2:
            return None
        return BookRecord(
            title=title, authors=tuple(q.authors_hint or ()),
            series=q.series_hint or '', series_index=q.series_index_hint,
            year=q.year_hint, language=q.lang_hint or '',
            isbn13=q.isbn_hint or '', provider='local', provider_id='',
            confidence=0.9 if q.has_isbn() else 0.6)
    except Exception:
        return None


def generate_book_name(file_path: str, pattern: str = '',
                       known_title: str = '', known_author: str = '',
                       opinions: Optional[list] = None,
                       allow_local: bool = True,
                       identity: Optional[BookIdentity] = None) -> tuple:
    """Generate new basename for a book file.

    Network opinions (when given) override local hints via fusion.
    Without opinions, a provisional local record is used (offline mode).
    Returns (new_basename, BookIdentity). Never raises.
    """
    try:
        if not isinstance(file_path, str) or not file_path:
            return '', BookIdentity(status='unresolved', warnings=['empty path'])
        basename = os.path.basename(file_path)
        # The caller may already have parsed the file to query catalogues.
        # Reuse that exact identity: PDF OCR is expensive and must run once.
        ident = identity if isinstance(identity, BookIdentity) else identify_book(
            file_path, known_title, known_author)
        record: Optional[BookRecord] = None
        try:
            fused = fuse_opinions(opinions, ident.query) if opinions else None
        except Exception:
            fused = None
        if fused is not None and len((fused.title or '').strip()) >= 2:
            record = fused
        elif allow_local:
            record = provisional_record(ident)
        if record is None:
            ident.status = 'unresolved' if ident.status != 'ambiguous' else ident.status
            return basename, ident
        if opinions:
            for opinion in opinions:
                try:
                    score = candidate_score(ident.query, opinion.record)
                    ident.evidence.append(
                        f"{opinion.provider}: {opinion.record.title}"
                        f" [{score:.2f}, confidence {float(opinion.confidence):.2f}]"
                    )
                except Exception:
                    continue
        # known_* overrides display values (explicit user truth)
        try:
            kt = (known_title or '').strip()
            ka = (known_author or '').strip()
            if kt or ka:
                record = BookRecord(
                    title=kt or record.title,
                    authors=(ka,) if ka else record.authors,
                    series=record.series, series_index=record.series_index,
                    year=record.year, language=record.language,
                    isbn13=record.isbn13, publisher=record.publisher,
                    provider=record.provider, provider_id=record.provider_id,
                    confidence=record.confidence)
        except Exception:
            pass
        ext = ident.ext or ''
        rendered = render_book_name(record, ext, pattern)
        if not rendered:
            return basename, ident
        ident.record = record
        ident.evidence.append(
            f"selected: {record.provider} [{float(record.confidence):.2f}]"
        )
        ident.title = record.title
        ident.authors = list(record.authors or [])
        ident.series = record.series or ''
        ident.series_index = record.series_index
        ident.year = record.year
        ident.language = record.language or ''
        ident.isbn = record.isbn13 or ''
        if ident.status == 'unresolved' and len(rendered) >= 2:
            ident.status = 'identified'
        return rendered, ident
    except Exception:
        try:
            return os.path.basename(file_path), BookIdentity(
                status='unresolved', warnings=['internal error'])
        except Exception:
            return '', BookIdentity(status='unresolved')
