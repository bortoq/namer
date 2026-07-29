"""Wikipedia title translation — find English title for foreign-language movie names.

Uses the free Wikipedia API (no key required) to search for a page in the
source language and retrieve the English title via interlanguage links.

Typical usage::

    from namer.wikipedia import enrich_title_via_wiki

    meta = {'title': 'невидимый гость', 'is_series': False}
    enrich_title_via_wiki(meta)
    # meta['title'] == 'The Invisible Guest'
"""

import json
import os
import re
import urllib.parse
import urllib.request
from typing import Dict, Optional

# ── Language detection ────────────────────────────────────────────────────────

# Cyrillic range: U+0400–U+04FF + U+0500–U+052F
_CYRILLIC_RE = re.compile(r'[\u0400-\u052F]')

# CJK (Chinese, Japanese, Korean)
_CJK_RE = re.compile(r'[\u3040-\u9FFF\uAC00-\uD7AF]')

# Arabic
_ARABIC_RE = re.compile(r'[\u0600-\u06FF]')

# Greek
_GREEK_RE = re.compile(r'[\u0370-\u03FF]')

# Thai
_THAI_RE = re.compile(r'[\u0E00-\u0E7F]')

_LANG_MAP = [
    (_CYRILLIC_RE, 'ru'),    # Russian for Cyrillic
    (_CJK_RE, 'ja'),         # Japanese for CJK (fallback, not ideal)
    (_ARABIC_RE, 'ar'),
    (_GREEK_RE, 'el'),
    (_THAI_RE, 'th'),
]


def _detect_language(title: str) -> Optional[str]:
    """Detect Wikipedia language code from title characters.

    Returns two-letter code (e.g. 'ru', 'ja') or None for Latin-only (assume en).
    """
    for pattern, lang in _LANG_MAP:
        if pattern.search(title):
            return lang
    return None


# ── Disk cache ────────────────────────────────────────────────────────────────

def _cache_path() -> str:
    xdg = os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache'))
    return os.path.join(xdg, 'namer', 'wikipedia.json')


def _load_cache() -> Dict:
    path = _cache_path()
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_cache(cache: Dict) -> None:
    path = _cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(cache, f, ensure_ascii=False)


# ── API helpers ───────────────────────────────────────────────────────────────

_USER_AGENT = 'namer/1.0 (https://github.com/bortoq/namer)'


def _wiki_api(language: str, params: Dict) -> Optional[Dict]:
    """Call Wikipedia API in *language*, return parsed JSON or None."""
    params['format'] = 'json'
    params['action'] = 'query'
    url = f'https://{language}.wikipedia.org/w/api.php?' + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': _USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _search_page(title: str, language: str) -> Optional[str]:
    """Search Wikipedia in *language* for *title*, return first result's page title.

    Returns None if no page found.
    """
    data = _wiki_api(language, {
        'list': 'search',
        'srsearch': title,
        'srlimit': 3,
    })
    if not data:
        return None
    results = data.get('query', {}).get('search', [])
    if not results:
        return None
    return results[0].get('title') or None


def _get_langlink(page_title: str, from_lang: str, to_lang: str) -> Optional[str]:
    """Get the *to_lang* title for *page_title* on *from_lang* Wikipedia.

    Example: _get_langlink('Невидимый гость', 'ru', 'en') -> 'The Invisible Guest'
    Returns None if not found.
    """
    data = _wiki_api(from_lang, {
        'titles': page_title,
        'prop': 'langlinks',
        'lllang': to_lang,
    })
    if not data:
        return None
    pages = data.get('query', {}).get('pages', {})
    for pid, pdata in pages.items():
        if pid != '-1':  # -1 = page not found
            for link in pdata.get('langlinks', []):
                if link.get('lang') == to_lang:
                    return link.get('*', '')
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def get_english_title(foreign_title: str, source_lang: str = None) -> str:
    """Find the English Wikipedia title for a foreign-language *foreign_title*.

    Args:
        foreign_title: Title in the original language (e.g. 'невидимый гость').
        source_lang: Wikipedia language code (e.g. 'ru', 'ja').
                     If None, auto-detected from characters.

    Returns:
        English title (e.g. 'The Invisible Guest'), or *foreign_title* as-is
        if translation is not available.
    """
    if not foreign_title:
        return foreign_title

    # Auto-detect language if not provided
    if not source_lang:
        source_lang = _detect_language(foreign_title)

    # Latin/unknown → assume already English (or can't translate)
    if not source_lang:
        return foreign_title

    # Check cache
    cache = _load_cache()
    cache_key = f'{foreign_title.strip().lower()}:{source_lang}'
    cached = cache.get(cache_key)
    if cached:
        return cached

    # Search for the page in the source-language Wikipedia
    page_title = _search_page(foreign_title, source_lang)
    if not page_title:
        return foreign_title

    # Get English title via interlanguage link
    en_title = _get_langlink(page_title, source_lang, 'en')
    if not en_title:
        return foreign_title

    # Cache and return
    cache[cache_key] = en_title
    _save_cache(cache)
    return en_title


def enrich_title_via_wiki(meta: Dict) -> Dict:
    """Enrich *meta['title']* with the English title from Wikipedia (if different).

    Only applies to movies (is_series=False).
    Uses the detected source language. If title is already Latin, assumes English.

    Modifies meta in-place and returns it.
    """
    if meta.get('is_series'):
        return meta

    title = meta.get('title', '') or meta.get('show', '')
    if not title:
        return meta

    en_title = get_english_title(title)
    if en_title and en_title != title:
        meta['title'] = en_title
        meta['dot_title'] = re.sub(r'\s+', '.', en_title.strip())

    return meta
