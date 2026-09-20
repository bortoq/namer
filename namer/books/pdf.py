"""PDF extractor -> BookQuery. Optional pypdf, else raw Info-scan. Never raises."""
from __future__ import annotations

import os
import re
from typing import Optional

from namer.books.detect import find_isbns_in_text, is_garbage_text
from namer.books.models import BookQuery, ReadBudget

_TITLE_RE = re.compile(rb'/Title\s*\(((?:\\.|[^()])*)\)', re.DOTALL)
_AUTHOR_RE = re.compile(rb'/Author\s*\(((?:\\.|[^()])*)\)', re.DOTALL)
_AUTHOR_SPLIT_RE = re.compile(r'\s*(?:[,;]|\s+and\s+|\s+&\s+)\s*', re.IGNORECASE)


def _unescape_pdf_string(raw: bytes) -> str:
    try:
        # octal escapes + \( \) \\; then latin-1 -> try utf-8
        out = bytearray()
        i = 0
        while i < len(raw):
            c = raw[i]
            if c == 0x5C and i + 1 < len(raw):  # backslash
                n = raw[i + 1]
                if n in (0x28, 0x29, 0x5C):
                    out.append(n)
                    i += 2
                    continue
                if 0x30 <= n <= 0x37:  # octal up to 3 digits
                    j = i + 1
                    digits = b''
                    while j < len(raw) and len(digits) < 3 and 0x30 <= raw[j] <= 0x37:
                        digits += bytes((raw[j],))
                        j += 1
                    try:
                        out.append(int(digits, 8) & 0xFF)
                    except ValueError:
                        out.append(n)
                    i = j
                    continue
                out.append(n)
                i += 2
                continue
            out.append(c)
            i += 1
        try:
            return bytes(out).decode('utf-8')
        except UnicodeDecodeError:
            return bytes(out).decode('latin-1', 'replace')
    except Exception:
        return ''


def parse_pdf_info_bytes(data: bytes) -> tuple:
    """Scan raw PDF bytes for /Title() /Author(). Returns (title, author_raw)."""
    try:
        if not data:
            return '', ''
        head = bytes(data[: 256 * 1024])  # Info dict lives near header/trailer
        tail = bytes(data[-256 * 1024:]) if len(data) > 256 * 1024 else b''
        blob = head + tail
        title = ''
        author = ''
        try:
            m = _TITLE_RE.search(blob)
            if m:
                title = _unescape_pdf_string(m.group(1)).strip()[:300]
        except Exception:
            title = ''
        try:
            m = _AUTHOR_RE.search(blob)
            if m:
                author = _unescape_pdf_string(m.group(1)).strip()[:300]
        except Exception:
            author = ''
        return title, author
    except Exception:
        return '', ''


_XMP_TITLE_RE = re.compile(
    rb'<dc:title>.*?<rdf:li[^>]*>(.*?)</rdf:li>', re.DOTALL | re.IGNORECASE)
_XMP_TITLE_DIRECT_RE = re.compile(
    rb'<dc:title>\s*([^<>]{2,300})\s*</dc:title>', re.DOTALL | re.IGNORECASE)
_XMP_CREATOR_RE = re.compile(
    rb'<dc:creator>.*?<rdf:li[^>]*>(.*?)</rdf:li>', re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r'<[^>]+>')


def _xmp_text(raw: bytes) -> str:
    """Strip inner tags + XML entities from an XMP capture. Never raises."""
    try:
        import xml.sax.saxutils as _su
        t = raw.decode('utf-8', 'replace')
        t = _TAG_RE.sub('', t)
        try:
            t = _su.unescape(t)
        except Exception:
            pass
        return t.strip()[:300]
    except Exception:
        return ''


def parse_xmp_bytes(data: bytes) -> tuple:
    """Extract (title, author_raw) from an XMP packet in raw PDF bytes.

    Pure. Returns ('','') when absent. Never raises.
    """
    try:
        if not data:
            return '', ''
        blob = bytes(data[: 2 * 1024 * 1024])
        title = ''
        creator = ''
        try:
            m = _XMP_TITLE_RE.search(blob)
            if m:
                title = _xmp_text(m.group(1))
            if not title:
                m = _XMP_TITLE_DIRECT_RE.search(blob)
                if m:
                    title = _xmp_text(m.group(1))
        except Exception:
            title = ''
        try:
            m = _XMP_CREATOR_RE.search(blob)
            if m:
                creator = _xmp_text(m.group(1))
        except Exception:
            creator = ''
        return title, creator
    except Exception:
        return '', ''


def split_authors(raw: str) -> tuple:
    try:
        if not raw:
            return ()
        parts = [p.strip() for p in _AUTHOR_SPLIT_RE.split(raw) if p.strip()]
        return tuple(p[:120] for p in parts if p and not is_garbage_text(p))
    except Exception:
        return ()


def _try_pypdf(path: str) -> tuple:
    """(info_title, info_author, head_text). All '' when unavailable. Never raises."""
    try:
        import importlib
        mod = importlib.import_module('pypdf')
        reader_cls = getattr(mod, 'PdfReader', None)
        if reader_cls is None:
            return '', '', ''
        reader = reader_cls(path)
        title = ''
        author = ''
        try:
            meta = reader.metadata
            if meta is not None:
                title = (getattr(meta, 'title', '') or '').strip()[:300]
                author = (getattr(meta, 'author', '') or '').strip()[:300]
        except Exception:
            title, author = '', ''
        head_text = ''
        try:
            for page in list(getattr(reader, 'pages', []) or [])[:2]:
                try:
                    head_text += '\n' + (page.extract_text() or '')
                except Exception:
                    continue
                if len(head_text) > 20000:
                    break
        except Exception:
            head_text = head_text or ''
        return title or '', author or '', head_text[:20000]
    except Exception:
        return '', '', ''


def extract_pdf_query(path: str, budget: Optional[ReadBudget] = None) -> BookQuery:
    """PDF -> query. ISBN from text wins; Info/XMP only when human. Never raises."""
    try:
        b = budget or ReadBudget()
        if not isinstance(path, str) or not path:
            return BookQuery(source_format='pdf')
        try:
            if not os.path.isfile(path):
                return BookQuery(source_format='pdf')
            if os.path.getsize(path) > b.max_uncompressed:
                return BookQuery(source_format='pdf')
        except OSError:
            return BookQuery(source_format='pdf')
        info_title, info_author, head_text = _try_pypdf(path)
        raw = b''
        if not head_text or not info_title or not info_author:
            try:
                with open(path, 'rb') as f:
                    raw = f.read(min(b.max_uncompressed, 2 * 1024 * 1024))
            except OSError:
                raw = b''
        if raw:
            if not info_title or not info_author:
                t2, a2 = parse_pdf_info_bytes(raw)
                if not info_title:
                    info_title = t2
                if not info_author:
                    info_author = a2
            # AUDIT: XMP packet (dc:title/dc:creator) preferred over Info —
            # Info often holds the producer app, XMP the real book data.
            try:
                xt, xa = parse_xmp_bytes(raw)
            except Exception:
                xt, xa = '', ''
            if xt and (not info_title or is_garbage_text(info_title)):
                info_title = xt
            if xa and (not info_author or is_garbage_text(info_author)):
                info_author = xa
            if not head_text:
                try:
                    head_text = raw.decode('latin-1', 'replace')[:20000]
                except Exception:
                    head_text = ''
        isbns = find_isbns_in_text(head_text or '')
        isbn = isbns[0] if isbns else ''
        title = '' if is_garbage_text(info_title or '') else (info_title or '').strip()[:300]
        authors = split_authors(info_author or '')
        return BookQuery(
            title_hint=title, authors_hint=authors, isbn_hint=isbn,
            source_format='pdf')
    except Exception:
        return BookQuery(source_format='pdf')
