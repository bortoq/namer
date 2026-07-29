"""Enrichment coordinator — uses TMDB to fill episode titles and movie years.

Usage::

    from namer.enricher import enrich_meta

    meta = {'title': 'Breaking Bad', 'season': 1, 'episode': 1, 'year': 0}
    enrich_meta(meta, tmdb_key='abc123')
    # meta['ep_title'] = 'Pilot'
    # meta['year'] = 2008
"""

from namer.tmdb import get_season_episode_titles, enrich_year


def enrich_meta(meta: dict, tmdb_key: str = '', language: str = 'en') -> dict:
    """Enrich *meta* dict with episode titles and year from TMDB.

    Modifies meta in-place AND returns it for convenience.

    For series files: looks up episode title via TMDB, sets ``meta['ep_title']``.
    For movie files: looks up year via TMDB if year is 0.

    Args:
        meta: Metadata dict.
        tmdb_key: TMDB API key.
        language: Two-letter language code (e.g. 'en', 'ru', 'de').
    """
    if not tmdb_key:
        return meta

    if meta.get('is_series') and meta.get('season') and meta.get('episode'):
        show_name = meta.get('title', '') or meta.get('show', '')
        if show_name:
            titles = get_season_episode_titles(show_name, meta['season'], tmdb_key, language)
            if titles:
                ep_title = titles.get(meta['episode'], '')
                if ep_title:
                    meta['ep_title'] = ep_title

    if not meta.get('is_series') and not meta.get('year'):
        show_name = meta.get('title', '') or meta.get('show', '')
        if show_name:
            year = enrich_year(show_name, tmdb_key, language)
            if year:
                meta['year'] = year

    return meta
