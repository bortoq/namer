"""Build provider evidence feeds for metadata arbitration.

Local providers (no network): filename, dirname, file (ffprobe).
Online providers: wikipedia, tvmaze, tmdb.

Each provider returns a :class:`namer.provider_opinion.ProviderOpinion`: a
typed, per-field candidate with confidence.  The legacy flat dict is
projected via ``opinion.values`` so the existing voting engine and template
rendering keep working unchanged.
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

from namer.parser import parse_file, title_from_path, _SERIES_PATTERN
from namer.provider_opinion import ProviderOpinion
from namer.identify.models import FieldCandidate

# Legacy alias: old code (notebooks, tests) imported ``Feed`` and built
# ``Feed(provider, values)``.  ``Feed`` is now the same object.
Feed = ProviderOpinion

# parse_file fields that vote as-is when non-empty (technical/naming fields).
_FILENAME_FIELDS = ('quality', 'resolution', 'source', 'codec', 'audio', 'hdr', 'mod')
# Default confidence for those fields when present in the filename.
_FILENAME_FIELD_CONF = dict.fromkeys(_FILENAME_FIELDS, 0.8)


# ── Local providers ──────────────────────────────────────────────────────────

def filename_feed(file_path: str, known_title: str = '') -> ProviderOpinion:
    """Feed from the file's own name (the identity source for S/E)."""
    meta = parse_file(file_path)
    op = ProviderOpinion('filename')

    title = known_title or meta.get('title', '')
    if title:
        op.set('title', title, 0.9)

    is_special = meta.get('is_special', False)
    season = meta.get('season', 0)
    episode = meta.get('episode', 0)

    # Specials are deliberately mapped to season 0 (standard convention);
    # this is NOT an assumption, so clear the weak flag.
    if is_special and season == 1:
        season = 0
        meta['season_assumed'] = False

    # season=0 means "not found" unless the file is a special.
    if season != 0 or is_special:
        op.set('season', season, 0.9)
    if episode:
        op.set('episode', episode, 0.9)
    if meta.get('season_assumed'):
        # Assumed seasons vote weakly: confidence reflects the guess.  We
        # rebuild the season candidate with a lower confidence (FieldCandidate
        # is frozen) rather than mutating it.
        if 'season' in op.fields:
            op.fields['season'] = FieldCandidate(
                op.fields['season'].value, 0.6, op.fields['season'].sources)
        op.meta['season_assumed'] = True

    for f in _FILENAME_FIELDS:
        v = meta.get(f)
        if v not in (None, '', 'Unknown'):
            op.set(f, v, _FILENAME_FIELD_CONF[f])

    if meta.get('year'):
        op.set('year', meta['year'], 0.8)

    return op


_SEASON_JAPANESE = {
    'shi': 4, 'san': 3, 'ni': 2, 'two': 2, 'go': 5,
    'roku': 6, 'nana': 7, 'shichi': 7, 'hachi': 8,
    'kyuu': 9, 'ku': 9, 'juu': 10,
}
_SEROMS = {'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'v': 5,
           'vi': 6, 'vii': 7, 'viii': 8, 'ix': 9, 'x': 10}


def _season_from_directories(file_path: str) -> Optional[int]:
    """Walk up the directory tree looking for an explicit season indicator.

    Mirrors core.py's directory heuristic: Sxx / "Season N" / "Part N" /
    "Specials" / Japanese number words / Roman numerals / trailing digits.
    Returns None if nothing is found.
    """
    start = os.path.dirname(os.path.abspath(file_path))
    parent = start
    while parent:
        dirname = os.path.basename(parent)
        if not dirname or dirname == os.path.sep:
            break

        m = _SERIES_PATTERN.search(dirname)
        if m:
            s = int(m.group('season'))
            if s:
                return s
        m = re.search(r'season\s*(\d{1,2})', dirname, re.IGNORECASE)
        if m:
            s = int(m.group(1))
            if s:
                return s
        m = re.search(r'(?:part|vol|volume)\s*(\d{1,2})', dirname, re.IGNORECASE)
        if m:
            s = int(m.group(1))
            if s:
                return s
        if dirname.lower() in ('specials', 'special'):
            return 0

        # Compare dir with its parent: an extra suffix may be the season
        # indicator (e.g. "Natsume Yuujinchou Shi" under "Natsume Yuujinchou").
        next_parent = os.path.dirname(parent)
        parent_name = os.path.basename(next_parent) if next_parent and next_parent != parent else ''
        if parent_name:
            norm = lambda s: re.sub(r'[._\s\-\[\]()]+', ' ', s).strip().lower()
            pn, dn = norm(parent_name), norm(dirname)
            suffix = ''
            if dn.startswith(pn + ' '):
                suffix = dn[len(pn):].strip()
                if suffix:
                    for word, season_num in _SEASON_JAPANESE.items():
                        if re.search(rf'\b{word}\b', suffix):
                            return season_num
                    for rom, season_num in _SEROMS.items():
                        if re.search(rf'\b{rom}\b', suffix):
                            return season_num

        m = re.search(r'(?:^|[\s.])(\d{1,2})$', dirname)
        if m:
            s = int(m.group(1))
            if 1 <= s <= 50:
                return s

        parent = os.path.dirname(parent)
    return None


def dirname_feed(file_path: str) -> ProviderOpinion:
    """Feed from the directory tree (show name + explicit season folders)."""
    op = ProviderOpinion('dirname')
    dir_title = title_from_path(file_path)
    if dir_title:
        op.set('title', dir_title, 0.7)
    season = _season_from_directories(file_path)
    if season is not None:
        op.set('season', season, 0.8)
    return op


def file_feed(file_path: str) -> ProviderOpinion:
    """Feed from ffprobe (technical metadata + container tags)."""
    op = ProviderOpinion('file')
    try:
        from namer.ffprobe import enrich_from_file, get_format_metadata
        fmeta = enrich_from_file(file_path)
        if fmeta.get('codec'):
            op.set('codec', fmeta['codec'], 0.95)
        if fmeta.get('resolution'):
            op.set('resolution', f"{fmeta['resolution']}p", 0.95)
        if fmeta.get('audio'):
            op.set('audio', fmeta['audio'], 0.95)
        if fmeta.get('channels'):
            op.set('channels', fmeta['channels'], 0.9)
        if fmeta.get('hdr'):
            op.set('hdr', fmeta['hdr'], 0.95)
        tags = get_format_metadata(file_path)
        if tags.get('show_name'):
            op.set('title', tags['show_name'], 0.8)
        if tags.get('season'):
            op.set('season', tags['season'], 0.8)
        if tags.get('episode'):
            op.set('episode', tags['episode'], 0.8)
    except (ImportError, FileNotFoundError):
        pass
    return op


# ── Online providers ─────────────────────────────────────────────────────────

def wikipedia_feed(meta: Dict, language: str) -> ProviderOpinion:
    """Feed from Wikipedia: canonical/translated title, premiere year, ep titles.

    *meta* must already carry the title enriched by core (translation pass).
    Episode-title votes only happen when the S/E hint is explicit — with an
    assumed season the lookup target is unreliable, so we abstain instead of
    guessing a possibly-wrong episode title.
    """
    op = ProviderOpinion('wikipedia')
    try:
        from namer.wikipedia import fetch_episode_titles, fetch_show_year
        title = meta.get('title', '')
        if not title:
            op.abstain = True
            return op
        op.set('title', title, 0.9)
        year = fetch_show_year(title, language)
        if year:
            op.set('year', year, 0.85)
        if meta.get('is_series') and meta.get('episode') and not meta.get('season_assumed'):
            season = 0 if meta.get('is_special') else meta.get('season', 0)
            eps = fetch_episode_titles(title, language)
            ep_title = eps.get((season, meta['episode']))
            if ep_title:
                op.set('ep_title', ep_title, 0.9)
    except Exception:
        op.abstain = True
    return op


def tvmaze_feed(meta: Dict, language: str) -> ProviderOpinion:
    """Feed from TVmaze: canonical show name, premiere year, episode title."""
    op = ProviderOpinion('tvmaze')
    try:
        from namer.tvmaze import enrich_episode_titles
        m = dict(meta)
        enrich_episode_titles(m, language=language)
        if m.get('title'):
            op.set('title', m['title'], 0.9)
        if m.get('year'):
            op.set('year', m['year'], 0.85)
        if m.get('ep_title') and not meta.get('season_assumed'):
            op.set('ep_title', m['ep_title'], 0.9)
    except Exception:
        op.abstain = True
    return op


def tmdb_feed(meta: Dict, tmdb_key: str, language: str) -> ProviderOpinion:
    """Feed from TMDB: localized title, year, episode title (requires key)."""
    op = ProviderOpinion('tmdb')
    if not tmdb_key:
        op.abstain = True
        return op
    try:
        from namer.enricher import enrich_meta
        m = dict(meta)
        enrich_meta(m, tmdb_key, language)
        if m.get('title'):
            op.set('title', m['title'], 0.9)
        if m.get('year'):
            op.set('year', m['year'], 0.9)
        if m.get('ep_title') and not meta.get('season_assumed'):
            op.set('ep_title', m['ep_title'], 0.9)
    except Exception:
        op.abstain = True
    return op


# ── Orchestration ────────────────────────────────────────────────────────────

def local_feeds(file_path: str, known_title: str = '') -> List[ProviderOpinion]:
    """Local (no-network) feeds: filename, dirname, file (ffprobe)."""
    return [
        filename_feed(file_path, known_title),
        dirname_feed(file_path),
        file_feed(file_path),
    ]


def online_feeds(meta: Dict, tmdb_key: str = '', language: str = 'en') -> List[ProviderOpinion]:
    """Online feeds: wikipedia, tvmaze, (tmdb if key given).

    *meta* must carry the resolved title/season/episode hints — online feeds
    confirm the episode identity and provide canonical names, but never vote
    on season/episode themselves.
    """
    if not meta.get('title'):
        return []
    feeds = [
        wikipedia_feed(meta, language),
        tvmaze_feed(meta, language),
    ]
    if tmdb_key:
        feeds.append(tmdb_feed(meta, tmdb_key, language))
    return feeds


def collect_feeds(file_path: str, meta: Dict, known_title: str = '',
                  tmdb_key: str = '', language: str = 'en') -> List[ProviderOpinion]:
    """Build local + online feeds for *file_path* (single-pass helper)."""
    return local_feeds(file_path, known_title) + online_feeds(meta, tmdb_key, language)
