"""Identify a media file from its filename.

Pure, offline, deterministic: only answers "what is this file and how
confident are we".  No network, no renaming, no ambiguity resolution — that
is the job of the upper layers that consume :class:`~namer.identify.Identity`.
"""
import re
from typing import Optional

from namer.identify.models import (
    Decision, Evidence, FieldCandidate, IdentificationWarning, Identity,
    IdentifyInput, MediaType, Status,
)
from namer.parser import (
    split_title_with_marker, extract_ext, extract_year, series_episode_numbers,
    _parse_season_episode_full, _episode_from_marker, _SPECIAL_EPISODE_MARKERS,
    _RESOLUTION_WIDTHS, _TECH_NUMBER_UNITS,
)
from namer.quality import parse_quality

_EXT_RE = re.compile(r'\.([a-z0-9]+)$', re.IGNORECASE)
_MARKER_RE = re.compile(
    r'(?:^|[.\s\-_+&/]+)(?:s\d{1,2}e\d{1,3}|\d{1,2}x\d{2,3})', re.IGNORECASE)


def _stem(basename: str) -> str:
    return _EXT_RE.sub('', basename, count=1)


def _first_marker_number(basename: str) -> Optional[int]:
    m = _MARKER_RE.search(_stem(basename).lower())
    return _episode_from_marker(m.group(0)) if m else None


def _numeric_tail_warning(basename: str) -> Optional[IdentificationWarning]:
    """Warn about a likely numeric episode title after a marker.

    Fires only for a bare number that is not a second episode, a year, a
    resolution or a technical token ("S01E01-33").  Such a file is treated as
    a single episode, but the numeric tail is ambiguous.
    """
    m = _MARKER_RE.search(_stem(basename).lower())
    if not m:
        return None
    rest = _stem(basename)[m.end():]
    rest = re.sub(r'^[.\s\-_+&/]+', '', rest)
    n = re.match(r'(\d{1,4})', rest)
    if not n:
        return None
    num = n.group(1)
    after = rest[n.end():]
    if re.match(r'\.\d', after) or _TECH_NUMBER_UNITS.match(after):
        return None
    if num in _RESOLUTION_WIDTHS or len(num) >= 4:
        return None
    first = _first_marker_number(basename)
    try:
        second = int(num)
    except ValueError:
        return None
    # A plausible adjacent range is handled as a multi-episode file; the
    # remaining case is a numeric episode title.
    return IdentificationWarning(
        'numeric-episode-title-maybe', 'episode',
        f'numeric token {num!r} after the marker may be an episode title, '
        'not an episode range')


def identify_filename(input: "IdentifyInput") -> "Identity":
    """Identify a media file.  No network, no side effects."""
    basename = input.basename()
    ide = Identity()
    if not basename:
        ide.status = Status.UNRESOLVED
        return ide

    title = split_title_with_marker(basename)
    year = extract_year(basename)
    season, episode, assumed = _parse_season_episode_full(basename)
    eps = series_episode_numbers(basename)
    quality = parse_quality(basename)
    ide.ext = extract_ext(basename)
    ide.is_special = bool(_SPECIAL_EPISODE_MARKERS.search(basename))
    ide.season_assumed = bool(assumed)
    ide.quality = {
        'label': quality.quality_label or 'Unknown',
        'resolution': f'{quality.resolution}p' if quality.resolution else '',
        'source': quality.source,
        'codec': quality.codec,
        'audio': quality.audio,
        'hdr': quality.hdr,
        'mod': '/'.join(quality.modifiers) if quality.modifiers else '',
    }

    if title:
        media_confidence = 0.9 if season is not None else 0.8
        ide.title = FieldCandidate(title, media_confidence, ['filename'])
        ide.evidence.append(Evidence('filename', 'title', title))

    if year is not None:
        ide.year = FieldCandidate(year, 0.9, ['filename'])
        ide.evidence.append(Evidence('filename', 'year', str(year)))

    if season is not None:
        conf = 0.7 if assumed else 0.95
        ide.media_type = MediaType.SERIES_EPISODE
        ide.season = FieldCandidate(season, conf, ['filename'])
        ide.evidence.append(Evidence('filename', 'season', str(season)))
        if episode is not None:
            ide.episode = FieldCandidate(episode, conf, ['filename'])
            ide.evidence.append(Evidence('filename', 'episode', str(episode)))
    elif title:
        ide.media_type = MediaType.MOVIE
    else:
        ide.media_type = MediaType.UNKNOWN

    if ide.media_type is MediaType.SERIES_EPISODE:
        if len(eps) >= 2:
            ide.episodes = [FieldCandidate(v, 0.9, ['filename']) for v in eps]
            ide.is_multi_episode = Decision(
                True, 0.95, ['_, filename'], 'multiple episodes in one file')
            ide.evidence.append(
                Evidence('filename', 'multi_tokens', ','.join(map(str, eps))))
        else:
            if eps:
                ide.episodes = [FieldCandidate(eps[0], 0.9, ['filename'])]
            ide.is_multi_episode = Decision(
                False, 0.9, ['filename'], 'single episode')

    if _SPECIAL_EPISODE_MARKERS.search(basename):
        ide.evidence.append(Evidence('filename', 'special', basename))
        ide.media_type = MediaType.SERIES_EPISODE

    # A numeric tail is only ambiguous for a *single* episode: a genuine
    # adjacent range is high-confidence multi-episode, not a title number.
    if not ide.is_multi_episode_value:
        warn = _numeric_tail_warning(basename)
        if warn:
            ide.warnings.append(warn)

    if ide.media_type is MediaType.UNKNOWN:
        ide.status = Status.UNRESOLVED
    elif ide.warnings:
        ide.status = Status.AMBIGUOUS
    else:
        ide.status = Status.IDENTIFIED

    return ide
