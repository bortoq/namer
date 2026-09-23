"""PDF extractor -> BookQuery. Optional pypdf, else raw Info-scan. Never raises."""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import shutil
import tempfile
import urllib.request
from io import BytesIO
from typing import Optional

from namer.books.detect import find_isbns_in_text, is_garbage_text
from namer.books.models import BookQuery, ReadBudget
from namer.books.ocr import OCRResult, ocr_space_text

_TITLE_RE = re.compile(rb'/Title\s*\(((?:\\.|[^()])*)\)', re.DOTALL)
_AUTHOR_RE = re.compile(rb'/Author\s*\(((?:\\.|[^()])*)\)', re.DOTALL)
_AUTHOR_SPLIT_RE = re.compile(r'\s*(?:[,;]|\s+and\s+|\s+&\s+)\s*', re.IGNORECASE)
_PERSON_LINE_RE = re.compile(
    r'^[A-ZА-ЯЁ][a-zа-яё]+(?:\s+[A-ZА-ЯЁ][a-zа-яё]+){1,3}$')
_EDITION_RE = re.compile(r'\b(?:\d+(?:st|nd|rd|th)?\s+edition|\d+\s*[-‑–]?\s*е?\s*издани[ея])\b',
                         re.IGNORECASE)
_INITIAL_AUTHOR_RE = re.compile(
    r'^(?:[A-ZА-ЯЁ]\.\s*){1,2}[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё-]+(?:,)?$')
_AUTHOR_NAME_RE = re.compile(
    r'^(?:[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё-]+|[A-ZА-ЯЁ]\.)(?:\s+(?:[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё-]+|[A-ZА-ЯЁ]\.)){1,3},?$')


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


def _try_pdftotext(path: str) -> str:
    """Extract the first pages with the optional pdftotext utility."""
    try:
        result = subprocess.run(
            ['pdftotext', '-f', '1', '-l', '3', '-layout', path, '-'],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if result.returncode == 0:
            return (result.stdout or '')[:30000]
    except (OSError, subprocess.SubprocessError, UnicodeError):
        pass
    return ''


def _first_pages_pdf(path: str, pages: int = 3) -> bytes:
    """Build a small PDF containing only the first *pages* pages."""
    try:
        # OCR.space's free endpoint has a 1 MiB file limit.  Rasterizing the
        # first pages at its low-quality preset keeps scanned book covers
        # comfortably below that limit without uploading the source PDF.
        if shutil.which('gs'):
            with tempfile.NamedTemporaryFile(suffix='.pdf') as tmp:
                result = subprocess.run(
                    ['gs', '-q', '-sDEVICE=pdfwrite',
                     '-dCompatibilityLevel=1.4', '-dPDFSETTINGS=/screen',
                     '-dNOPAUSE', '-dBATCH', '-dFirstPage=1',
                     f'-dLastPage={pages}', f'-sOutputFile={tmp.name}', path],
                    capture_output=True, timeout=60, check=False,
                )
                if result.returncode == 0:
                    tmp.seek(0)
                    compressed = tmp.read()
                    if compressed:
                        return compressed
        import importlib
        mod = importlib.import_module('pypdf')
        reader = mod.PdfReader(path)
        writer = mod.PdfWriter()
        for page in list(reader.pages)[:pages]:
            writer.add_page(page)
        out = BytesIO()
        writer.write(out)
        return out.getvalue()
    except Exception:
        return b''


def _ocr_space_result(path: str) -> OCRResult:
    """Upload prepared pages through the isolated OCR client."""
    return ocr_space_text(_first_pages_pdf(path, 3))


def _try_ocr_space(path: str) -> str:
    """Compatibility adapter for callers that only need OCR text."""
    return _ocr_space_result(path).text


def _first_page_images(path: str, pages: int = 3) -> list:
    """Render the first PDF pages as PNG bytes for Umi-OCR."""
    try:
        with tempfile.TemporaryDirectory(prefix='namer-umi-') as directory:
            prefix = os.path.join(directory, 'page')
            result = subprocess.run(
                ['pdftoppm', '-f', '1', '-l', str(pages), '-r', '150',
                 '-png', path, prefix],
                capture_output=True, timeout=60, check=False,
            )
            if result.returncode != 0:
                return []
            images = []
            for name in sorted(os.listdir(directory)):
                if name.startswith('page-') and name.endswith('.png'):
                    with open(os.path.join(directory, name), 'rb') as fh:
                        images.append(fh.read())
            return images[:pages]
    except (OSError, subprocess.SubprocessError):
        return []


def _umi_language_options() -> list:
    try:
        req = urllib.request.Request('http://127.0.0.1:1224/api/ocr/get_options')
        with urllib.request.urlopen(req, timeout=0.3) as response:
            data = json.loads(response.read(256 * 1024).decode('utf-8', 'replace'))
        option = data.get('ocr.language') if isinstance(data, dict) else None
        return option.get('optionsList', []) if isinstance(option, dict) else []
    except Exception:
        return []


def _try_umi_ocr(path: str) -> str:
    """Use a locally running Umi-OCR HTTP server, if available."""
    try:
        language_options = _umi_language_options()
        if not language_options:
            return ''
        images = _first_page_images(path, 3)
        if not images:
            return ''
        language = ''
        for item in language_options:
            if isinstance(item, list) and len(item) >= 2:
                value, label = str(item[0]), str(item[1])
                if 'рус' in f'{value} {label}'.lower():
                    language = value
                    break
        texts = []
        for image in images:
            options = {'data.format': 'text', 'tbpu.parser': 'single_para'}
            if language:
                options['ocr.language'] = language
            payload = json.dumps({
                'base64': base64.b64encode(image).decode('ascii'),
                'options': options,
            }).encode('utf-8')
            req = urllib.request.Request(
                'http://127.0.0.1:1224/api/ocr', data=payload,
                headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read(2 * 1024 * 1024).decode('utf-8', 'replace'))
            if isinstance(result, dict) and result.get('code') == 100:
                value = result.get('data', '')
                if isinstance(value, str) and value.strip():
                    texts.append(value)
        return '\n'.join(texts)[:30000]
    except Exception:
        return ''


def _text_title_authors(text: str) -> tuple:
    """Best-effort title/author from a text PDF's opening lines."""
    try:
        def clean_line(line: str) -> str:
            line = re.sub(r'\s+', ' ', line).strip()
            # A common OCR artifact on covers is a word printed twice without
            # a separator (``MODERNMODERN``).  Collapse only exact halves.
            if len(line) >= 6 and len(line) % 2 == 0:
                half = line[:len(line) // 2]
                if half == line[len(line) // 2:]:
                    line = half
            return line

        def render_title(parts: list) -> str:
            values = [part.capitalize() if part.isupper() else part
                      for part in parts if part]
            return re.sub(r'\s+', ' ', ' '.join(values)).strip(' ,;')

        def author_line(line: str) -> bool:
            if _PERSON_LINE_RE.fullmatch(line) or _INITIAL_AUTHOR_RE.fullmatch(line):
                return True
            # An all-caps title resembles a name syntactically.  Accept it as
            # an author only when it contains an initial (``A. TANENBAUM``).
            return bool(_AUTHOR_NAME_RE.fullmatch(line)
                        and (line != line.upper() or re.search(r'\b[A-ZА-ЯЁ]\.', line)))

        lines = [clean_line(line) for line in (text or '').splitlines()]
        # Ignore OCR debris such as ``票！``.  A book title must contain at
        # least two letters; punctuation must never turn a single glyph into
        # an apparent title.
        lines = [line for line in lines if 2 <= len(line) <= 240
                 and not is_garbage_text(line)
                 and sum(char.isalpha() for char in line) >= 2]
        if not lines:
            return '', ()
        # A scanned cover can have an all-caps two-word author line first.
        # If it is followed by a long all-caps title block, use that block
        # rather than naming the file after the author (or OCR debris before
        # it).  This covers Raymond Smullyan's Russian editions.
        first_words = lines[0].replace(',', '').split()
        if (len(lines) >= 4 and len(first_words) == 2 and lines[0].isupper()
                and all(part.isupper() for part in lines[1:4])):
            title = render_title(lines[1:6])
            if len(title) >= 2:
                return title, (lines[0].rstrip(','),)
        # Cover layout: a series label, a multi-line title, an edition and
        # initial+surname author lines.  The title immediately before the
        # edition is more trustworthy than a decorative label at the top.
        for edition_idx, line in enumerate(lines[:12]):
            if not _EDITION_RE.search(line) or edition_idx < 1:
                continue
            prefix = lines[:edition_idx]
            # Author-before-title covers use the entire remaining block;
            # without such an author, keep the two title lines nearest the
            # edition and discard a decorative series label.
            author_before_title = author_line(prefix[0])
            title_parts = prefix[1:] if author_before_title else prefix[-2:]
            title = (re.sub(r'\s+', ' ', ' '.join(title_parts)).strip(' ,;')
                     if author_before_title else render_title(title_parts))
            author_parts = []
            for author in lines[edition_idx + 1:edition_idx + 4]:
                if author_line(author):
                    author_parts.append(author.rstrip(','))
                elif author_parts:
                    break
            if len(title) >= 2:
                if author_before_title:
                    return title, (prefix[0].rstrip(','),)
                return title, tuple(author_parts)
        # Some English covers put the edition first, then authors, then the
        # title.  This is the layout used by Modern Operating Systems.
        for edition_idx, line in enumerate(lines[:3]):
            if not _EDITION_RE.search(line):
                continue
            author_parts = []
            pos = edition_idx + 1
            while pos < min(len(lines), edition_idx + 4) and author_line(lines[pos]):
                author_parts.append(lines[pos].rstrip(','))
                pos += 1
            title_parts = []
            while pos < min(len(lines), edition_idx + 6):
                candidate = lines[pos]
                if _EDITION_RE.search(candidate) or author_line(candidate):
                    break
                title_parts.append(candidate)
                pos += 1
            title = render_title(title_parts)
            if len(title) >= 2:
                return title, tuple(author_parts)
        # Covers often put an all-caps author with an initial before an
        # all-caps title (e.g. ``CHRISTOPHER W. TOTTEN``).  In that layout
        # the first line is the author, not the title.
        if (len(lines) >= 2 and re.search(r'\b[A-Z]\.', lines[0])
                and lines[0].upper() == lines[0]):
            title = ' '.join(lines[1:4])
            title = re.sub(r'\b\d+(?:ST|ND|RD|TH)\s+EDITION\b', '',
                           title, flags=re.IGNORECASE)
            title = re.sub(r'\s+', ' ', title).strip(' ,;')
            if title:
                return title, split_authors(lines[0])
        if len(lines) >= 3 and _PERSON_LINE_RE.fullmatch(lines[0]):
            title = ' '.join(lines[1:4])
            title = re.sub(r'\b\d+(?:ST|ND|RD|TH)\s+EDITION\b', '',
                           title, flags=re.IGNORECASE)
            title = re.sub(r'\s+', ' ', title).strip(' ,;')
            if title:
                return title, (lines[0],)
        # OCR covers often put a subtitle/tagline first, then a title on
        # several lines, and the author below it (e.g. Russian editions of
        # ``How Linux Works``). Find the first plausible person line and use
        # the preceding title block instead of blindly taking lines[0].
        for author_idx, line in enumerate(lines[1:6], start=1):
            if not _PERSON_LINE_RE.fullmatch(line):
                continue
            title_lines = lines[:author_idx]
            if len(title_lines) >= 2 and title_lines[0][:1].islower():
                title_lines = title_lines[1:]
            if title_lines:
                title = render_title(title_lines)
                if len(title) >= 2:
                    return title, (line,)
        title = lines[0].strip(' ,;')
        authors = split_authors(lines[1]) if len(lines) > 1 else ()
        return title, authors
    except Exception:
        return '', ()


def _diagnostic_text(source: str, text: str) -> str:
    """One verbose-safe evidence line containing the extractor's output."""
    try:
        visible = (text or '').replace('\r', '').replace('\n', ' ↩ ')
        return f'{source} output: {visible}'
    except Exception:
        return f'{source} output unavailable'


def _metadata_title_is_placeholder(title: str, path: str) -> bool:
    """Whether PDF metadata is just an export/file-name placeholder."""
    try:
        value = re.sub(r'[^a-zа-яё0-9]+', '', (title or '').lower())
        if not value:
            return True
        stem = os.path.splitext(os.path.basename(path or ''))[0]
        filename_value = re.sub(r'[^a-zа-яё0-9]+', '', stem.lower())
        if value == filename_value:
            return True
        return (value in {'titul', 'title', 'untitled', 'converted', 'scan', 'document'}
                or value.startswith('titul'))
    except Exception:
        return False


def extract_pdf_query(path: str, budget: Optional[ReadBudget] = None) -> BookQuery:
    """PDF -> query. ISBN from text wins; Info/XMP only when human. Never raises."""
    try:
        b = budget or ReadBudget()
        if not isinstance(path, str) or not path:
            return BookQuery(source_format='pdf')
        try:
            if not os.path.isfile(path):
                return BookQuery(source_format='pdf')
        except OSError:
            return BookQuery(source_format='pdf')
        diagnostics = []
        info_title, info_author, head_text = _try_pypdf(path)
        if head_text and head_text.strip():
            diagnostics.append(f'text: pypdf ({len(head_text)} characters)')
            diagnostics.append(_diagnostic_text('text: pypdf', head_text))
        if not head_text or not head_text.strip():
            head_text = _try_pdftotext(path)
            if head_text and head_text.strip():
                diagnostics.append(f'text: pdftotext ({len(head_text)} characters)')
                diagnostics.append(_diagnostic_text('text: pdftotext', head_text))
        if not head_text or not head_text.strip():
            head_text = _try_umi_ocr(path)
            if head_text and head_text.strip():
                diagnostics.append(f'ocr: Umi-OCR success ({len(head_text)} characters)')
                diagnostics.append(_diagnostic_text('ocr: Umi-OCR', head_text))
        if not head_text or not head_text.strip():
            ocr_result = _ocr_space_result(path)
            diagnostics.append(
                f'ocr: {ocr_result.provider} {ocr_result.status}'
                + (f' ({ocr_result.detail})' if ocr_result.detail else ''))
            head_text = ocr_result.text
            if head_text:
                diagnostics.append(_diagnostic_text(f'ocr: {ocr_result.provider}', head_text))
        text_hint = head_text if head_text and head_text.strip() else ''
        raw = b''
        if not head_text or not info_title or not info_author:
            try:
                with open(path, 'rb') as f:
                    probe_size = min(b.max_uncompressed, 2 * 1024 * 1024)
                    head = f.read(probe_size // 2)
                    f.seek(max(0, os.path.getsize(path) - probe_size // 2))
                    raw = head + f.read(probe_size // 2)
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
        if text_hint:
            text_title, text_authors = _text_title_authors(text_hint)
            if text_title and (not title or _metadata_title_is_placeholder(title, path)):
                title = text_title
            if not authors or not any(_PERSON_LINE_RE.fullmatch(a) for a in authors):
                authors = text_authors
        return BookQuery(
            title_hint=title, authors_hint=authors, isbn_hint=isbn,
            source_format='pdf', diagnostics=tuple(diagnostics))
    except Exception:
        return BookQuery(source_format='pdf')
