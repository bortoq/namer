"""Wikipedia title translation — find translated title for foreign-language movie names.

Uses the free Wikipedia API (no key required) to search for a page in the
source language and retrieve the translated title via interlanguage links.

Typical usage::

    from namer.wikipedia import enrich_title_via_wiki

    meta = {'title': 'невидимый гость', 'is_series': False}
    enrich_title_via_wiki(meta)           # default target=en
    enrich_title_via_wiki(meta, 'it')     # Italian: 'L'ospite invisibile'
"""

import json
import os
import re
import urllib.parse
import urllib.request
from typing import Dict, Optional

# ── Known Wikipedia languages ──────────────────────────────────────────────────

# Active Wikipedia language codes (from API sitematrix, 374 languages)
_KNOWN_LANGUAGES = frozenset({
    "aa", "ab", "ace", "ady", "af", "ak", "als", "alt", "am", "ami", "an", "ang",
    "ann", "anp", "ar", "arc", "ary", "arz", "as", "ast", "atj", "av", "avk", "awa",
    "ay", "az", "azb", "ba", "ban", "bar", "bat-smg", "bbc", "bcl", "bdr", "be",
    "be-tarask", "be-x-old", "bew", "bg", "bh", "bi", "bjn", "blk", "bm", "bn", "bo",
    "bol", "bpy", "br", "bs", "btm", "bug", "bxr", "ca", "cbk-zam", "cdo", "ce", "ceb",
    "ch", "cho", "chr", "chy", "ckb", "co", "cr", "crh", "cs", "csb", "cu", "cv", "cy",
    "da", "dag", "de", "dga", "din", "diq", "dsb", "dtp", "dty", "dv", "dz", "ee", "el",
    "eml", "en", "eo", "es", "et", "eu", "ext", "fa", "fat", "ff", "fi", "fiu-vro", "fj",
    "fo", "fon", "fr", "frp", "frr", "fur", "fy", "ga", "gag", "gan", "gcr", "gd", "gl",
    "glk", "gn", "gom", "gor", "got", "gpe", "gsw", "gu", "guc", "gur", "guw", "gv", "ha",
    "hak", "haw", "he", "hi", "hif", "ho", "hr", "hsb", "ht", "hu", "hy", "hyw", "hz",
    "ia", "iba", "id", "ie", "ig", "igl", "ii", "ik", "ilo", "inh", "io", "is", "isv",
    "it", "iu", "ja", "jam", "jbo", "jv", "ka", "kaa", "kab", "kai", "kaj", "kbd", "kbp",
    "kcg", "kg", "kge", "ki", "kj", "kk", "kl", "km", "kn", "knc", "ko", "koi", "kr",
    "krc", "ks", "ksh", "ku", "kus", "kv", "kw", "ky", "la", "lad", "lb", "lbe", "lez",
    "lfn", "lg", "li", "lij", "lld", "lmo", "ln", "lo", "lrc", "lt", "ltg", "lv", "lzh",
    "mad", "mag", "mai", "map-bms", "mdf", "mg", "mh", "mhr", "mi", "min", "mk", "ml",
    "mn", "mni", "mnw", "mo", "mos", "mr", "mrj", "ms", "mt", "mus", "mwl", "my", "myv",
    "mzn", "na", "nah", "nan", "nap", "nds", "nds-nl", "ne", "new", "ng", "nia", "nl",
    "nn", "no", "nov", "nqo", "nr", "nrm", "nso", "nup", "nv", "ny", "oc", "olo", "om",
    "or", "os", "pa", "pag", "pam", "pap", "pcd", "pcm", "pdc", "pfl", "pi", "pih", "pl",
    "pms", "pnb", "pnt", "ppl", "ps", "pt", "pwn", "qu", "rki", "rm", "rmy", "rn", "ro",
    "roa-rup", "roa-tara", "rsk", "ru", "rue", "rup", "rw", "sa", "sah", "sat", "sc",
    "scn", "sco", "sd", "se", "sg", "sgs", "sh", "shi", "shn", "shy", "si", "simple",
    "sk", "skr", "sl", "sm", "smn", "sn", "so", "sq", "sr", "srn", "ss", "st", "stq",
    "su", "sv", "sw", "syl", "szl", "szy", "ta", "tay", "tcy", "tdd", "te", "tet", "tg",
    "th", "ti", "tig", "tk", "tl", "tly", "tn", "to", "tok", "tpi", "tr", "trv", "ts",
    "tt", "tum", "tw", "ty", "tyv", "udm", "ug", "uk", "ur", "uz", "ve", "vec", "vep",
    "vi", "vls", "vo", "vro", "wa", "war", "wo", "wuu", "xal", "xh", "xmf", "yi", "yo",
    "yue", "za", "zea", "zgh", "zh", "zh-classical", "zh-min-nan", "zh-yue", "zu",
})


def is_valid_language(code: str) -> bool:
    """Check if *code* is a known active Wikipedia language code."""
    return code in _KNOWN_LANGUAGES


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


# ── Wikidata helpers ──────────────────────────────────────────────────────────

_WIKIDATA_API = 'https://www.wikidata.org/w/api.php'


def _get_wikidata_id(page_title: str, language: str) -> Optional[str]:
    """Get the Wikidata item ID (QID) for a Wikipedia page.

    Args:
        page_title: Page title on *language* Wikipedia.
        language: Wikipedia language code.

    Returns:
        QID string (e.g. 'Q28114432') or None.
    """
    data = _wiki_api(language, {
        'titles': page_title,
        'prop': 'pageprops',
        'ppprop': 'wikibase_item',
    })
    if not data:
        return None
    pages = data.get('query', {}).get('pages', {})
    for pid, pdata in pages.items():
        if pid != '-1':
            return pdata.get('pageprops', {}).get('wikibase_item')
    return None


def _get_wikidata_label(qid: str, target_lang: str) -> Optional[str]:
    """Get the label for a Wikidata item in *target_lang*.

    Args:
        qid: Wikidata item ID (e.g. 'Q28114432').
        target_lang: Desired language code.

    Returns:
        Label string or None if not available.
    """
    try:
        url = f'{_WIKIDATA_API}?action=wbgetentities&ids={qid}&props=labels&languages={target_lang}&format=json'
        req = urllib.request.Request(url, headers={'User-Agent': _USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        entity = data.get('entities', {}).get(qid, {})
        label = entity.get('labels', {}).get(target_lang, {})
        return label.get('value')
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────────────────────

def get_translated_title(foreign_title: str, target_lang: str = 'en', source_lang: str = None) -> str:
    """Find the Wikipedia title for *foreign_title* in *target_lang*.

    Args:
        foreign_title: Title in the original language (e.g. 'невидимый гость').
        target_lang: Desired language code (e.g. 'en', 'it', 'de'). Default 'en'.
        source_lang: Wikipedia language code of the source (e.g. 'ru').
                     If None, auto-detected from characters.

    Returns:
        Translated title (e.g. 'The Invisible Guest', 'L'ospite invisibile'),
        or *foreign_title* as-is if translation is not available.
    """
    if not foreign_title:
        return foreign_title

    # Auto-detect source language if not provided
    if not source_lang:
        source_lang = _detect_language(foreign_title)

    # Latin/unknown script — try English Wikipedia search.
    # English Wikipedia may still find the page (e.g. anime romaji titles).
    if not source_lang:
        page_title = _search_page(foreign_title, 'en')
        if page_title:
            qid = _get_wikidata_id(page_title, 'en')
            if qid:
                translated = _get_wikidata_label(qid, target_lang)
                if translated and translated != foreign_title:
                    return translated
        return foreign_title

    # If source == target, nothing to do
    if source_lang == target_lang:
        return foreign_title

    # Check cache
    cache = _load_cache()
    cache_key = f'{foreign_title.strip().lower()}:{source_lang}:{target_lang}'
    cached = cache.get(cache_key)
    if cached:
        return cached

    # Search for the page in the source-language Wikipedia
    page_title = _search_page(foreign_title, source_lang)
    if not page_title:
        return foreign_title

    # Get target-language title via interlanguage link
    translated = _get_langlink(page_title, source_lang, target_lang)
    if not translated:
        # Fallback: get Wikidata label in the target language.
        # This is more reliable than search-based fallbacks because Wikidata
        # is the central hub that all Wikipedia editions link to.
        qid = _get_wikidata_id(page_title, source_lang)
        if qid:
            translated = _get_wikidata_label(qid, target_lang)

    if not translated:
        return foreign_title

    # Cache and return
    cache[cache_key] = translated
    _save_cache(cache)
    return translated


def enrich_title_via_wiki(meta: Dict, target_lang: str = 'en') -> bool:
    """Enrich *meta['title']* with the Wikipedia title in *target_lang* (if different).

    Works for both movies and TV series/anime.
    Source language is auto-detected from the title characters.

    Args:
        meta: Metadata dict.
        target_lang: Desired language code (e.g. 'en', 'it', 'de'). Default 'en'.

    Modifies meta in-place.
    Returns True if translation was applied, False if not (no page, already same, etc.).
    """
    title = meta.get('title', '') or meta.get('show', '')
    if not title:
        return False

    translated = get_translated_title(title, target_lang=target_lang)
    if translated and translated != title:
        # Clean up Wikipedia disambiguation suffixes: "(film)", "(film, 2016)", etc.
        clean = re.sub(
            r'\s*\(\s*(?:film|pel[íi]cula|movie|tv series|serie|film\s*,\s*\d{4})[^)]*\)\s*$',
            '', translated, flags=re.IGNORECASE,
        ).strip()
        meta['title'] = clean or translated
        meta['dot_title'] = re.sub(r'\s+', '.', (clean or translated).strip())
        return True

    return False
