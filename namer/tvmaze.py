"""Episode title lookup via TVmaze API (free, no key required).

Uses the public TVmaze API to search for shows and fetch episode names.

Typical usage::

    from namer.tvmaze import enrich_episode_titles

    meta = {'title': 'The Summer Hikaru Died', 'season': 1, 'episode': 1}
    enrich_episode_titles(meta)
    # meta['ep_title'] == 'Replacement'
"""

import json
import os
import re
import string
import urllib.request
import urllib.parse
from typing import Dict, List, Optional, Tuple


# ── Tiny disk cache ──────────────────────────────────────────────────────────

def _cache_path() -> str:
    """Return path to the TVmaze JSON cache file."""
    xdg = os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache'))
    return os.path.join(xdg, 'namer', 'tvmaze.json')


def _load_cache() -> Dict:
    """Load cached show→episodes mapping from disk."""
    path = _cache_path()
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_cache(cache: Dict) -> None:
    """Persist *cache* to disk."""
    path = _cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(cache, f)


# ── API calls ────────────────────────────────────────────────────────────────

def _api_get(path: str, params: Dict = None) -> Optional[Dict]:
    """Make a GET request to the TVmaze API.

    Returns parsed JSON dict on success, None on any error.
    """
    url = f'https://api.tvmaze.com{path}'
    if params:
        url += '?' + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'namer/1.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError,
            json.JSONDecodeError, OSError):
        return None


def _search_variants(title: str) -> List[str]:
    """Generate search query variants for *title*.

    Tries progressively more aggressive normalisation.
    """
    variants = [title]  # original first
    stripped = title.strip()
    if stripped != title:
        variants.append(stripped)

    # Without punctuation (use a set of chars to avoid regex escaping issues)
    punct_chars = set(string.punctuation)
    no_punct = ''.join(c for c in stripped if c not in punct_chars)
    no_punct = re.sub(r'\s+', ' ', no_punct).strip()
    if no_punct and no_punct != stripped:
        variants.append(no_punct)

    # Without leading articles
    article_stripped = re.sub(
        r'^(?:the|a|an|les|le|la|el|las|los|der|das|die|un|une|ein|eine)\s+',
        '', stripped, flags=re.IGNORECASE,
    ).strip()
    if article_stripped and article_stripped != stripped:
        variants.append(article_stripped)

    # Without trailing generic words
    trailer_stripped = re.sub(
        r'\s+(?:the\s+series|the\s+anime|the\s+tv\s+series|the\s+show|tv)$',
        '', stripped, flags=re.IGNORECASE,
    ).strip()
    if trailer_stripped and trailer_stripped != stripped:
        variants.append(trailer_stripped)

    return variants


def search_show(title: str, language: str = 'en') -> Optional[int]:
    """Search TVmaze for *title* and return the best-matching show ID.

    Tries multiple query variants (original, without punctuation,
    without leading articles) to find the best match.
    Returns None if no match found.
    """
    variants = _search_variants(title)
    seen = set()

    for query in variants:
        if query in seen:
            continue
        seen.add(query)
        data = _api_get('/search/shows', {'q': query, 'language': language})
        if not data:
            continue
        # Check for exact match first
        for entry in data:
            show = entry.get('show', {})
            if show.get('name', '').lower() == query.lower():
                return show['id']
        # Fall back to first result if score is reasonable (>= 0.5)
        first_entry = data[0]
        score = first_entry.get('score', 0) if first_entry else 0
        if score >= 0.5:
            return first_entry['show']['id']

    # Last try: use the first result of any variant with data
    for query in variants:
        if query in seen:
            continue
        seen.add(query)
        data = _api_get('/search/shows', {'q': query, 'language': language})
        if data:
            return data[0]['show']['id']
    return None


def get_all_episodes(show_id: int, language: str = 'en') -> List[Dict]:
    """Return ALL episodes (regular + specials) for *show_id*.

    Fetches each season's full episode list via /seasons/{sid}/episodes,
    which includes ``insignificant_special`` entries not returned by
    the top-level /shows/{id}/episodes endpoint.

    Each entry:: {'season': 1, 'number': 1, 'name': 'Pilot', 'type': 'regular'}
    Specials have ``number: None`` and ``type: 'insignificant_special'``.
    Returns empty list on any error.
    """
    seasons = _api_get(f'/shows/{show_id}/seasons')
    if not seasons:
        return []

    result = []
    for season in seasons:
        sid = season.get('id')
        if not sid:
            continue
        eps = _api_get(f'/seasons/{sid}/episodes', {'language': language})
        if not eps:
            continue
        for ep in eps:
            result.append({
                'season': ep.get('season', 0),
                'number': ep.get('number'),  # may be None for specials
                'name': ep.get('name', ''),
                'type': ep.get('type', 'regular'),
            })
    return result


def get_episodes(show_id: int, language: str = 'en') -> List[Dict]:
    """Return only regular episodes (backward-compat wrapper)."""
    return [ep for ep in get_all_episodes(show_id, language)
            if ep.get('type') == 'regular']


def enrich_episode_titles(meta: Dict, protect_filename: bool = False, language: str = 'en') -> Dict:
    """Look up episode titles from TVmaze and fill *meta['ep_title']*.

    Args:
        meta: Metadata dict with at least ``title``, ``season``, ``episode``.
        protect_filename: If True, keep the existing ``ep_title`` value
            (assumed to come from the filename) and do NOT override with
            TVmaze data.  Default False.
        language: Two-letter language code (e.g. 'en', 'ru', 'de').

    Uses a disk cache so repeated lookups for the same show are instant.
    Will try multiple search variants if the first query fails.

    Modifies *meta* in-place and returns it for convenience.
    """
    if not meta.get('is_series'):
        return meta
    if meta.get('season') is None or not meta.get('episode'):
        return meta

    title = meta.get('title', '') or meta.get('show', '')
    if not title:
        return meta

    season = int(meta['season']) if not isinstance(meta['season'], int) else meta['season']
    episode = meta['episode']  # already int

    # If protect_filename is True, keep what we already have
    had_ep_title = bool(meta.get('ep_title'))
    if protect_filename and had_ep_title:
        return meta

    cache = _load_cache()

    # Cache hit? (include language in key)
    cache_key = f"{title.lower().strip()}:{language}"
    show_id = None
    if cache_key in cache:
        episodes = cache[cache_key]
    else:
        show_id = search_show(title, language)
        if not show_id:
            return meta
        episodes = get_episodes(show_id, language)
        if not episodes:
            return meta
        cache[cache_key] = episodes
        _save_cache(cache)

    # If we didn't search above (cache hit), try to get show_id now
    if show_id is None:
        show_id = search_show(title, language)

    # Also fetch/cache ALL episodes (incl. specials) for specials lookup.
    # Stored under a separate key to not break existing cache entries.
    all_key = cache_key + ':all'
    if all_key not in cache and show_id:
        all_eps = get_all_episodes(show_id, language)
        if all_eps:
            cache[all_key] = all_eps
            _save_cache(cache)

    # Find the matching episode
    if meta.get('is_special'):
        # Specials match by positional index (episode N -> Nth special).
        # Only works when get_all_episodes was used (not legacy cache).
        all_eps = cache.get(cache_key + ':all')
        if all_eps:
            specials = [ep for ep in all_eps if ep.get('type') != 'regular']
            idx = episode - 1  # 1-based -> 0-based
            if 0 <= idx < len(specials):
                name = specials[idx].get('name')
                if name:
                    meta['ep_title'] = name
    else:
        # Regular episodes match by season + number
        for ep in episodes:
            if ep['season'] == season and ep['number'] == episode:
                if ep['name']:
                    meta['ep_title'] = ep['name']
                break

    return meta
