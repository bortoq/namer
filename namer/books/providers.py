"""Network book providers (OpenLibrary, GoogleBooks). Injectable fetcher for tests.

All functions never raise: network/JSON errors -> []. Default fetcher uses
urllib with a short timeout; callers may inject a stub.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Callable, Optional

from namer.books.detect import normalize_isbn
from namer.books.models import BookOpinion, BookQuery, BookRecord

Fetcher = Callable[[str], object]


def _default_fetch(url: str, timeout: float = 5.0):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'namer/0.1'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(512 * 1024)
        try:
            return json.loads(raw.decode('utf-8', 'replace'))
        except (ValueError, UnicodeDecodeError):
            return None
    except Exception:
        return None


def _year_of(value) -> Optional[int]:
    try:
        import re
        m = re.search(r'((?:19|20)\d{2})', str(value or ''))
        return int(m.group(1)) if m else None
    except Exception:
        return None


def _record_from_openlibrary_doc(doc: dict, isbn: str = '') -> Optional[BookRecord]:
    try:
        if not isinstance(doc, dict):
            return None
        title = (doc.get('title') or '').strip()[:300]
        if len(title) < 2:
            return None
        authors: list = []
        for a in doc.get('author_name') or []:
            if isinstance(a, str) and a.strip():
                authors.append(a.strip()[:120])
        year = _year_of(doc.get('first_publish_year'))
        lang = ''
        langs = doc.get('language') or []
        if isinstance(langs, list) and langs and isinstance(langs[0], str):
            lang = langs[0][:8]
        key = (doc.get('key') or '') if isinstance(doc.get('key'), str) else ''
        return BookRecord(
            title=title, authors=tuple(authors), year=year, language=lang or '',
            isbn13=isbn, provider='openlibrary', provider_id=key,
            confidence=0.98 if isbn else 0.85)
    except Exception:
        return None


def _resolve_ol_author_names(keys: list, fetch: Fetcher) -> tuple:
    """Resolve ['/authors/OL1A', ...] -> ('Name', ...) via author docs.

    Bounded (first 3 keys), guarded, same injected fetcher. Never raises.
    """
    try:
        names: list = []
        for key in (keys or [])[:3]:
            try:
                if not isinstance(key, str) or not key.startswith('/authors/'):
                    continue
                url = 'https://openlibrary.org' + key + '.json'
                try:
                    doc = fetch(url)
                except Exception:
                    continue
                if isinstance(doc, dict):
                    nm = doc.get('name')
                    if isinstance(nm, str) and nm.strip() and len(nm.strip()) >= 2:
                        names.append(nm.strip()[:120])
            except Exception:
                continue
        return tuple(names)
    except Exception:
        return ()


def search_openlibrary(query: BookQuery, fetcher: Optional[Fetcher] = None) -> list:
    """Search OpenLibrary by ISBN first, then title+author. Never raises."""
    try:
        if not isinstance(query, BookQuery) or query.is_empty():
            return []
        fetch = fetcher or _default_fetch
        # 1) exact ISBN
        isbn = normalize_isbn(query.isbn_hint or '')
        if isbn and len(isbn) == 13:
            try:
                url = f'https://openlibrary.org/isbn/{urllib.parse.quote(isbn)}.json'
                doc = fetch(url)
            except Exception:
                doc = None
            if isinstance(doc, dict) and (doc.get('title') or '').strip():
                # NOTE (audit): /isbn/*.json authors are [{'key': '/authors/OL..'}],
                # never display names — resolve bounded via author docs, else drop.
                raw_authors = doc.get('authors') or doc.get('author_name') or []
                keys = [a.get('key') for a in raw_authors
                        if isinstance(a, dict) and isinstance(a.get('key'), str)]
                authors = [a.strip()[:120] for a in raw_authors
                           if isinstance(a, str) and a.strip()]
                if keys and len(authors) < 3:
                    try:
                        resolved = _resolve_ol_author_names(keys, fetch)
                    except Exception:
                        resolved = ()
                    for nm in resolved:
                        if nm not in authors:
                            authors.append(nm)
                rec = BookRecord(
                    title=str(doc.get('title')).strip()[:300],
                    authors=tuple(x[:120] for x in authors if x),
                    year=_year_of(doc.get('publish_date')),
                    isbn13=isbn, provider='openlibrary',
                    provider_id=str(doc.get('key', ''))[:80], confidence=0.98)
                if len(rec.title) >= 2:
                    return [BookOpinion('openlibrary', rec, 0.98)]
        # 2) title + author search
        title = (query.title_hint or '').strip()
        if len(title) < 2:
            return []
        try:
            params = {'title': title, 'limit': '5'}
            if query.authors_hint:
                params['author'] = query.authors_hint[0]
            url = 'https://openlibrary.org/search.json?' + urllib.parse.urlencode(params)
            data = fetch(url)
        except Exception:
            return []
        if not isinstance(data, dict):
            return []
        docs = data.get('docs')
        if not isinstance(docs, list):
            return []
        out: list = []
        for doc in docs[:5]:
            rec = _record_from_openlibrary_doc(doc if isinstance(doc, dict) else {}, '')
            if rec is not None:
                out.append(BookOpinion('openlibrary', rec, 0.85 if query.authors_hint else 0.6))
        return out
    except Exception:
        return []


def _record_from_google_item(item: dict) -> Optional[BookRecord]:
    try:
        if not isinstance(item, dict):
            return None
        info = item.get('volumeInfo')
        if not isinstance(info, dict):
            return None
        title = (info.get('title') or '').strip()[:300]
        if len(title) < 2:
            return None
        authors = tuple(a.strip()[:120] for a in (info.get('authors') or [])
                        if isinstance(a, str) and a.strip())
        year = _year_of(info.get('publishedDate'))
        lang = (info.get('language') or '')[:8] if isinstance(info.get('language'), str) else ''
        isbn13 = ''
        for ident in info.get('industryIdentifiers') or []:
            if isinstance(ident, dict) and ident.get('type') == 'ISBN_13':
                isbn13 = normalize_isbn(str(ident.get('identifier', '')))
                if isbn13:
                    break
        publisher = (info.get('publisher') or '')[:120] if isinstance(info.get('publisher'), str) else ''
        gid = item.get('id', '') if isinstance(item.get('id'), str) else ''
        conf = 0.95 if isbn13 else 0.8
        return BookRecord(title=title, authors=authors, year=year, language=lang,
                          isbn13=isbn13, publisher=publisher,
                          provider='googlebooks', provider_id=gid[:80], confidence=conf)
    except Exception:
        return None


def search_googlebooks(query: BookQuery, fetcher: Optional[Fetcher] = None) -> list:
    """Search Google Books. Never raises."""
    try:
        if not isinstance(query, BookQuery) or query.is_empty():
            return []
        fetch = fetcher or _default_fetch
        isbn = normalize_isbn(query.isbn_hint or '')
        if isbn and len(isbn) == 13:
            q = f'isbn:{isbn}'
        else:
            title = (query.title_hint or '').strip()
            if len(title) < 2:
                return []
            q = f'intitle:{title}'
            if query.authors_hint:
                q += f'+inauthor:{query.authors_hint[0]}'
        try:
            url = ('https://www.googleapis.com/books/v1/volumes?'
                   + urllib.parse.urlencode({'q': q, 'maxResults': '5'}))
            data = fetch(url)
        except Exception:
            return []
        if not isinstance(data, dict):
            return []
        items = data.get('items')
        if not isinstance(items, list):
            return []
        out: list = []
        for item in items[:5]:
            rec = _record_from_google_item(item)
            if rec is not None:
                out.append(BookOpinion('googlebooks', rec, rec.confidence))
        return out
    except Exception:
        return []
