"""Book file-kind detection + ISBN helpers. Pure, no side effects."""
from __future__ import annotations

import os
import re
from typing import Optional

BOOK_EXTENSIONS = frozenset({'.fb2', '.fb2.zip', '.epub', '.pdf', '.djvu'})

_SINGLE_EXT_KIND = {
    '.fb2': 'fb2',
    '.epub': 'epub',
    '.pdf': 'pdf',
    '.djvu': 'djvu',
}

_ISBN_CANDIDATE_RE = re.compile(r'97[89][-\s0-9]{10,}')

# garbage that must never become title/author
_GARBAGE_TOKENS = frozenset({
    'word', 'microsoft', 'scan', 'scanner', 'scankromsator', 'abbyy',
    'acrobat', 'untitled', 'untitled document',
})


def book_kind(path: str) -> Optional[str]:
    """Return 'fb2'|'fb2.zip'|'epub'|'pdf'|'djvu' or None. Never raises."""
    if not isinstance(path, str) or not path:
        return None
    base = os.path.basename(path).lower()
    if not base:
        return None
    if base.endswith('.fb2.zip'):
        return 'fb2.zip'
    _, ext = os.path.splitext(base)
    if not ext:
        return None
    return _SINGLE_EXT_KIND.get(ext)


def is_book_path(path: str) -> bool:
    return book_kind(path) is not None


def is_garbage_text(text: str) -> bool:
    """True for scanner/Word/Acrobat placeholders. Guard: non-str -> True."""
    if not isinstance(text, str):
        return True
    t = text.strip().lower()
    if len(t) < 2:
        return True
    for g in _GARBAGE_TOKENS:
        if g in t:
            return True
    return False


def normalize_isbn(raw: str) -> str:
    """Normalize to digits(+X for ISBN-10). '' when invalid. Never raises."""
    if not isinstance(raw, str) or not raw:
        return ''
    s = re.sub(r'[^0-9Xx]', '', raw.strip())
    if not s:
        return ''
    s = s.upper()
    if len(s) == 10:
        if not re.fullmatch(r'[0-9]{9}[0-9X]', s):
            return ''
        return s
    if len(s) == 13:
        if not s.isdigit() or not s.startswith(('978', '979')):
            return ''
        # ISBN-13 checksum
        try:
            total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(s[:12]))
            if (10 - total % 10) % 10 != int(s[12]):
                return ''
        except (ValueError, IndexError):
            return ''
        return s
    return ''


def find_isbns_in_text(text: str) -> list:
    """Extract valid ISBN-13 candidates from free text. Never raises."""
    if not isinstance(text, str) or not text:
        return []
    found: list = []
    try:
        for m in _ISBN_CANDIDATE_RE.finditer(text):
            norm = normalize_isbn(m.group(0))
            if norm and norm not in found:
                found.append(norm)
    except Exception:
        return []
    return found


def _skip_dir(name: str) -> bool:
    return name.startswith('.') or name == '__pycache__'


def find_book_files(directory: str, recursive: bool = True) -> list:
    """List book files under *directory*. Never raises on bad input."""
    files: list = []
    if not isinstance(directory, str) or not directory:
        return files
    if not os.path.isdir(directory):
        return files
    try:
        if recursive:
            for root, dirs, names in os.walk(directory):
                dirs[:] = [d for d in dirs if not _skip_dir(d)]
                for name in names:
                    fpath = os.path.join(root, name)
                    try:
                        if not os.path.isfile(fpath):
                            continue
                    except OSError:
                        continue
                    if is_book_path(name):
                        files.append(fpath)
        else:
            for name in os.listdir(directory):
                fpath = os.path.join(directory, name)
                try:
                    if os.path.isfile(fpath) and is_book_path(name):
                        files.append(fpath)
                except OSError:
                    continue
    except OSError:
        return files
    return sorted(files)
