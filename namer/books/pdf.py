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
import uuid
from io import BytesIO
from typing import Optional

from namer.books.detect import find_isbns_in_text, is_garbage_text
from namer.books.models import BookQuery, ReadBudget

_TITLE_RE = re.compile(rb'/Title\s*\(((?:\\.|[^()])*)\)', re.DOTALL)
_AUTHOR_RE = re.compile(rb'/Author\s*\(((?:\\.|[^()])*)\)', re.DOTALL)
_AUTHOR_SPLIT_RE = re.compile(r'\s*(?:[,;]|\s+and\s+|\s+&\s+)\s*', re.IGNORECASE)
_PERSON_LINE_RE = re.compile(
    r'^[A-ZА-ЯЁ][a-zа-яё]+(?:\s+[A-ZА-ЯЁ][a-zа-яё]+){1,3}$')


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


def _multipart(fields: dict, name: str, content: bytes,
               filename: str, content_type: str) -> tuple:
    boundary = '----namer-' + uuid.uuid4().hex
    chunks = []
    for key, value in fields.items():
        chunks.extend([
            f'--{boundary}\r\n'.encode(),
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
            str(value).encode(), b'\r\n',
        ])
    chunks.extend([
        f'--{boundary}\r\n'.encode(),
        (f'Content-Disposition: form-data; name="{name}"; '
         f'filename="{filename}"\r\n').encode(),
        f'Content-Type: {content_type}\r\n\r\n'.encode(),
        content, b'\r\n', f'--{boundary}--\r\n'.encode(),
    ])
    return b''.join(chunks), boundary


def _try_ocr_space(path: str) -> str:
    """OCR first three PDF pages through OCR.space Engine 3.

    Uses OCR.space's documented public demo key by default.  A personal key
    can be supplied through OCR_SPACE_API_KEY to avoid shared-key limits.
    """
    try:
        if os.environ.get('NAMER_DISABLE_OCR') == '1':
            return ''
        api_key = os.environ.get('OCR_SPACE_API_KEY', '').strip() or 'helloworld'
        content = _first_pages_pdf(path, 3)
        if not content:
            return ''
        body, boundary = _multipart(
            {'language': 'auto', 'OCREngine': '3',
             'filetype': 'PDF', 'isOverlayRequired': 'false',
             'scale': 'true'},
            'file', content, 'first-pages.pdf', 'application/pdf')
        req = urllib.request.Request(
            'https://api.ocr.space/parse/image', data=body,
            headers={'Content-Type': f'multipart/form-data; boundary={boundary}',
                     'apikey': api_key,
                     'User-Agent': 'namer/0.1'}, method='POST')
        with urllib.request.urlopen(req, timeout=90) as response:
            payload = response.read(2 * 1024 * 1024)
        data = json.loads(payload.decode('utf-8', 'replace'))
        text = []
        for result in data.get('ParsedResults') or []:
            if isinstance(result, dict) and result.get('ParsedText'):
                text.append(str(result['ParsedText']))
        return '\n'.join(text)[:30000]
    except Exception:
        return ''


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
        lines = [re.sub(r'\s+', ' ', line).strip()
                 for line in (text or '').splitlines()]
        lines = [line for line in lines if 2 <= len(line) <= 240]
        if not lines or is_garbage_text(lines[0]):
            return '', ()
        # Covers often put an all-caps author with an initial before an
        # all-caps title (e.g. ``CHRISTOPHER W. TOTTEN``).  In that layout
        # the first line is the author, not the title.
        if (len(lines) >= 2 and re.search(r'\b[A-Z]\.', lines[0])
                and lines[0].upper() == lines[0]):
            title = ' '.join(lines[1:4])
            title = re.sub(r'\b\d+(?:ST|ND|RD|TH)\s+EDITION\b', '',
                           title, flags=re.IGNORECASE)
            title = re.sub(r'\s+', ' ', title).strip()
            if title:
                return title, split_authors(lines[0])
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
                normalized = []
                for part in title_lines:
                    normalized.append(part.capitalize() if part.isupper() else part)
                title = re.sub(r'\s+', ' ', ' '.join(normalized)).strip()
                if len(title) >= 2:
                    return title, (line,)
        title = lines[0]
        authors = split_authors(lines[1]) if len(lines) > 1 else ()
        return title, authors
    except Exception:
        return '', ()


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
        return value in {'titul', 'title', 'untitled', 'converted', 'scan', 'document'}
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
        info_title, info_author, head_text = _try_pypdf(path)
        if not head_text or not head_text.strip():
            head_text = _try_pdftotext(path)
        if not head_text or not head_text.strip():
            head_text = _try_umi_ocr(path)
        if not head_text or not head_text.strip():
            head_text = _try_ocr_space(path)
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
            if not authors:
                authors = text_authors
        return BookQuery(
            title_hint=title, authors_hint=authors, isbn_hint=isbn,
            source_format='pdf')
    except Exception:
        return BookQuery(source_format='pdf')
