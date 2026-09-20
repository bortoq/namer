"""DjVu extractor -> BookQuery. Binary ANTa-scan + optional djvused. Never raises."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Optional

from namer.books.detect import find_isbns_in_text, is_garbage_text
from namer.books.models import BookQuery, ReadBudget

_META_KV_RE = re.compile(r'(?i)\b(title|author|creator|series)\s+"([^"]{1,300})"')
_DJVUSED_LINE_RE = re.compile(r'^\s*(title|author|creator|series)\s+(.+?)\s*$', re.IGNORECASE)


def parse_djvu_meta_bytes(data: bytes) -> BookQuery:
    """Scan DjVu binary for ANTa-style key/value + ISBN. Pure. Never raises."""
    try:
        if not data:
            return BookQuery(source_format='djvu')
        blob = bytes(data[: 2 * 1024 * 1024])
        try:
            text = blob.decode('utf-8', 'replace')
        except Exception:
            text = ''
        title = ''
        authors: list = []
        series = ''
        for m in _META_KV_RE.finditer(text):
            try:
                key = m.group(1).lower()
                val = m.group(2).strip()[:300]
                if not val or is_garbage_text(val):
                    continue
                if key == 'title' and not title:
                    title = val
                elif key in ('author', 'creator'):
                    if val not in authors:
                        authors.append(val)
                elif key == 'series' and not series:
                    series = val[:200]
            except Exception:
                continue
        isbns = find_isbns_in_text(text)
        return BookQuery(
            title_hint=title, authors_hint=tuple(authors), series_hint=series,
            isbn_hint=isbns[0] if isbns else '', source_format='djvu')
    except Exception:
        return BookQuery(source_format='djvu')


def extract_via_djvused(path: str, timeout_sec: float = 5.0) -> BookQuery:
    """Query `djvused PATH -e 'print-meta'`. No shell. '' when missing. Never raises."""
    try:
        if not shutil.which('djvused'):
            return BookQuery(source_format='djvu')
        try:
            proc = subprocess.run(
                ['djvused', path, '-e', 'print-meta'],
                capture_output=True, timeout=timeout_sec, check=False)
        except (OSError, subprocess.SubprocessError):
            return BookQuery(source_format='djvu')
        if proc.returncode != 0:
            return BookQuery(source_format='djvu')
        try:
            text = (proc.stdout or b'').decode('utf-8', 'replace')
        except Exception:
            return BookQuery(source_format='djvu')
        title = ''
        authors: list = []
        series = ''
        for line in text.splitlines():
            m = _DJVUSED_LINE_RE.match(line.strip().strip('()'))
            if not m:
                continue
            key = m.group(1).lower()
            val = m.group(2).strip().strip('"')[:300]
            if not val or is_garbage_text(val):
                continue
            if key == 'title' and not title:
                title = val
            elif key in ('author', 'creator'):
                if val not in authors:
                    authors.append(val)
            elif key == 'series' and not series:
                series = val[:200]
        isbns = find_isbns_in_text(text)
        return BookQuery(
            title_hint=title, authors_hint=tuple(authors), series_hint=series,
            isbn_hint=isbns[0] if isbns else '', source_format='djvu')
    except Exception:
        return BookQuery(source_format='djvu')


def extract_djvu_query(path: str, budget: Optional[ReadBudget] = None) -> BookQuery:
    """DjVu -> query: djvused first, binary scan fallback. Never raises."""
    try:
        b = budget or ReadBudget()
        if not isinstance(path, str) or not path:
            return BookQuery(source_format='djvu')
        try:
            if not os.path.isfile(path):
                return BookQuery(source_format='djvu')
            if os.path.getsize(path) > b.max_uncompressed:
                return BookQuery(source_format='djvu')
        except OSError:
            return BookQuery(source_format='djvu')
        # AUDIT: extract_via_djvused already returns source_format='djvu' —
        # return as-is instead of a field-by-field rebuild.
        via = extract_via_djvused(path, b.timeout_sec)
        if not via.is_empty():
            return via
        try:
            with open(path, 'rb') as f:
                data = f.read(min(b.max_uncompressed, 2 * 1024 * 1024))
        except OSError:
            return BookQuery(source_format='djvu')
        return parse_djvu_meta_bytes(data)
    except Exception:
        return BookQuery(source_format='djvu')
