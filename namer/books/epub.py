"""EPUB extractor -> BookQuery. Stdlib zip+xml only. Never raises."""
from __future__ import annotations

import os
import re
import zipfile
from typing import Optional
import xml.etree.ElementTree as ET

from namer.books.detect import is_garbage_text, normalize_isbn
from namer.books.models import BookQuery, ReadBudget

_DC = 'http://purl.org/dc/elements/1.1/'
_OPF = 'http://www.idpf.org/2007/opf'


def _local(tag: str) -> str:
    return tag.rsplit('}', 1)[-1] if isinstance(tag, str) and '}' in tag else (tag or '')


def _ns(tag: str) -> str:
    if isinstance(tag, str) and tag.startswith('{') and '}' in tag:
        return tag[1:].split('}', 1)[0]
    return ''


def parse_container_bytes(data: bytes) -> str:
    """container.xml -> opf path. '' when unknown. Never raises."""
    try:
        if not data:
            return ''
        raw = bytes(data)
        if b'<!ENTITY' in raw.upper():
            return ''
        root = ET.fromstring(raw)
        for el in root.iter():
            if _local(el.tag) == 'rootfile':
                fp = (el.get('full-path') or '').strip()
                if fp and not fp.startswith('/') and '..' not in fp.split('/'):
                    return fp
        return ''
    except Exception:
        return ''


def _inject_opf_ns(raw: bytes) -> bytes:
    """Add xmlns:opf to <package> when opf: is used undeclared. Never raises."""
    try:
        if b'opf:' in raw and b'xmlns:opf' not in raw:
            return re.sub(rb'<package\b',
                          b'<package xmlns:opf="http://www.idpf.org/2007/opf"',
                          raw, count=1)
        return raw
    except Exception:
        return raw


def parse_opf_bytes(data: bytes, source_format: str = 'epub') -> BookQuery:
    """OPF bytes -> query. Pure. Never raises."""
    try:
        if not data:
            return BookQuery(source_format=source_format or 'epub')
        raw = bytes(data)
        if b'<!ENTITY' in raw.upper():
            return BookQuery(source_format=source_format or 'epub')
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            # tolerate files using opf: prefix without declaration: inject the
            # namespace on <package> (touches the tag only, never text content)
            try:
                root = ET.fromstring(_inject_opf_ns(raw))
            except ET.ParseError:
                return BookQuery(source_format=source_format or 'epub')
        title = ''
        creators: list = []
        isbn = ''
        lang = ''
        year = None
        publisher = ''
        series = ''
        series_index: Optional[int] = None
        for el in root.iter():
            try:
                ns = _ns(el.tag)
                ln = _local(el.tag)
                if ns == _DC and ln == 'title' and not title:
                    title = ''.join(el.itertext()).strip()
                elif ns == _DC and ln == 'creator':
                    role = ''
                    for k, v in el.attrib.items():
                        if _local(k) == 'role':
                            role = v
                    # keep authors (role aut/unknown), drop translators
                    if role and role.lower() not in ('aut', 'author', ''):
                        lk = role.lower()
                        if 'trl' in lk or 'translator' in lk:
                            continue
                    nm = ''.join(el.itertext()).strip()
                    if nm and nm not in creators:
                        creators.append(nm)
                elif ns == _DC and ln == 'identifier' and not isbn:
                    scheme = ''
                    for k, v in el.attrib.items():
                        if _local(k) == 'scheme':
                            scheme = v
                    cand = normalize_isbn(''.join(el.itertext()))
                    if cand and (not scheme or scheme.upper() in ('ISBN', 'ISBN13', 'ISBN-13')):
                        isbn = cand
                    elif cand and not scheme and not isbn:
                        # UUID/DOI ignored; keep only ISBN-length
                        if len(cand) == 13:
                            isbn = cand
                elif ns == _DC and ln == 'language' and not lang:
                    lang = ''.join(el.itertext()).strip().lower()[:8]
                elif ns == _DC and ln == 'date' and year is None:
                    m = re.search(r'((?:19|20)\d{2})', ''.join(el.itertext()))
                    if m:
                        try:
                            year = int(m.group(1))
                        except ValueError:
                            year = None
                elif ns == _DC and ln == 'publisher' and not publisher:
                    publisher = ''.join(el.itertext()).strip()[:120]
                elif ln == 'meta':
                    name = ''
                    content = ''
                    for k, v in el.attrib.items():
                        lk = _local(k)
                        if lk == 'name':
                            name = v
                        elif lk == 'content':
                            content = v
                    # EPUB3 form: <meta property="calibre:series">X</meta>
                    prop = ''
                    for k, v in el.attrib.items():
                        if _local(k) == 'property':
                            prop = v
                    text = ''.join(el.itertext()).strip()
                    key = name or prop
                    if key == 'calibre:series' and not series:
                        series = (content or text).strip()[:200]
                    elif key == 'calibre:series_index' and series_index is None:
                        try:
                            series_index = int(float((content or text).strip()))
                        except (ValueError, TypeError):
                            series_index = None
            except Exception:
                continue
        if title and is_garbage_text(title):
            title = ''
        creators = tuple(c for c in creators if c and not is_garbage_text(c))
        return BookQuery(
            title_hint=title.strip()[:300] if title else '',
            authors_hint=creators,
            series_hint=series,
            series_index_hint=series_index,
            isbn_hint=isbn,
            lang_hint=lang,
            year_hint=year,
            source_format=source_format or 'epub',
        )
    except Exception:
        return BookQuery(source_format='epub')


def extract_epub_query(path: str, budget: Optional[ReadBudget] = None) -> BookQuery:
    """Read .epub (zip) -> query. Reads only container.xml + one opf."""
    try:
        b = budget or ReadBudget()
        if not isinstance(path, str) or not path:
            return BookQuery(source_format='epub')
        try:
            if not os.path.isfile(path):
                return BookQuery(source_format='epub')
            if os.path.getsize(path) > b.max_uncompressed:
                return BookQuery(source_format='epub')
        except OSError:
            return BookQuery(source_format='epub')
        try:
            with zipfile.ZipFile(path, 'r') as z:
                names = z.namelist()
                # total size guard
                try:
                    total = sum(i.file_size for i in z.infolist())
                    if total > b.max_uncompressed * 4:
                        return BookQuery(source_format='epub')
                except Exception:
                    pass
                lower = {n.lower(): n for n in names}
                cont_name = lower.get('meta-inf/container.xml')
                if cont_name is None:
                    # case-insensitive fallback scan
                    cont_name = next((n for n in names if n.lower() == 'meta-inf/container.xml'), None)
                opf_path = ''
                if cont_name is not None:
                    try:
                        info = z.getinfo(cont_name)
                        if info.file_size <= b.max_xml_bytes:
                            with z.open(cont_name, 'r') as f:
                                opf_path = parse_container_bytes(f.read(b.max_xml_bytes + 1))
                    except (KeyError, OSError, RuntimeError):
                        opf_path = ''
                if not opf_path:
                    # fallback: first .opf entry
                    opf_path = next((n for n in names if n.lower().endswith('.opf')), '')
                if not opf_path:
                    return BookQuery(source_format='epub')
                try:
                    info = z.getinfo(opf_path)
                except KeyError:
                    return BookQuery(source_format='epub')
                if info.file_size > b.max_xml_bytes:
                    return BookQuery(source_format='epub')
                with z.open(opf_path, 'r') as f:
                    return parse_opf_bytes(f.read(b.max_xml_bytes + 1), 'epub')
        except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError):
            return BookQuery(source_format='epub')
    except Exception:
        return BookQuery(source_format='epub')
