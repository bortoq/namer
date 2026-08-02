"""File metadata parser — extracts season/episode, quality, year, clean title."""

import os
import re
from typing import Optional, Tuple

from namer.quality import (parse_quality, QualityInfo,
                              MODIFIER_NON_FIRST_PATTERN, BLACK_BARS_TAG)

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
#   * a bare number close to the first episode (a real range like S01E01-02,
#     S03E07-08, E099-100) after a range separator ('-', '+', '&', 'and', '_')
#                                                      -> multi-episode;
#   * an arbitrary bare number (S01E01-33, S01E01-42) is a numeric episode
#     title, not a range                              -> single;
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

# A bare number is a second episode only when it is close to the first one.
# Arbitrary values ("S01E01-33", "S03E07-42") are numeric episode titles.
_MAX_RANGE_GAP = 2


def _strip_video_extension(file_name: str) -> str:
    """Strip a known video extension from a basename, if present."""
    return re.sub(
        r'\.(?:mkv|mp4|avi|m2ts|ts|m4v|mov|wmv|flv|webm|mpg|mpeg|vob|iso)$',
        '', file_name, flags=re.IGNORECASE,
    )


def _episode_from_marker(marker: str) -> int:
    """Extract the episode number from a primary marker ('.S01E01' -> 1, '1x01' -> 1)."""
    m = re.search(r'(?:s\d{1,2}e|e|x)(\d{1,3})', marker)
    return int(m.group(1)) if m else 0


def _episode_number_from_marker(marker: str) -> int:
    """Episode number inside a second marker ('.S01E01' -> 1, '1x02' -> 2, 'E03' -> 3)."""
    m = re.search(r'(?:s\d{1,2}e|e|x)(\d{1,3})', marker)
    return int(m.group(1)) if m else 0


def _second_episode_after_marker(rest: str, first_episode: int) -> Optional[int]:
    """Inspect the substring after a primary episode marker.

    *rest* is the lowercased basename remainder following the marker; the
    *first_episode* number comes from the marker itself.  Returns the second
    episode number when the nearest tokens describe a second episode, else
    None (numeric episode title or a quality/audio/video token).
    """
    # Normalize the word separator 'and' to '&' first, so the leading
    # separator run (and its length) is consistent.
    rest = re.sub(r'\band\b', '&', rest, flags=re.IGNORECASE)
    m = re.match(r'[.\s\-_+&,]+', rest)
    sep = m.group(0) if m else ''
    rest = rest[len(sep):]
    # Second full marker: SxxExx / NxNN / bare E-number (E02).  The E-number
    # branch also covers adjacent E-numbers ("S01E01E02" -> remainder "E02").
    fm = re.match(r'((?:s\d{1,2}e|\d{1,2}x|e)\d{1,3})(?![0-9])', rest)
    if fm:
        return _episode_number_from_marker(fm.group(1))
    m = re.match(r'(\d{1,4})', rest)
    if not m:
        return None
    num = m.group(1)
    after = rest[m.end():]
    # Decimal audio channels: 5.1 / 7.1 / 2.0 - number followed by ".digit".
    if re.match(r'\.\d', after):
        return None
    # Technical token: number continued by '-', ' ' or '.' to a unit word
    # (10-bit, 10 bit, 60 fps, 24 fps, 10bit, 24fps).
    if _TECH_NUMBER_UNITS.match(after):
        return None
    # Resolution widths, years and other 4-digit numbers are not episodes.
    if num in _RESOLUTION_WIDTHS or len(num) >= 4:
        return None
    # A bare number is a second episode only when (a) it follows a range
    # separator ('-', '+', '&', 'and', or '_' which commonly replaces a dash)
    # in ranges like "S01E01_02") and (b) it is close to the first episode.
    # An arbitrary number ("S01E01-33", "S03E07-42") is a numeric episode
    # title, not a range; dot/space separators stay ambiguous (single).
    if not any(c in sep for c in '-+&_'):
        return None
    try:
        second = int(num)
    except ValueError:
        return None
    if second <= first_episode or second - first_episode > _MAX_RANGE_GAP:
        return None
    return second


def _is_multi_episode(file_name: str) -> bool:
    """Return True when *file_name* represents more than one episode.

    Token-level detection: find the primary episode marker (SxxExx or NxNN)
    and check only the nearest right-hand tokens for a second episode marker
    or an adjacent number range.  Quality/audio/video tokens are never read
    as a second episode number.
    """
    base = _strip_video_extension(file_name)
    if not base:
        return False
    lower = base.lower()
    for m in re.finditer(
            r'(?:^|[.\s\-_+&,])+(?:s\d{1,2}e\d{1,3}|\d{1,2}x\d{2,3})', lower):
        first_episode = _episode_from_marker(m.group(0))
        if _second_episode_after_marker(lower[m.end():], first_episode) is not None:
            return True
    return False


def series_episode_numbers(file_name: str) -> tuple:
    """Return the episode numbers of *file_name*.

    Single episode -> ``(episode,)``; multi-episode -> ``(first, second)``;
    empty tuple when no episode can be resolved.
    """
    base = _strip_video_extension(file_name)
    if base:
        lower = base.lower()
        for m in re.finditer(
                r'(?:^|[.\s\-_+&,])+(?:s\d{1,2}e\d{1,3}|\d{1,2}x\d{2,3})', lower):
            first_episode = _episode_from_marker(m.group(0))
            second = _second_episode_after_marker(lower[m.end():], first_episode)
            if second is not None:
                return (first_episode, second)
    _, episode, _ = _parse_season_episode_full(file_name)
    if episode is not None:
        return (episode,)
    return ()

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


def _title_case_uniform_latin(title: str) -> str:
    """Title-case a uniformly-cased Latin title ("MALICE" -> "Malice").

    Fires only when every letter is ASCII (Latin) and all letters share one
    case — i.e. the name carries no mixed-case title information.  Mixed-case
    titles ("Gone Girl", "Mieruko chan") and non-Latin titles (Cyrillic etc.)
    are left untouched so real capitalization and foreign names survive.
    """
    if not title:
        return title
    letters = [c for c in title if c.isalpha()]
    if not letters:
        return title
    if not all(c.isascii() for c in letters):
        return title
    if not (all(c.isupper() for c in letters)
            or all(c.islower() for c in letters)):
        return title
    return ' '.join(w.capitalize() if w else w for w in title.split())


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

    # Check for release markers BEFORE the year is removed — the release year
    # itself is a marker, and modifiers sit after it ("Gone Girl (2014).Uncut",
    # "American Psycho (2000) uncut").  Computing the flag after year removal
    # leaves the modifier words stuck in the title.
    has_release_markers = bool(
        _QUALITY_TOKENS.search(name)
        or _SOURCE_TOKENS.search(name)
        or _YEAR_PATTERN.search(name)
    )

    # Remove only the last year (release year), keep earlier years like "2001"
    years = list(_YEAR_PATTERN.finditer(name))
    if years:
        last_year = years[-1]
        name = name[:last_year.start()] + name[last_year.end():]

    # Remove quality/resolution/codec tokens
    name = _QUALITY_TOKENS.sub('', name)

    # Remove source tokens
    name = _SOURCE_TOKENS.sub('', name)

    # "uncut_black" — the video keeps its (uncropped) black bars; a
    # video-technical tag, not an edition modifier.  Strip the whole
    # compound so neither word reaches the title.
    name = BLACK_BARS_TAG.sub('', name)

    # Remove modifiers only if release markers present, and never the first
    # word of a title (avoids eating legitimate titles like "Uncut Gems" or
    # "Extended Family" whose first word coincides with a modifier name).
    if has_release_markers:
        name = MODIFIER_NON_FIRST_PATTERN.sub('', name)

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

    return _title_case_uniform_latin(name)





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

    Thin adapter over the identification layer: the identifying fields come
    from :func:`namer.identify.identify_filename` (single source of truth),
    and the legacy flat dict is projected for template placeholders.

    Returns a dict with keys matching the template placeholders:
        title, dot_title, season, episode, ext, year, quality,
        resolution, source, codec, audio, hdr, mod, is_series.
    """
    from namer.identify import identify_filename, IdentifyInput,         MediaType, Status

    basename = os.path.basename(file_path)
    ide = identify_filename(IdentifyInput(filename=basename))

    title = ide.title_value or ''
    season = ide.season.value if ide.season else None
    episode = ide.episode.value if ide.episode else None
    year = ide.year_value
    q = ide.quality or {}

    quality_label = q.get('label') or 'Unknown'

    # Dot-title (torrent-style)
    dot_title = re.sub(r'\s+', '.', title.strip())
    # Dot-quality: quality label with dots instead of spaces (torrent-style)
    dot_quality = re.sub(r'\s+', '.', quality_label.strip())

    return {
        'title': title,
        'dot_title': dot_title,
        'dot_quality': dot_quality,
        'is_special': ide.is_special,
        'season': season or 0,
        'episode': episode or 0,
        'season_assumed': bool(ide.season_assumed),
        'ext': ide.ext,
        'year': year or 0,
        'quality': quality_label,
        'resolution': q.get('resolution') or '',
        'source': q.get('source') or '',
        'codec': q.get('codec') or '',
        'audio': q.get('audio') or '',
        'hdr': q.get('hdr') or '',
        'mod': q.get('mod') or '',
        'group': '',
        'ep_title': '',
        'is_series': season is not None,
        'is_multi_episode': ide.is_multi_episode_value,
    }


def split_title_with_marker(file_name: str) -> str:
    """Split the title at a season/episode marker boundary.

    When SxxExx (variants) is detected, the show title is the text *before*
    the marker, so an episode name after the marker never leaks into the show
    title.  Without a marker the whole file name is the title.
    """
    marker_match = (_SERIES_PATTERN.search(file_name)
                    or _SERIES_X_FORMAT.search(file_name)
                    or _SEASON_DOT_EPISODE.search(file_name)
                    or _SINGLE_DIGIT_DOT_EPISODE.search(file_name)
                    or _EPISODE_FALLBACK.search(file_name))
    if marker_match:
        before = file_name[:marker_match.start()]
        return clean_title(before) if before.strip() else ''
    return clean_title(file_name)
