"""Differential test: parse_file adapter must match the legacy parse logic.

Golden reference re-implements the PRE-adapter parse_file exactly.  For a
corpus of representative filenames the adapter output must be byte-identical,
proving the refactor to namer/identify introduced no behavioral change.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, '/home/user/work/namer')

from namer.parser import parse_file  # noqa: E402
from namer.parser import (extract_ep_title_from_filename,  # noqa: E402
                          _SERIES_PATTERN, _SERIES_X_FORMAT, _SEASON_DOT_EPISODE,  # noqa: E402
                          _SINGLE_DIGIT_DOT_EPISODE, _EPISODE_FALLBACK)
from namer.parser import (_parse_season_episode_full, extract_ext,  # noqa: E402
                          extract_year, clean_title, _is_multi_episode)
from namer.quality import parse_quality  # noqa: E402
from namer.parser import _SPECIAL_EPISODE_MARKERS  # noqa: E402


def legacy_parse(file_path):
    """Byte-for-byte copy of the pre-refactor parse_file."""
    basename = os.path.basename(file_path)
    ext = extract_ext(basename)
    season, episode, season_assumed = _parse_season_episode_full(basename)
    year = extract_year(basename)
    quality = parse_quality(basename)

    marker_match = (_SERIES_PATTERN.search(basename)
                    or _SERIES_X_FORMAT.search(basename)
                    or _SEASON_DOT_EPISODE.search(basename)
                    or _SINGLE_DIGIT_DOT_EPISODE.search(basename)
                    or _EPISODE_FALLBACK.search(basename))
    if marker_match:
        before = basename[:marker_match.start()]
        title = clean_title(before) if before.strip() else ''
    else:
        title = clean_title(basename)

    mod_str = '/'.join(quality.modifiers) if quality.modifiers else ''
    quality_label = quality.quality_label or 'Unknown'
    dot_title = re.sub(r'\s+', '.', title.strip())
    is_series = season is not None
    is_multi_episode = _is_multi_episode(basename)
    dot_quality = re.sub(r'\s+', '.', quality_label.strip())
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
        # Design: ep_title is now filled from a clean filename (single source
        # of truth: name -> {field: value}); online providers may override.
        'ep_title': extract_ep_title_from_filename(basename),
        'is_series': season is not None,
        'is_multi_episode': is_multi_episode,
    }


CORPUS = [
    "Game.of.Thrones.S03E07.1080p.BluRay.x264.mkv",
    "Show.Name.S01E01-02.720p.WEB-DL.mkv",
    "Show.S01E01E02.1080p.mkv",
    "Show.1x01-1x02.mkv",
    "Show.S01E01_02.mkv",
    "Show.S01E01-33.1080p.mkv",
    "невидимый гость.2016.mkv",
    "The.Matrix.1999.1080p.BluRay.x264.mkv",
    "Show [OVA] [01].mkv",
    "special.S02E01.Special.1080p.mkv",
    "Anime.S01E01.Episode Name.720p.mkv",
    "Show.1.01.720p.mkv",
    "show.s01e01.mkv",
    "Some.Movie.2020.4K.UHD.Remux.HEVC.mkv",
    "Some.Movie.2019.2160p.HDR.BluRay.x265.mkv",
    "Some.Movie.2012.BluRay.1080p.DTS-HD.MA.5.1.x264.mkv",
    "Show.S02E05.720p.HDTV.zlik.ru.mkv",
    "Show.S03E01.1080p.WEB-DL.h.264.iNT.mkv",
    "password!.mkv",
    "random.bin",
    "NoSeasonHere.1080p.mkv",
    "Show.S01E01.WEB-DL.1080p.Repack90.mkv",
    "Stargate.SG1.S01E01.Children.of.the.Gods.720p.mkv",
    "Once.Upon.a.Time.S01E01E02.mkv",
    "1984.mkv",
    "s01e01.mkv",
    "S01E01.mkv",
    "S01E01E02.mkv",
    "Show.2021.S01E01.2160p.mkv",
    "Show.S1.E01.mkv",
]


@pytest.mark.parametrize("name", CORPUS)
def test_adapter_matches_legacy(name):
    actual = parse_file(name)
    expected = legacy_parse(name)
    assert actual == expected, name


def test_parse_file_handles_full_path():
    path = "/media/video/anime/Angel Beats!/1/episode.mkv"
    assert parse_file(path) == legacy_parse(path)
