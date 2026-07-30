"""File metadata parser — extracts season/episode, quality, year, clean title."""

import os
import re
from typing import Optional, Tuple

from namer.quality import parse_quality, strip_modifiers, QualityInfo

# ── Patterns (adapted from sator/normalizer.py and sator/title.py) ───────

# Primary: Sxx or SxxExx
_SERIES_PATTERN = re.compile(
    r'(?:^|[.\s-])+S(?P<season>\d{1,2})(?:E(?P<episode>\d{1,3}))?',
    re.IGNORECASE,
)

# Fallback: standalone episode number like " - 01" (common anime format)
#   Matches 2-3 digit number before quality bracket, end of name, or extension.
#   Excluded: numbers >=1900 (years) and common resolution widths (480/576/720).
_EPISODE_FALLBACK = re.compile(
    r'(?:^|[.\s-])(?P<episode>\d{2,3})(?:\s*v\d+)?(?=\s*[\[\(]|\s*$|\.\w+$)',
)

# "1.01." or "12.01." format (already-formatted season.episode.)
_SEASON_DOT_EPISODE = re.compile(
    r'(?:^|[.\s-])(?P<season>\d{1,2})\.(?P<episode>\d{2,3})\.',
)

# Episode in brackets: [01] or [01_of_74] (common anime format)
_EPISODE_IN_BRACKETS = re.compile(
    r'\[(?P<episode>\d{2,3})(?:_of_\d+)?\]',
)

# Year: 4 digits, not preceded by word char, not followed by letter or "p" or "i"
_YEAR_PATTERN = re.compile(r'(?<![a-zA-Z])(?P<year>(?:19|20)\d{2})(?![a-zA-Z]|p|i)')

_EXT_PATTERN = re.compile(r'\.(?P<ext>[a-zA-Z0-9]+)$')

# Quality/resolution tokens to strip during title cleaning
_QUALITY_TOKENS = re.compile(
    r'\b(?:'
    r'480[ip]|576[ip]|720[ip]|1080[ip]|2160[ip]'
    r'|UHD|4K'
    r'|[xh]\.?26[45]|HEVC|AV1|VP9|Xvid|Divx|AVC'
    r'|DD\W?5[. ]1|DDP?5[. ]1'
    r'|AAC5[. ]1|TrueHD|DTS[ -]HD|DTS|FLAC|AAC|AC3|MP3|PCM|Opus'
    r'|8bit|10bit|8-bit|10-bit'
    r'|HDR10?|Dolby[. ]?Vision|DOVI|DV|HLG'
    r'|HDR|SDR'
    r'|x265|h\.265'
    r'|848x480|1280x720|1920x1080|3840x2160|4096x2160'
    r'|Remux'
    r'|MULTi|DUAL[. ]?AUDIO|5[. ]1|7[. ]1|2[. ]0'
    r')\b', re.IGNORECASE
)

_SOURCE_TOKENS = re.compile(
    r'\b(?:BluRay|WEB[-_. ]?DL|WEBRip|BDRip|BRRip|HDTV|DVD|DVDR|'
    r'SCREENER|TELESYNC|TELECINE|CAM|WORKPRINT|PDTV|SDTV|TVRip)\b',
    re.IGNORECASE
)

# ── Accessory patterns ───────────────────────────────────────────────────

def parse_season_episode(file_name: str) -> Tuple[Optional[int], Optional[int]]:
    """Extract (season, episode) from a filename.

    Tries Sxx/SxxExx first, then standalone episode number (anime format).
    Returns (None, None) if nothing found.
    """
    # Primary: Sxx or SxxExx
    m = _SERIES_PATTERN.search(file_name)
    if m:
        season = int(m.group('season'))
        episode = int(m.group('episode')) if m.group('episode') else None
        return season, episode

    # Fallback: standalone episode number like " - 01"
    m = _EPISODE_FALLBACK.search(file_name)
    if m:
        ep = int(m.group('episode'))
        # Filter out years (>=1900) and common resolutions (480/576/720)
        if ep < 1900 and ep not in (480, 576, 720):
            return 1, ep  # default season 1

    # Episode in brackets: [01] or [01_of_74]
    m = _EPISODE_IN_BRACKETS.search(file_name)
    if m:
        ep = int(m.group('episode'))
        if ep < 1900 and ep not in (480, 576, 720):
            return 1, ep

    # "N.NN." format: already-formatted season.episode.
    m = _SEASON_DOT_EPISODE.search(file_name)
    if m:
        season = int(m.group('season'))
        episode = int(m.group('episode'))
        return season, episode

    return None, None


def extract_ext(file_name: str) -> str:
    """Return file extension without the leading dot."""
    m = _EXT_PATTERN.search(file_name)
    return m.group('ext').lower() if m else ''


def extract_year(file_name: str) -> Optional[int]:
    """Extract a 4-digit year from the filename."""
    m = _YEAR_PATTERN.search(file_name)
    return int(m.group('year')) if m else None


def clean_title(file_name: str) -> str:
    """Derive a clean show/movie title from the filename.

    Strips extension, season/episode markers, quality tokens, source,
    year, modifiers, release groups, bracketed/parenthesized groups.
    Returns a space-separated title.
    """
    name = file_name.replace('_', ' ')

    # Remove extension
    name = re.sub(r'\.(mkv|mp4|avi|m2ts|ts|m4v|mov|wmv|flv|webm|mpg|mpeg|vob|iso)$',
                  '', name, flags=re.IGNORECASE)

    # Remove season/episode (primary + fallback)
    name = _SERIES_PATTERN.sub('', name)
    name = _EPISODE_FALLBACK.sub('', name)
    name = _SEASON_DOT_EPISODE.sub('', name)

    # Remove year
    name = _YEAR_PATTERN.sub('', name)

    # Remove quality/resolution/codec tokens
    name = _QUALITY_TOKENS.sub('', name)

    # Remove source tokens
    name = _SOURCE_TOKENS.sub('', name)

    # Remove modifiers
    name = strip_modifiers(name)

    # Remove release group at end: -GROUP (common p2p patterns)
    # Matches dash optionally surrounded by dots/spaces (e.g. ".-.GetSchwifty")
    # But requires at least one dash — avoids eating ".Thrones" from "Game.of.Thrones"
    name = re.sub(r'[-. ]*-[-. ]*[a-zA-Z0-9À-ɏ]{2,15}$', '', name.strip())

    # Remove bracketed / parenthesized groups
    name = re.sub(r'\[.*?\]', '', name)
    name = re.sub(r'\(.*?\)', '', name)

    # Replace separators with spaces
    name = re.sub(r'[._-]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()

    # Preserve original casing (user can pass title arg for custom name)

    return name




def _is_generic_dir(name: str) -> bool:
    """Return True if *name* looks like a generic/numeric directory (season folder, etc.)."""
    generic = {'downloads', 'video', 'videos', 'tv', 'movies', 'series',
               'anime', 'season', 'seasons', 'episodes', 'specials',
               'complete', 'batch', 'vol', 'volume', 'disc', 'disk',
               'media', 'data', 'mnt', 'storage', 'shared', 'home',
               'library', 'collection', 'shows', 'films', 'cartoons', 'user',
               'tmp', 'temp', 'var', 'opt', 'usr', 'etc', 'root',
               'private', 'system', 'system32', 'windows', 'program',
               'programs', 'program files'}
    lower = name.lower().strip()
    # Normalise: collapse multiple spaces, replace underscores with spaces
    normalised = re.sub(r'[\s_]+', ' ', lower).strip()
    # Check whole normalised name
    if normalised in generic:
        return True
    # Check each word — if ALL words are generic, it's a generic dir
    words = normalised.split()
    if all(w in generic for w in words):
        return True
    # Pure number (season folder like "1", "2", "01")
    if re.match(r'^\d{1,2}$', normalised):
        return True
    # "Season 1", "S01", "season 02", "Season 01"
    if re.match(r'^(?:season\s*|s)\d{1,2}$', normalised):
        return True
    # "TV Shows", "TV Series", "TV Anime" etc.
    if normalised.startswith('tv ') or normalised == 'tv':
        return True
    # Temp dir pattern: "tmpXXXXXX", "tempXXXXXX", "tmp_XXXXXX" 
    # (tempfile-style random names — check against any segment or whole)
    for word in words:
        if re.match(r'^(?:tmp|temp)[\da-z]{3,}$', word):
            return True
    # Also check the whole name with spaces removed
    no_spaces = normalised.replace(' ', '')
    if re.match(r'^(?:tmp|temp)[\da-z_]{3,}$', no_spaces):
        return True
    return False


def title_from_path(file_path: str) -> str:
    """Walk up the directory tree to find a meaningful show/movie title.

    Skips generic/season/numeric directories, collecting the non-generic
    directory levels closest to the file (max 3 levels) as the show name.

    Example: ``/media/video/anime/Angel Beats!/1/episode.mkv``
    1. Skip "1" (numeric season folder)
    2. Collect "Angel Beats!" (non-generic)
    3. Stop at "anime" (generic collection folder)
    Returns "Angel Beats!"

    Joins nearby non-generic parts for multi-word titles:
    ``.../The Summer/Hikaru/Died/Season 1/episode.mkv`` → "The Summer Hikaru Died"

    Returns empty string if nothing meaningful found.
    """
    parts = []
    parent = os.path.dirname(os.path.abspath(file_path))
    collecting = False

    while parent:
        dirname = os.path.basename(parent)
        if not dirname or dirname == os.path.sep:
            break

        is_generic = _is_generic_dir(dirname)

        if collecting:
            # Stop at next generic dir or when we have collected 3+ levels
            if is_generic or len(parts) >= 3:
                break
            cleaned = clean_title(dirname)
            if len(cleaned) >= 2 and (not parts or cleaned != parts[-1]):
                parts.append(cleaned)
            parent = os.path.dirname(parent)
            continue

        # Not yet collecting: skip generic dirs (season numbers, etc.)
        if is_generic:
            parent = os.path.dirname(parent)
            continue

        # Found first non-generic dir — start collecting
        collecting = True
        cleaned = clean_title(dirname)
        if len(cleaned) >= 2:
            parts.append(cleaned)
        parent = os.path.dirname(parent)

    # Deduplicate consecutive identical entries (e.g. parent + subdir with same show name)
    deduped = []
    for p in parts:
        if not deduped or p != deduped[-1]:
            deduped.append(p)
    parts = deduped

    if not parts:
        return ''

    # Join collected parts from bottom (closest to file) to top
    candidate = ' '.join(reversed(parts))
    if len(candidate) >= 3:
        return candidate

    return parts[-1] if len(parts[-1]) >= 3 else ''

def extract_ep_title_from_filename(file_name: str) -> str:
    """Extract episode title from content after a season/episode marker.

    Handles both N.NN. format ("1.01. Departure.mkv" → "Departure")
    and SxxExx format ("Show S01E01 Episode.mkv" → "Episode").
    Preserves leading triple-dot ellipsis ("S01E17...In Translation" → "...In Translation").
    Returns empty string if no episode title found.
    """
    name = re.sub(r'\.(mkv|mp4|avi|m2ts|ts|m4v|mov|wmv|flv|webm|mpg|mpeg|vob|iso)$',
                  '', file_name, flags=re.IGNORECASE)

    def _clean_ep_title(raw: str) -> str:
        """Clean an episode title extracted after the marker."""
        s = raw.strip()
        s = _QUALITY_TOKENS.sub('', s)
        s = _SOURCE_TOKENS.sub('', s)
        s = re.sub(r'\[.*?\]', '', s)
        s = re.sub(r'\(.*?\)', '', s)
        # Preserve leading triple-dot ellipsis (part of episode title)
        # Replace internal dots/dashes with spaces, but NOT leading ...
        if s.startswith('...'):
            suffix = s[3:].lstrip()
            suffix = re.sub(r'[._-]', ' ', suffix)
            suffix = re.sub(r'\s+', ' ', suffix).strip()
            return '...' + suffix if suffix else '...'
        s = re.sub(r'[._-]', ' ', s)
        s = re.sub(r'\s+', ' ', s).strip()
        return s

    # Try N.NN. format first (already-formatted files)
    m = _SEASON_DOT_EPISODE.search(name)
    if m:
        after = _clean_ep_title(name[m.end():])
        if after and len(after) >= 2:
            return after

    # Try SxxExx format
    m = _SERIES_PATTERN.search(name)
    if m:
        after = _clean_ep_title(name[m.end():])
        if after and len(after) >= 2:
            return after

    return ""
def parse_file(file_path: str) -> dict:
    """Parse a video file path and extract all available metadata.

    Returns a dict with keys matching the template placeholders:
        title, dot_title, season, episode, ext, year, quality,
        resolution, source, codec, audio, hdr, mod, is_series.
    """
    basename = os.path.basename(file_path)

    ext = extract_ext(basename)
    season, episode = parse_season_episode(basename)
    year = extract_year(basename)
    quality: QualityInfo = parse_quality(basename)

    # Extract episode title from filename content after season/ep marker
    ep_title_fn = extract_ep_title_from_filename(basename)

    # When SxxExx is detected, split title/ep_title at the marker boundary
    # This prevents episode name from leaking into the show title
    marker_match = _SERIES_PATTERN.search(basename) or _SEASON_DOT_EPISODE.search(basename)
    if marker_match:
        before = basename[:marker_match.start()]
        title = clean_title(before) if before.strip() else (clean_title(basename) if not ep_title_fn else '')
        # If no content before the marker (e.g. "S01E01.mkv"), title stays empty
        # and will be filled later by directory heuristic or -t flag
    else:
        # No season/ep marker — use whole filename as title (movie or unknown)
        title = clean_title(basename)

    # Modifiers string
    mod_str = '/'.join(quality.modifiers) if quality.modifiers else ''

    # Quality label
    quality_label = quality.quality_label or 'Unknown'

    # Dot-title (torrent-style)
    dot_title = re.sub(r'\s+', '.', title.strip())

    is_series = season is not None

    # Dot-quality: quality label with dots instead of spaces (torrent-style)
    dot_quality = re.sub(r'\s+', '.', quality_label.strip())

    return {
        'title': title,
        'dot_title': dot_title,
        'dot_quality': dot_quality,
        'season': season or 0,
        'episode': f'{episode:02d}' if episode else 0,
        'ext': ext,
        'year': year or 0,
        'quality': quality_label,
        'resolution': f'{quality.resolution}p' if quality.resolution else '',
        'source': quality.source,
        'codec': quality.codec,
        'audio': quality.audio,
        'hdr': quality.hdr,
        'mod': mod_str,
        'group': '',
        'ep_title': ep_title_fn,
        'is_series': is_series,
    }
