"""TMDB lookup for episode titles and movie info.

Best-effort: all functions return empty/default if no API key is available.

API key sources (in order of precedence):
  1. ``api_key`` parameter passed directly
  2. ``tmdb_key`` line in ``~/.config/namer/config``
  3. ``TMDB_API_KEY`` environment variable
"""

import json
import os
import re
import time
import urllib.parse
import urllib.request
from typing import Dict, Optional

# ── Config ──────────────────────────────────────────────────────────────────
CONFIG_PATH = os.path.expanduser('~/.config/namer/config')
CACHE_DIR = os.path.expanduser('~/.cache/namer')
CACHE_TTL = 7 * 24 * 3600  # 7 days

# ── Cache ────────────────────────────────────────────────────────────────────
_episode_cache: Optional[dict] = None
_inmemory_cache: Dict[str, str] = {}


def _load_episode_cache() -> dict:
    global _episode_cache
    if _episode_cache is not None:
        return _episode_cache
    path = os.path.join(CACHE_DIR, 'episodes.json')
    try:
        with open(path) as f:
            raw = json.load(f)
        now = time.time()
        result = {}
        for key, entry in raw.items():
            if now - entry.get('_cached_at', 0) > CACHE_TTL:
                continue
            titles = entry.get('titles', {})
            if titles:
                result[key] = {int(k): v for k, v in titles.items()}
        _episode_cache = result
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        _episode_cache = {}
    return _episode_cache


def _save_episode_cache(cache: dict):
    path = os.path.join(CACHE_DIR, 'episodes.json')
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        now = time.time()
        to_save = {k: {'titles': v, '_cached_at': now} for k, v in cache.items()}
        with open(path, 'w') as f:
            json.dump(to_save, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


# ── Key loading ──────────────────────────────────────────────────────────────
def _load_tmdb_key() -> str:
    # 1. Config file
    try:
        with open(CONFIG_PATH) as f:
            for line in f:
                if line.strip().startswith('tmdb_key'):
                    return line.split('=', 1)[1].strip()
    except OSError:
        pass
    # 2. Environment variable
    return os.environ.get('TMDB_API_KEY', '')


def _resolve_key(api_key: str = '') -> str:
    return api_key or _load_tmdb_key()


# ── HTTP helpers ─────────────────────────────────────────────────────────────
_UA = 'Namer/0.1 (https://github.com/bortoq/namer)'
_TIMEOUT = 10


def _tmdb_get(endpoint: str, api_key: str, params: dict = None) -> Optional[dict]:
    if not api_key:
        return None
    url = f'https://api.themoviedb.org/3/{endpoint.lstrip("/")}'
    params = dict(params or {})
    params['api_key'] = api_key
    url += '?' + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': _UA})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


# ── Public API ───────────────────────────────────────────────────────────────

def get_tv_show_id(show_name: str, api_key: str = '', language: str = 'en') -> Optional[int]:
    """Get TMDB TV show ID by name. Returns None if not found."""
    key = _resolve_key(api_key)
    if not key:
        return None
    clean = re.sub(r'\b(?:19|20)\d{2}\b', '', show_name).strip()
    clean = re.sub(r'\s+', ' ', clean).strip() or show_name
    data = _tmdb_get('search/tv', key, {'query': clean, 'language': language})
    if data and data.get('results'):
        return data['results'][0].get('id')
    return None


def get_season_episode_titles(
    show_name: str,
    season_number: int,
    api_key: str = '',
    language: str = 'en',
) -> Dict[int, str]:
    """Get mapping {episode_num: title} for a TV season from TMDB.

    Returns empty dict if lookup fails or no API key.
    Results are cached on disk for 7 days.
    """
    key = _resolve_key(api_key)
    if not key:
        return {}

    cache_key = f'{show_name.lower().strip()}:{season_number}:{language}'
    episode_cache = _load_episode_cache()
    cached = episode_cache.get(cache_key)
    if cached is not None:
        return cached

    show_id = get_tv_show_id(show_name, key, language)
    if not show_id:
        return {}

    data = _tmdb_get(f'tv/{show_id}/season/{season_number}', key, {'language': language})
    if not data or not data.get('episodes'):
        return {}

    result: Dict[int, str] = {}
    for ep in data['episodes']:
        ep_num = ep.get('episode_number')
        ep_name = ep.get('name', '').strip()
        if ep_num and ep_name:
            result[ep_num] = ep_name

    if result:
        episode_cache[cache_key] = result
        _save_episode_cache(episode_cache)
    return result


def search_movie(title: str, api_key: str = '', language: str = 'en') -> Optional[dict]:
    """Search for a movie by title on TMDB.

    Returns first result dict with keys: title, year, id.
    Returns None if not found or no API key.
    """
    key = _resolve_key(api_key)
    if not key:
        return None
    data = _tmdb_get('search/movie', key, {'query': title, 'language': language})
    if data and data.get('results'):
        r = data['results'][0]
        year = ''
        if r.get('release_date') and len(r['release_date']) >= 4:
            year = r['release_date'][:4]
        return {'title': r.get('title', ''), 'year': year, 'id': r.get('id')}
    return None


def enrich_year(title: str, api_key: str = '', language: str = 'en') -> Optional[int]:
    """Try to fetch release year for a movie title from TMDB.

    Returns year as int, or None if not found.
    """
    key = _resolve_key(api_key)
    if not key:
        return None

    # Check in-memory cache
    cache_key = f'year:{title.lower().strip()}:{language}'
    if cache_key in _inmemory_cache:
        val = _inmemory_cache[cache_key]
        return int(val) if val else None

    # Try TV first, then movie
    tv_data = _tmdb_get('search/tv', key, {'query': title, 'language': language})
    if tv_data and tv_data.get('results'):
        r = tv_data['results'][0]
        year_str = r.get('first_air_date', '') or r.get('release_date', '')
        if len(year_str) >= 4:
            year = int(year_str[:4])
            _inmemory_cache[cache_key] = str(year)
            return year

    movie = search_movie(title, key)
    if movie and movie['year']:
        year = int(movie['year'])
        _inmemory_cache[cache_key] = str(year)
        return year

    _inmemory_cache[cache_key] = ''
    return None
