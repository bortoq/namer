"""FB2 / FB2.ZIP extractor -> BookQuery. Stdlib only, never raises, never writes."""
from __future__ import annotations

import os
import re
import zipfile
from typing import Optional
import xml.etree.ElementTree as ET

from namer.books.detect import is_garbage_text, normalize_isbn
from namer.books.models import BookQuery, ReadBudget

_FB2_NS = 'http://www.gribuser.ru/xml/fictionbook/2.0'


def _local(tag: str) -> str:
    if not isinstance(tag, str):
        return ''
    return tag.rsplit('}', 1)[-1] if '}' in tag else tag


def _text(el) -> str:
    try:
        return ''.join(el.itertext()).strip() if el is not None else ''
    except Exception:
        return ''


def _author_name(el) -> str:
    """first+middle+last or nickname. '' when empty/garbage-creator."""
    try:
        if el is None:
            return ''
        parts = []
        for child in list(el):
            ln = _local(child.tag)
            if ln in ('first-name', 'middle-name', 'last-name', 'nickname'):
                t = _text(child).strip()
                if t:
                    parts.append(t)
        # fb2 order: first middle last — join, but 'Last First' not forced here
        name = ' '.join(parts).strip()
        return name
    except Exception:
        return ''


_DESC_OPEN_RE = re.compile(rb'<[A-Za-z0-9_.:-]*description(?:\s[^>]*)?>', re.IGNORECASE)
_DESC_CLOSE_RE = re.compile(rb'</[A-Za-z0-9_.:-]*description\s*>', re.IGNORECASE)


def _description_stub(data: bytes, cap: int) -> bytes | None:
    """Extract <description>…</description> wrapped in a stub root.

    Large fb2 files (base64 bodies/covers) exceed the XML budget, but the
    metadata lives at the start. A truncated slice is not well-formed, so
    parse just the description span. Namespace-tolerant matching downstream
    (via _local) is unaffected by the synthetic wrapper. None when the span
    is missing or itself over budget. Never raises.
    """
    try:
        if not data or cap <= 0:
            return None
        blob = bytes(data[:cap])
        m_open = _DESC_OPEN_RE.search(blob)
        if not m_open:
            return None
        m_close = _DESC_CLOSE_RE.search(blob, m_open.end())
        if not m_close:
            return None
        span = blob[m_open.start():m_close.end()]
        if len(span) > cap:
            return None
        return b'<stub>' + span + b'</stub>'
    except Exception:
        return None


def _parse_maybe_large(data: bytes, source_format: str, b: "ReadBudget") -> "BookQuery":
    """Parse full doc when small, else description stub. Never raises."""
    try:
        limit = b.max_xml_bytes * 4
        if len(data) <= limit:
            return parse_fb2_bytes(data, source_format)
        stub = _description_stub(data, b.max_xml_bytes)
        if stub is not None:
            return parse_fb2_bytes(stub, source_format)
        return BookQuery(source_format=source_format)
    except Exception:
        return BookQuery(source_format=source_format)


def parse_fb2_bytes(data: bytes, source_format: str = 'fb2') -> BookQuery:
    """Parse fb2 XML bytes -> query. Pure. Never raises."""
    try:
        if not isinstance(data, (bytes, bytearray)) or not data:
            return BookQuery(source_format=source_format or 'fb2')
        raw = bytes(data)
        if b'<!ENTITY' in raw.upper():
            return BookQuery(source_format=source_format or 'fb2')
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            return BookQuery(source_format=source_format or 'fb2')
        # find description/title-info (namespace-tolerant)
        title = ''
        authors: list = []
        series = ''
        series_index: Optional[int] = None
        year = None
        lang = ''
        isbn = ''
        publisher = ''
        desc = None
        for el in root.iter():
            if _local(el.tag) == 'description':
                desc = el
                break
        scope = desc if desc is not None else root
        ti = None
        for el in scope.iter():
            if _local(el.tag) == 'title-info':
                ti = el
                break
        if ti is not None:
            for child in list(ti):
                ln = _local(child.tag)
                try:
                    if ln == 'book-title' and not title:
                        title = _text(child)
                    elif ln == 'author':
                        nm = _author_name(child)
                        if nm and not is_garbage_text(nm) and nm not in authors:
                            authors.append(nm)
                    elif ln == 'sequence' and not series:
                        nm = (child.get('name') or '').strip()
                        if nm:
                            series = nm
                        num = (child.get('number') or '').strip()
                        if num:
                            try:
                                series_index = int(re.sub(r'\D', '', num) or '0') or None
                            except ValueError:
                                series_index = None
                    elif ln == 'date' and year is None:
                        cand = (child.get('value') or _text(child) or '')
                        m = re.search(r'((?:19|20)\d{2})', cand)
                        if m:
                            try:
                                year = int(m.group(1))
                            except ValueError:
                                year = None
                    elif ln == 'lang' and not lang:
                        lang = _text(child).strip().lower()[:8]
                except Exception:
                    continue
        # publish-info isbn/publisher (namespace-tolerant)
        for el in scope.iter():
            ln = _local(el.tag)
            try:
                if ln == 'isbn' and not isbn:
                    isbn = normalize_isbn(_text(el))
                elif ln == 'publisher' and not publisher:
                    publisher = _text(el).strip()[:120]
            except Exception:
                continue
        # NOTE: document-info/author is the FILE maker, never the book author.
        if title and is_garbage_text(title):
            title = ''
        authors = tuple(a for a in authors if a and not is_garbage_text(a))
        return BookQuery(
            title_hint=title.strip()[:300] if title else '',
            authors_hint=authors,
            series_hint=series.strip()[:200] if series else '',
            series_index_hint=series_index,
            isbn_hint=isbn,
            lang_hint=lang,
            year_hint=year,
            source_format=source_format or 'fb2',
        )
    except Exception:
        return BookQuery(source_format='fb2')


def extract_fb2_query(path: str, budget: Optional[ReadBudget] = None) -> BookQuery:
    """Read plain .fb2 file -> query. Guarded, size-limited. Never raises."""
    try:
        b = budget or ReadBudget()
        if not isinstance(path, str) or not path:
            return BookQuery(source_format='fb2')
        try:
            if not os.path.isfile(path):
                return BookQuery(source_format='fb2')
            if os.path.getsize(path) > b.max_uncompressed:
                return BookQuery(source_format='fb2')
        except OSError:
            return BookQuery(source_format='fb2')
        try:
            with open(path, 'rb') as f:
                data = f.read(b.max_uncompressed + 1)
        except OSError:
            return BookQuery(source_format='fb2')
        if len(data) > b.max_uncompressed:
            return BookQuery(source_format='fb2')
        return _parse_maybe_large(data, 'fb2', b)
    except Exception:
        return BookQuery(source_format='fb2')


def extract_fb2zip_query(path: str, budget: Optional[ReadBudget] = None) -> BookQuery:
    """Read first *.fb2 inside .fb2.zip -> query. In-memory, guarded."""
    try:
        b = budget or ReadBudget()
        if not isinstance(path, str) or not path:
            return BookQuery(source_format='fb2.zip')
        try:
            if not os.path.isfile(path):
                return BookQuery(source_format='fb2.zip')
            if os.path.getsize(path) > b.max_uncompressed:
                return BookQuery(source_format='fb2.zip')
        except OSError:
            return BookQuery(source_format='fb2.zip')
        try:
            with zipfile.ZipFile(path, 'r') as z:
                names = z.namelist()
                if len(names) > b.max_entries:
                    return BookQuery(source_format='fb2.zip')
                inner = None
                for n in names:
                    if n.lower().endswith('.fb2') and not n.endswith('/'):
                        inner = n
                        break
                if inner is None:
                    return BookQuery(source_format='fb2.zip')
                info = z.getinfo(inner)
                if info.file_size > b.max_uncompressed:
                    return BookQuery(source_format='fb2.zip')
                with z.open(inner, 'r') as f:
                    data = f.read(b.max_uncompressed + 1)
                if len(data) > b.max_uncompressed:
                    return BookQuery(source_format='fb2.zip')
        except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError):
            return BookQuery(source_format='fb2.zip')
        return _parse_maybe_large(data, 'fb2.zip', b)
    except Exception:
        return BookQuery(source_format='fb2.zip')
