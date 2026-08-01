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

# Multi-episode detection (token-level): a rename target can only express
# one episode, so a multi-episode file must be skipped rather than silently
# renamed to the first episode number.  Detection is deliberately NOT a single
# growing regex: regex-only matching both misses whitespace/word-separated
# second markers (S01E01 E02, 1x01 and 1x02) and misfires on technical tokens
# with a separator inside (10-bit, 10 bit, 60 fps, 24 fps).  Instead we locate
# the primary episode marker and inspect only the nearest right-hand token(s):
#   * a second full marker (SxxExx / NxNN / E-number)  -> multi-episode;
#   * a bare number after an explicit range separator ('-', '+', '&', 'and'),
#     e.g. S01E01-02                                     -> multi-episode;
#   * a dot/space-separated bare number is ambiguous (numeric episode titles
#     like "S01E01.33", "S01E01.12.Monkeys") and stays single -> single;
#   * a quality/audio/video token (10bit, 60 fps, 5.1, 1080p, 2020) -> single.

# Bare numbers with these values are resolution widths - never a second episode.
_RESOLUTION_WIDTHS = frozenset({'480', '576', '720', '1080', '2160'})

# Unit words that turn a bare number into a technical token (10-bit, 60 fps).
_TECH_NUMBER_UNITS = re.compile(
    r"[\s.\-]*(?:bit|bits|fps|hz|khz|mhz|ch|channels?|kbps|mbps|vbr|cbr)\b",
    re.IGNORECASE,
)


def _strip_video_extension(file_name: str) -> str:
    """Strip a known video extension from a basename, if present."""
    return re.sub(
        r'\.(?:mkv|mp4|avi|m2ts|ts|m4v|mov|wmv|flv|webm|mpg|mpeg|vob|iso)$',
        '', file_name, flags=re.IGNORECASE,
    )


def _second_episode_after_marker(rest: str) -> bool:
    """Inspect the substring after a primary episode marker.

    *rest* is the lowercased basename remainder following the marker.  True
    when the nearest tokens describe a second episode rather than a numeric
    episode title or a quality/audio/video token.
    """
    # Normalize the word separator 'and' to '&' first, so the leading
    # separator run (and its length) is consistent.
    rest = re.sub(r'\band\b', '&', rest, flags=re.IGNORECASE)
    m = re.match(r'[.\s\-_+&,]+', rest)
    sep = m.group(0) if m else ''
    rest = rest[len(sep):]
    # Second full marker: SxxExx / NxNN / bare E-number (E02).  The E-number
    # branch also covers adjacent E-numbers ("S01E01E02" -> remainder "E02").
    if re.match(r'(?:s\d{1,2}e\d{1,3}|\d{1,2}x\d{1,3}|e\d{1,3})(?![0-9])', rest):
        return True
    m = re.match(r'(\d{1,4})', rest)
    if not m:
        return False
    num = m.group(1)
    after = rest[m.end():]
    # Decimal audio channels: 5.1 / 7.1 / 2.0 - number followed by ".digit".
    if re.match(r'\.\d', after):
        return False
    # Technical token: number continued by '-', ' ' or '.' to a unit word
    # (10-bit, 10 bit, 60 fps, 24 fps, 10bit, 24fps).
    if _TECH_NUMBER_UNITS.match(after):
        return False
    # Resolution widths, years and other 4-digit numbers are not episodes.
    if num in _RESOLUTION_WIDTHS or len(num) >= 4:
        return False
    # A bare number is a second episode only after an explicit range
    # separator ('-', '+', '&', 'and').  After '.', ' ' or '_' it is
    # ambiguous (numeric episode titles like "S01E01.33", "S01E01.12.
    # Monkeys") and is left as a single episode instead of a false skip.
    if not any(c in sep for c in '-+&'):
        return False
    return True


def _is_multi_episode(file_name: str) -> bool:
    """Return True when *file_name* represents more than one episode.

    Token-level detection: find the primary episode marker (SxxExx or NxNN)
    and check only the nearest right-hand tokens for a second episode marker
    or a number range.  Quality/audio/video tokens are never read as a second
    episode number.
    """
    base = _strip_video_extension(file_name)
    if not base:
        return False
    lower = base.lower()
    for m in re.finditer(
            r'(?:^|[.\s\-_+&,])+(?:s\d{1,2}e\d{1,3}|\d{1,2}x\d{2,3})', lower):
        if _second_episode_after_marker(lower[m.end():]):
            return True
    return False

# Fallback: standalone episode number like " - 01" (common anime format)
#   Matches 2-3 digit number before quality bracket, end of name, or extension.
#   Excluded: numbers >=1900 (years) and common resolution widths (480/576/720).
_EPISODE_FALLBACK = re.compile(
    r'(?:^|[.\s-])(?P<episode>\d{2,3})(?:\s*v\d+)?(?=\s*[\[\(]|\s*$|\.\w+$|\.\s)',
)

# "1.01." or "12.01." format (already-formatted season.episode.)
_SEASON_DOT_EPISODE = re.compile(
    r'(?:^|[.\s-])(?P<season>\d{1,2})\.(?P<episode>\d{2,3})\.',
)

# NxNN format: 1x02, 2x01, etc.
_SERIES_X_FORMAT = re.compile(
    r'(?:^|[.\s-])(?P<season>\d{1,2})x(?P<episode>\d{2,3})',
    re.IGNORECASE,
)



# "N.N" with a single-digit episode, anchored at the very start of the name
# (e.g. "1.1.mkv", "2.6.mkv" - hand-numbered series rips).  The ^ anchor is
# what keeps audio strings like "DTS.5.1." from matching: they never appear
# at the start of a filename.
_SINGLE_DIGIT_DOT_EPISODE = re.compile(
    r'^(?P<season>\d{1,2})\.(?P<episode>\d)(?:\.|$)',
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
    r'SCREENER|TELESYNC|TELECINE|WORKPRINT|PDTV|SDTV|TVRip)\b',
    re.IGNORECASE
)

# ── Accessory patterns ───────────────────────────────────────────────────

# Episode-type markers: filename contains these → it's a special episode (OVA, etc.)
# Matches bracketed [Special], [OVA], or standalone .Special./.OVA. patterns
# in the original filename before clean_title strips brackets.
_SPECIAL_EPISODE_MARKERS = re.compile(
    r'\[(?:Special|OVA|OAV|OAD|Extra|Movie|Film|Omake|SP|OVD)\]'
    r'|\.(?:Special|OVA|OAV|OAD|Extra|Movie|Film|Omake|SP|OVD)\.',
    re.IGNORECASE
)

def parse_season_episode(file_name: str) -> Tuple[Optional[int], Optional[int]]:
    """Extract (season, episode) from a filename.  Returns (None, None) if nothing found."""
    season, episode, _ = _parse_season_episode_full(file_name)
    return season, episode


def _parse_season_episode_full(file_name: str) -> Tuple[Optional[int], Optional[int], bool]:
    """Extract (season, episode, season_assumed) from a filename.

    *season_assumed* is True when the season is a weak default (1) taken from
    the anime-style fallback patterns (" - 01", "[01]") rather than from an
    explicit marker (Sxx / NxNN / N.NN.).  Voting treats assumed values as
    non-committal: they fill in only when no explicit season exists.
    """
    season_from_series = None  # saved from Sxx match if no Exx found

    # Primary: Sxx or SxxExx
    m = _SERIES_PATTERN.search(file_name)
    if m:
        season = int(m.group('season'))
        episode = int(m.group('episode')) if m.group('episode') else None
        if episode is not None:
            return season, episode, False
        # Sxx without Exx — save season and continue to fallback patterns
        season_from_series = season

    # NxNN format: 1x02, 2x01, etc.
    m = _SERIES_X_FORMAT.search(file_name)
    if m:
        season = int(m.group('season'))
        episode = int(m.group('episode'))
        return season, episode, False

    # Fallback: standalone episode number like " - 01" or ".01." at end
    m = _EPISODE_FALLBACK.search(file_name)
    if m:
        ep = int(m.group('episode'))
        # Filter out years (>=1900) and common resolutions (480/576/720)
        if ep < 1900 and ep not in (480, 576, 720):
            assumed = season_from_series is None
            return (season_from_series or 1), ep, assumed

    # Episode in brackets: [01] or [01_of_74]
    m = _EPISODE_IN_BRACKETS.search(file_name)
    if m:
        ep = int(m.group('episode'))
        if ep < 1900 and ep not in (480, 576, 720):
            assumed = season_from_series is None
            return (season_from_series or 1), ep, assumed

    # "N.NN." format: already-formatted season.episode.
    m = _SEASON_DOT_EPISODE.search(file_name)
    if m:
        season = int(m.group('season'))
        episode = int(m.group('episode'))
        return season, episode, False

    # "N.N." with single-digit episode, anchored at the start
    # (e.g. "1.1.mkv" - hand-numbered series rips).  Never matches mid-name
    # quality strings like "DTS.5.1.".
    m = _SINGLE_DIGIT_DOT_EPISODE.search(file_name)
    if m:
        season = int(m.group('season'))
        episode = int(m.group('episode'))
        return season, episode, False

    # If we had Sxx but no episode was found by any fallback, return (season, None)
    if season_from_series is not None:
        return season_from_series, None, False

    return None, None, False


def extract_ext(file_name: str) -> str:
    """Return file extension without the leading dot."""
    m = _EXT_PATTERN.search(file_name)
    return m.group('ext').lower() if m else ''


def extract_year(file_name: str) -> Optional[int]:
    """Extract release year (last 19xx/20xx from filename)."""
    matches = list(_YEAR_PATTERN.finditer(file_name))
    if matches:
        return int(matches[-1].group('year'))
    return None


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
    name = _SINGLE_DIGIT_DOT_EPISODE.sub('', name)
    name = _SERIES_X_FORMAT.sub('', name)

    # Remove only the last year (release year), keep earlier years like "2001"
    years = list(_YEAR_PATTERN.finditer(name))
    if years:
        last_year = years[-1]
        name = name[:last_year.start()] + name[last_year.end():]

    # Check for release markers BEFORE removal (needed for modifier/group guards)
    has_release_markers = bool(
        _QUALITY_TOKENS.search(name)
        or _SOURCE_TOKENS.search(name)
        or _YEAR_PATTERN.search(name)
    )

    # Remove quality/resolution/codec tokens
    name = _QUALITY_TOKENS.sub('', name)

    # Remove source tokens
    name = _SOURCE_TOKENS.sub('', name)

    # Remove modifiers only if release markers present
    # (avoids eating legitimate title words like "Extended" in "Extended Family")
    if has_release_markers:
        name = strip_modifiers(name)

    # Remove release group at end (-GROUP) only if release markers present
    # Avoids eating legitimate hyphenated words like "Spider-Man", "X-Men".
    if has_release_markers:
        name = re.sub(r'[-. ]*-[-. ]*[a-zA-Z0-9À-ɏ]{2,15}$', '', name.strip())

    # Remove bracketed / parenthesized groups
    name = re.sub(r'\[.*?\]', '', name)
    name = re.sub(r'\(.*?\)', '', name)

    # Replace separators with spaces
    name = re.sub(r'[._-]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()

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
        after = name[m.end():]
        # Strip remaining E markers from multi-episode (e.g. "E02" from "S01E01E02")
        after = re.sub(r'\s*E\d{1,3}\s*', '', after, flags=re.IGNORECASE).strip()
        after = _clean_ep_title(after)
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
    season, episode, season_assumed = _parse_season_episode_full(basename)
    year = extract_year(basename)
    quality: QualityInfo = parse_quality(basename)

    # Extract episode title from filename content after season/ep marker
    # ep_title is no longer scraped from filename — comes only from enrichment

    # When SxxExx is detected, split title/ep_title at the marker boundary
    # This prevents episode name from leaking into the show title
    marker_match = (_SERIES_PATTERN.search(basename)
                    or _SERIES_X_FORMAT.search(basename)
                    or _SEASON_DOT_EPISODE.search(basename)
                    or _SINGLE_DIGIT_DOT_EPISODE.search(basename)
                    or _EPISODE_FALLBACK.search(basename))
    if marker_match:
        before = basename[:marker_match.start()]
        title = clean_title(before) if before.strip() else ''
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
    is_multi_episode = _is_multi_episode(basename)

    # Dot-quality: quality label with dots instead of spaces (torrent-style)
    dot_quality = re.sub(r'\s+', '.', quality_label.strip())

    # Check for special episode markers (OVA, Special, etc.) in the
    # original filename before clean_title strips bracketed content.
    is_special = bool(_SPECIAL_EPISODE_MARKERS.search(basename))

    return {
        'title': title,
        'dot_title': dot_title,
        'dot_quality': dot_quality,
        'is_special': is_special,
        'season': season or 0,
        'episode': episode or 0,
        'season_assumed': bool(season_assumed),
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
        'ep_title': '',
        'is_series': is_series,
        'is_multi_episode': is_multi_episode,
    }
