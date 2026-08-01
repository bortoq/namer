"""Wikipedia title translation — find translated title for foreign-language movie names.

Uses the free Wikipedia API (no key required) to search for a page in the
source language and retrieve the translated title via interlanguage links.

Typical usage::

    from namer.wikipedia import enrich_title_via_wiki

    meta = {'title': 'невидимый гость', 'is_series': False}
    enrich_title_via_wiki(meta)           # default target=en
    enrich_title_via_wiki(meta, 'it')     # Italian: 'Contrattempo (film)'
"""

import html
import json
import os
import re
import threading
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

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


def _atomic_json_write(path: str, cache: Dict) -> None:
    """Write *cache* to *path* atomically (safe for concurrent threads)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.tmp.{os.getpid()}.{threading.get_ident()}'
    with open(tmp, 'w') as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp, path)


def _save_cache(cache: Dict) -> None:
    _atomic_json_write(_cache_path(), cache)


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


def _search_pages(title: str, language: str) -> List[str]:
    """Search Wikipedia in *language* for *title*; return all result page titles."""
    data = _wiki_api(language, {
        'list': 'search',
        'srsearch': title,
        'srlimit': 3,
    })
    if not data:
        return []
    return [r.get('title') for r in data.get('query', {}).get('search', []) if r.get('title')]


def _search_page(title: str, language: str) -> Optional[str]:
    """Search Wikipedia in *language* for *title*, return first result's page title.

    Returns None if no page found.
    """
    results = _search_pages(title, language)
    return results[0] if results else None


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


# ── Wikidata entity kinds (P31 "instance of") ───────────────────────────────
# A translation candidate is only trusted when its Wikidata entity looks like
# the same media work as the file: it must be an instance of a film / TV
# series / anime / manga (and, when the file carries a release year, that
# year must match).  Concept pages (darkness, aurora) and disambiguation
# pages are rejected, as is any later search hit that cannot be confirmed.

_FILM_TYPES = frozenset({
    'Q11424',      # film
    'Q1259759',    # television film
    'Q2002065',    # animated film
    'Q210294',     # documentary film
})
_SERIES_TYPES = frozenset({
    'Q5398426',    # television series
    'Q15416',      # television program
    'Q2485448',    # miniseries
    'Q581714',     # television series (alt)
    'Q21191270',   # television series (alt)
    'Q1107',       # anime
    'Q21198342',   # manga series
})
_MEDIA_TYPES = _FILM_TYPES | _SERIES_TYPES | frozenset({
    'Q8261',       # novel
    'Q7725634',    # literary work
})

_ENTITY_CACHE_SUFFIX = 'wikipedia_entity.json'


def _entity_cache_load() -> Dict:
    path = _wiki_cache_path(_ENTITY_CACHE_SUFFIX)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _entity_cache_save(cache: Dict) -> None:
    try:
        _atomic_json_write(_wiki_cache_path(_ENTITY_CACHE_SUFFIX), cache)
    except OSError:
        pass


def _get_wikidata_entity(qid: str) -> Optional[Dict]:
    """Fetch {types: [P31...], year} for a Wikidata item; disk-cached per QID."""
    if not qid:
        return None
    cache = _entity_cache_load()
    if qid in cache:
        return cache[qid]
    try:
        url = f'{_WIKIDATA_API}?action=wbgetentities&ids={qid}&props=claims&format=json'
        req = urllib.request.Request(url, headers={'User-Agent': _USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None
    entity = data.get('entities', {}).get(qid, {})
    claims = entity.get('claims', {})
    types = []
    for cl in claims.get('P31', []):
        dv = cl.get('mainsnak', {}).get('datavalue', {})
        val = dv.get('value', {})
        if isinstance(val, dict) and val.get('id'):
            types.append(val['id'])
    year = None
    for prop in ('P577', 'P580'):
        for cl in claims.get(prop, []):
            t = cl.get('mainsnak', {}).get('datavalue', {}).get('value', {}).get('time', '')
            m = re.match(r'[+-](\d{4})', t or '')
            if m:
                year = int(m.group(1))
                break
        if year:
            break
    if not types and year is None:
        return None  # nothing usable — do not cache
    record = {'types': sorted(types), 'year': year}
    cache[qid] = record
    try:
        _entity_cache_save(cache)
    except Exception:
        pass
    return record


def _get_wikidata_types(qid: str) -> frozenset:
    rec = _get_wikidata_entity(qid)
    return frozenset(rec.get('types') or ()) if rec else frozenset()


def _get_wikidata_year(qid: str) -> Optional[int]:
    rec = _get_wikidata_entity(qid)
    return rec.get('year') if rec else None


# ── Public API ────────────────────────────────────────────────────────────────────────

def get_translated_title(foreign_title: str, target_lang: str = 'en',
                         source_lang: str = None, is_series: Optional[bool] = None,
                         year: Optional[int] = None) -> str:
    """Find the Wikipedia title for *foreign_title* in *target_lang*.

    Args:
        foreign_title: Title in the original language (e.g. 'невидимый гость').
        target_lang: Desired language code (e.g. 'en', 'it', 'de'). Default 'en'.
        source_lang: Wikipedia language code of the source (e.g. 'ru').
                     If None, auto-detected from characters.
        is_series: Whether the file is a TV series (True), a movie (False), or
            unknown (None).  Used to disambiguate homonym titles.
        year: Release/premiere year of the file, if known.  Candidates whose
            Wikidata year does not match are rejected.

    Returns:
        Translated title (e.g. 'The Invisible Guest', 'Contrattempo (film)'),
        or *foreign_title* as-is if translation is not available or the
        matching entity cannot be confirmed.
    """
    if not foreign_title:
        return foreign_title

    # Auto-detect source language if not provided
    if not source_lang:
        source_lang = _detect_language(foreign_title)

    # Latin/unknown script — try English Wikipedia search.
    # English Wikipedia may still find the page (e.g. anime romaji titles).
    # Search resolves redirects, so the first hit for a romaji/foreign title
    # is usually the English-named article ('Yuru Camp' -> 'Laid-Back Camp').
    # Scan ALL results like the non-Latin branch: the first hit can be a
    # concept/person page while the actual media work is the second one
    # ('Mother!' -> 'Mother' concept first, the film second).
    if not source_lang:
        page_titles = _search_pages(foreign_title, 'en')
        translated = None
        for i, page_title in enumerate(page_titles):
            translated = _translated_for_candidate(
                page_title, 'en', target_lang, is_series, year,
                first_result=(i == 0))
            if translated:
                break
        if translated and translated != foreign_title:
            return translated
        return foreign_title

    # If source == target, nothing to do
    if source_lang == target_lang:
        return foreign_title

    # Check cache.  v4 keys include the resolution context (is_series/year)
    # because the same localized title can map to different Wikidata entities
    # for a film vs a series (or different years).  Old v3/unversioned keys
    # are ignored (they may hold context-polluted values).
    cache = _load_cache()
    ctx_series = 'series' if is_series else ('movie' if is_series is False else 'any')
    ctx_year = year if year is not None else ''
    cache_key = (f'v4:{foreign_title.strip().lower()}:{source_lang}:{target_lang}'
                 f':{ctx_series}:{ctx_year}')
    cached = cache.get(cache_key)
    if cached:
        return cached

    # Search for the page in the source-language Wikipedia.  The first hit
    # may be a generic/disambiguation page that is not the movie or series
    # we want ('Тьма' -> the darkness concept), so scan all results.
    page_titles = _search_pages(foreign_title, source_lang)
    if not page_titles:
        return foreign_title

    translated = None
    for i, page_title in enumerate(page_titles):
        translated = _translated_for_candidate(
            page_title, source_lang, target_lang, is_series, year,
            first_result=(i == 0))
        if translated:
            break
    if not translated:
        return foreign_title

    # Cache and return
    cache[cache_key] = translated
    _save_cache(cache)
    return translated


def _translated_for_candidate(page_title: str, from_lang: str, to_lang: str,
                              is_series: Optional[bool], year: Optional[int],
                              first_result: bool) -> Optional[str]:
    """Target-language title of *page_title* if it plausibly matches the file.

    Requires the Wikidata entity to be a media work whose type matches
    *is_series* and whose year matches *year* (when either is known).
    A non-first search hit is only trusted with a year or an explicit
    series context — otherwise the ambiguity is left unresolved and the
    original title is kept.
    """
    qid = _get_wikidata_id(page_title, from_lang)
    if not qid:
        return None
    types = _get_wikidata_types(qid)
    if not (types & _MEDIA_TYPES):
        return None
    if is_series is not None:
        wanted = _SERIES_TYPES if is_series else _FILM_TYPES
        if not (types & wanted):
            return None
    if year is not None:
        entity_year = _get_wikidata_year(qid)
        if entity_year is None or abs(entity_year - year) > 1:
            return None
    elif not first_result and is_series is not True:
        return None
    translated = _get_langlink(page_title, from_lang, to_lang)
    if not translated:
        translated = _get_wikidata_label(qid, to_lang)
    return translated or None


def enrich_title_via_wiki(meta: Dict, target_lang: str = 'en') -> bool:
    """Enrich *meta['title']* with the Wikipedia title in *target_lang* (if different).

    Works for both movies and TV series/anime.
    Source language is auto-detected from the title characters.
    The file context (is_series, year) is passed to the resolver so homonym
    titles are disambiguated against the Wikidata entity.

    Args:
        meta: Metadata dict.
        target_lang: Desired language code (e.g. 'en', 'it', 'de'). Default 'en'.

    Modifies meta in-place.
    Returns True if translation was applied, False if not (no page, already same, etc.).
    """
    title = meta.get('title', '') or meta.get('show', '')
    if not title:
        return False

    translated = get_translated_title(
        title,
        target_lang=target_lang,
        is_series=meta.get('is_series'),
        year=meta.get('year') or None,
    )
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


# ── Episode-list and year extraction ──────────────────────────────────────────

# Sub-headings under which episodes are specials (OVA etc.) → season 0
_SPECIAL_HEADING_RE = re.compile(
    r'original video|original net|ova|oav|oad|special|bonus|extra|omake', re.IGNORECASE
)

# Cache files (separate from translation cache to keep its format stable)
_EP_CACHE_PATH_SUFFIX = 'wikipedia_episodes.json'
_QID_CACHE_PATH_SUFFIX = 'wikipedia_qid.json'


def _wiki_cache_path(suffix: str) -> str:
    xdg = os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache'))
    return os.path.join(xdg, 'namer', suffix)


def _get_wikitext(page_title: str, language: str = 'en') -> str:
    """Return the raw wikitext of *page_title* on *language* Wikipedia.

    Uses the canonical revisions API (prop=wikitext was deprecated upstream).
    """
    data = _wiki_api(language, {
        'prop': 'revisions', 'rvprop': 'content', 'rvslots': 'main',
        'titles': page_title,
    })
    if not data:
        return ''
    pages = data.get('query', {}).get('pages', {})
    for pid, pdata in pages.items():
        if pid != '-1':
            revisions = pdata.get('revisions') or []
            if revisions:
                return revisions[0].get('slots', {}).get('main', {}).get('*', '') or ''
    return ''


def _season_from_page(page_name: str) -> Optional[int]:
    """Extract season number from a page name like 'Show season 2' / 'Show (Series 3)'."""
    m = re.search(r'(?:season|series|saison|temporada|part|volume)\s*(\d{1,2})',
                  page_name, re.IGNORECASE)
    if m:
        s = int(m.group(1))
        if 1 <= s <= 99:
            return s
    return None


def _clean_wiki_title(raw: str) -> str:
    """Clean a wikitext episode title: strip refs, links, templates, quotes."""
    s = raw
    s = html.unescape(s)
    s = re.sub(r'<ref[^>]*/>', '', s)
    s = re.sub(r'<ref[^>]*>.*?</ref>', '', s, flags=re.DOTALL)
    # [[link|display]] → display ; [[link]] → link
    s = re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]*)\]\]', r'\1', s)
    # Unwrap title-bearing templates BEFORE the generic template strip, so the
    # actual title survives: {{lang|xx|Text}} -> Text, {{lang-xx|Text}} -> Text,
    # {{nowrap|Text}} -> Text, {{nihongo|English|...}} -> English.
    s = re.sub(
        r'\{\{\s*lang(?:-[a-z]{2,3})?\s*\|\s*[a-z]{2,3}\s*\|\s*([^|{}]+?)\s*\}\}',
        r'\1', s, flags=re.IGNORECASE)
    s = re.sub(r'\{\{\s*nowrap\s*\|\s*([^|{}]+?)\s*\}\}', r'\1', s,
               flags=re.IGNORECASE)
    s = re.sub(r'\{\{\s*nihongo\s*\|\s*([^|{}]+?)\s*\|.*?\}\}', r'\1', s,
               flags=re.IGNORECASE | re.DOTALL)
    s = re.sub(r'\{\{[^{}]*\}\}', '', s)  # remaining templates
    s = re.sub(r"''+", '', s)  # italics/bold quotes
    s = re.sub(r'&nbsp;', ' ', s)
    s = s.replace('\u200b', '')
    s = re.sub(r'\s+', ' ', s).strip()
    return s.strip('"')


def _parse_episode_blocks(wikitext: str, default_season: Optional[int]) -> List[Tuple[int, int, str]]:
    """Parse `{{Episode list/sublist}}` / `{{Episode list}}` blocks.

    Returns a list of (season, episode, title).  Blocks under special-ish
    headings are mapped to season 0.  Season-relative number (EpisodeNumber2)
    is preferred; falls back to overall EpisodeNumber.
    """
    result: List[Tuple[int, int, str]] = []
    current_heading = ''
    # Walk line by line; track headings to catch OVA/special sections.
    blocks = list(re.finditer(
        r'\{\{Episode\s+list(?:/sublist)?\s*\n(.*?)\n\}\}',
        wikitext, re.DOTALL,
    ))
    for m in blocks:
        block_start = m.start()
        # Determine the nearest heading before the block
        heading_matches = list(re.finditer(
            r'^={1,6}\s*(.*?)\s*={1,6}\s*$', wikitext[:block_start],
            re.MULTILINE,
        ))
        if heading_matches:
            current_heading = heading_matches[-1].group(1)
        body = m.group(1)
        ep_m = re.search(r'\|\s*EpisodeNumber\s*=\s*(\d{1,3})', body)
        ep2_m = re.search(r'\|\s*EpisodeNumber2\s*=\s*(\d{1,3})', body)
        title_m = re.search(r'\|\s*Title\s*=\s*(.+?)(?=\n\s*\||\Z)', body, re.DOTALL)
        translit_m = re.search(r'\|\s*TranslitTitle\s*=\s*(.+?)(?=\n\s*\||\Z)', body, re.DOTALL)
        if not ep_m and not ep2_m:
            continue
        ep_num = int((ep2_m or ep_m).group(1))
        if ep2_m is None:
            # No season-relative number → overall number; only usable for season 1
            ep_num = int(ep_m.group(1))
        raw_title = (title_m or translit_m)
        if not raw_title:
            continue
        title = _clean_wiki_title(raw_title.group(1))
        if not title or len(title) < 2:
            continue
        if _SPECIAL_HEADING_RE.search(current_heading):
            season = 0
        else:
            # A page can hold several seasons inline under '== Season N =='
            # headings (e.g. 'Dark (TV series)'); the heading is more specific
            # than the caller-supplied default.
            heading_season = _season_from_page(current_heading)
            if heading_season is not None:
                season = heading_season
            else:
                season = default_season if default_season is not None else 1
        result.append((season, ep_num, title))
    return result


def fetch_episode_titles(show_title: str, language: str = 'en') -> Dict[Tuple[int, int], str]:
    """Return {(season, episode): title} for *show_title* from Wikipedia.

    Finds the 'List of X episodes' page, follows transcluded season sub-pages
    ({{:Show season N}} / {{Main|Show season N}}), and parses their episode
    tables.  Results are cached on disk.
    """
    if not show_title:
        return {}
    cache = _episode_cache_load()
    key = f'{show_title.strip().lower()}:{language}'
    if key in cache:
        return {(int(k.split(".")[0]), int(k.split(".")[1])): v
                for k, v in cache[key].items()}

    result: Dict[Tuple[int, int], str] = {}
    # 1. Find the "List of ... episodes" page
    list_page = _search_page(f'List of {show_title} episodes', language)
    pages: Dict[str, Optional[int]] = {}
    if list_page:
        wt = _get_wikitext(list_page, language)
        if wt:
            for pat in (r'\{\{:\s*([^}|]+?)\s*\}\}', r'\{\{Main\s*\|([^}|]+?)\s*\}\}'):
                for pm in re.finditer(pat, wt):
                    name = pm.group(1).strip()
                    season = _season_from_page(name)
                    if season and name not in pages:
                        pages[name] = season
    if not pages and list_page:
        pages[list_page] = None  # parse the list page itself
    if not pages:
        # Fallback: search directly for a season-1-style page
        fallback = _search_page(f'{show_title} season 1', language)
        if fallback and _season_from_page(fallback):
            pages[fallback] = _season_from_page(fallback)

    # 2. Parse each page
    for page, season in pages.items():
        wt = _get_wikitext(page, language)
        if not wt:
            continue
        for s, e, title in _parse_episode_blocks(wt, season):
            if (s, e) not in result:  # first source wins
                result[(s, e)] = title

    # Cache
    try:
        cache[key] = {f'{s}.{e}': t for (s, e), t in result.items()}
        _episode_cache_save(cache)
    except Exception:
        pass
    return result


def _episode_cache_load() -> Dict:
    path = _wiki_cache_path(_EP_CACHE_PATH_SUFFIX)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _episode_cache_save(cache: Dict) -> None:
    try:
        _atomic_json_write(_wiki_cache_path(_EP_CACHE_PATH_SUFFIX), cache)
    except OSError:
        pass


# ── Wikidata QID resolution (synonym normalisation) ─────────────────────────

def get_entity_qid(title: str, language: str = 'en') -> Optional[str]:
    """Return the Wikidata QID for *title* (via *language* Wikipedia), cached.

    Two different titles that resolve to the same QID refer to the same
    entity (e.g. 'Yuru Camp' vs 'Laid-Back Camp').
    """
    if not title:
        return None
    cache = _qid_cache_load()
    key = f'{title.strip().lower()}:{language}'
    if key in cache:
        return cache[key]
    qid = None
    page = _search_page(title, language)
    if page:
        qid = _get_wikidata_id(page, language)
    cache[key] = qid
    try:
        _qid_cache_save(cache)
    except Exception:
        pass
    return qid


def _qid_cache_load() -> Dict:
    path = _wiki_cache_path(_QID_CACHE_PATH_SUFFIX)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _qid_cache_save(cache: Dict) -> None:
    try:
        _atomic_json_write(_wiki_cache_path(_QID_CACHE_PATH_SUFFIX), cache)
    except OSError:
        pass


def _year_from_infobox(page_titles: List[str], language: str) -> Optional[int]:
    """Return the earliest premiere year found in infoboxes of *page_titles*."""
    year_re = re.compile(
        r'\|[ ]*(?:first_aired|last_aired|released|air_date|original_release)[ ]*='
        r'[ ]*(?:\{\{[^{}]*\|)?(19|20)\d{2}',
        re.IGNORECASE,
    )
    best = None
    for title in page_titles:
        if not title:
            continue
        wt = _get_wikitext(title, language)
        if not wt:
            continue
        for m in year_re.finditer(wt):
            y = int(re.search(r'(19|20)\d{2}', m.group(0)).group(0))
            if best is None or y < best:
                best = y
        # continue scanning all candidates and take the minimum across them
    return best


def fetch_show_year(show_title: str, language: str = 'en') -> Optional[int]:
    """Extract the premiere/release year from the show's Wikipedia infobox.

    Returns int or None.  Cached in the episode-list cache file.
    """
    if not show_title:
        return None
    cache = _episode_cache_load()
    key = f'year:{show_title.strip().lower()}:{language}'
    if key in cache:
        return cache[key]
    # Earliest premiere year across the franchise: check season-1 page first
    # (a franchise article may only describe later seasons), then the main page.
    candidates = [f'{show_title} season 1', show_title,
                  f'{show_title} (TV series)', f'{show_title} (anime)']
    year = _year_from_infobox(candidates, language)
    if year is None:
        page = _search_page(show_title, language)
        if page:
            year = _year_from_infobox([page], language)
    cache[key] = year
    try:
        _episode_cache_save(cache)
    except Exception:
        pass
    return year
