"""Network OCR client, cache and rate-limit handling for scanned books.

This module deliberately knows nothing about PDF parsing: callers provide a
small PDF containing the pages to recognize.  Keeping the network boundary
here makes OCR observable and prevents duplicate uploads from the book parser.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid


_CACHE_TTL_SEC = 30 * 24 * 60 * 60
_CACHE_LOCK = threading.Lock()
_REQUEST_LOCK = threading.BoundedSemaphore(1)
_BACKOFF_LOCK = threading.Lock()
_BACKOFF_UNTIL = 0.0


@dataclass(frozen=True)
class OCRResult:
    text: str = ''
    provider: str = 'ocr.space'
    status: str = 'unavailable'  # success | cached | rate-limited | error
    detail: str = ''


def _cache_path() -> str:
    root = os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache')
    return os.path.join(root, 'namer', 'ocr.json')


def _read_cache() -> dict:
    try:
        with open(_cache_path(), encoding='utf-8') as fh:
            value = json.load(fh)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_cache(entries: dict) -> None:
    try:
        path = _cache_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temporary = path + '.tmp'
        with open(temporary, 'w', encoding='utf-8') as fh:
            json.dump(entries, fh, ensure_ascii=False, separators=(',', ':'))
        os.replace(temporary, path)
    except OSError:
        pass


def _multipart(fields: dict, content: bytes) -> tuple:
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
        b'Content-Disposition: form-data; name="file"; filename="first-pages.pdf"\r\n',
        b'Content-Type: application/pdf\r\n\r\n', content, b'\r\n',
        f'--{boundary}--\r\n'.encode(),
    ])
    return b''.join(chunks), boundary


def _rate_limit_detail(data: object) -> str:
    if not isinstance(data, dict):
        return 'service returned an invalid response'
    messages = data.get('ErrorMessage') or data.get('ErrorDetails') or ''
    if isinstance(messages, list):
        messages = '; '.join(str(item) for item in messages)
    return str(messages or 'OCR service rejected the request')[:180]


def _back_off() -> None:
    global _BACKOFF_UNTIL
    with _BACKOFF_LOCK:
        _BACKOFF_UNTIL = time.time() + 60


def ocr_space_text(content: bytes) -> OCRResult:
    """Recognize a prepared PDF through OCR.space with cache and backoff.

    The public key uses Engine 2; a user-provided key enables Engine 3.  Only
    successful text is cached, keyed by the exact uploaded pages.
    """
    global _BACKOFF_UNTIL
    if os.environ.get('NAMER_DISABLE_OCR') == '1':
        return OCRResult(status='unavailable', detail='disabled by NAMER_DISABLE_OCR')
    if not content:
        return OCRResult(status='unavailable', detail='cannot prepare PDF pages')
    configured_key = os.environ.get('OCR_SPACE_API_KEY', '').strip()
    engine = '3' if configured_key else '2'
    cache_key = f'{engine}:{hashlib.sha256(content).hexdigest()}'
    now = time.time()
    with _CACHE_LOCK:
        cached = _read_cache().get(cache_key)
    try:
        cached_at = float(cached.get('time', 0) or 0) if isinstance(cached, dict) else 0
    except (TypeError, ValueError):
        cached_at = 0
    if isinstance(cached, dict) and now - cached_at < _CACHE_TTL_SEC:
        text = cached.get('text', '')
        if isinstance(text, str) and text:
            return OCRResult(text=text, status='cached', detail=f'{len(text)} characters')
    with _BACKOFF_LOCK:
        remaining = _BACKOFF_UNTIL - now
    if remaining > 0:
        return OCRResult(status='rate-limited', detail=f'retry after {int(remaining) + 1}s')
    with _REQUEST_LOCK:
        try:
            body, boundary = _multipart({
                'language': 'auto', 'OCREngine': engine, 'filetype': 'PDF',
                'isOverlayRequired': 'false', 'scale': 'true',
            }, content)
            req = urllib.request.Request(
                'https://api.ocr.space/parse/image', data=body,
                headers={'Content-Type': f'multipart/form-data; boundary={boundary}',
                         'apikey': configured_key or 'helloworld',
                         'User-Agent': 'namer/0.1'}, method='POST')
            with urllib.request.urlopen(req, timeout=30) as response:
                payload = response.read(2 * 1024 * 1024)
            data = json.loads(payload.decode('utf-8', 'replace'))
            if data.get('IsErroredOnProcessing'):
                detail = _rate_limit_detail(data)
                if 'limit' in detail.lower() or 'rate' in detail.lower():
                    _back_off()
                    return OCRResult(status='rate-limited', detail=detail)
                return OCRResult(status='error', detail=detail)
            text = '\n'.join(str(result.get('ParsedText', '')) for result in
                             (data.get('ParsedResults') or []) if isinstance(result, dict)).strip()[:30000]
            if not text:
                return OCRResult(status='error', detail='service returned no text')
            with _CACHE_LOCK:
                entries = _read_cache()
                entries[cache_key] = {'time': time.time(), 'text': text}
                _write_cache(entries)
            return OCRResult(text=text, status='success', detail=f'{len(text)} characters')
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                _back_off()
                return OCRResult(status='rate-limited', detail='HTTP 429')
            return OCRResult(status='error', detail=f'HTTP {exc.code}')
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            return OCRResult(status='error', detail=type(exc).__name__)
