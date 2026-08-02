"""Tests for the internal identification layer (namer/identify)."""

import sys
import pytest
sys.path.insert(0, '/home/user/work/namer')

from namer.identify import identify_filename, IdentifyInput, MediaType, Status


def identify(name):
    return identify_filename(IdentifyInput(name))


class TestMediaType:
    @pytest.mark.parametrize("name,exp", [
        ("Show.S01E01.mkv", MediaType.SERIES_EPISODE),
        ("Show.S01E01-02.mkv", MediaType.SERIES_EPISODE),
        ("The.Matrix.1999.1080p.BluRay.mkv", MediaType.MOVIE),
        ("невидимый гость.2016.mkv", MediaType.MOVIE),
        ("Show [OVA] [01].mkv", MediaType.SERIES_EPISODE),
    ])
    def test_media_type(self, name, exp):
        assert identify(name).media_type is exp


class TestMultiEpisode:
    @pytest.mark.parametrize("name,eps,multi", [
        ("Show.S01E01.mkv", [1], False),
        ("Show.S01E01-02.mkv", [1, 2], True),
        ("Show.S01E01_02.mkv", [1, 2], True),
        ("Show.S01E01E02.mkv", [1, 2], True),
        ("Show.1x01-1x02.mkv", [1, 2], True),
    ])
    def test_episodes(self, name, eps, multi):
        ide = identify(name)
        assert [c.value for c in ide.episodes] == eps
        assert ide.is_multi_episode_value == multi

    @pytest.mark.parametrize("name,multi,status", [
        ("Show.S01E01-33.mkv", False, Status.AMBIGUOUS),
        ("Show.S01E01.mkv", False, Status.IDENTIFIED),
        ("Show.S01E01-02.mkv", True, Status.IDENTIFIED),
    ])
    def test_status_and_warnings(self, name, multi, status):
        ide = identify(name)
        assert ide.is_multi_episode_value == multi
        assert ide.status == status
        if name.endswith("S01E01-33.mkv"):
            codes = {w.code for w in ide.warnings}
            assert "numeric-episode-title-maybe" in codes


class TestFields:
    def test_series_fields(self):
        ide = identify("Game.of.Thrones.S03E07.1080p.mkv")
        assert ide.title_value == "Game of Thrones"
        assert ide.media_type is MediaType.SERIES_EPISODE
        assert ide.season.value == 3
        assert ide.episode.value == 7
        assert ide.year is None or not hasattr(ide, 'year')

    def test_movie_year(self):
        ide = identify("The.Matrix.1999.1080p.BluRay.x264.mkv")
        assert ide.title_value == "The Matrix"
        assert ide.year_value == 1999
        assert ide.media_type is MediaType.MOVIE

    def test_cyrillic_movie(self):
        ide = identify("невидимый гость.2016.mkv")
        assert ide.title_value == "невидимый гость"
        assert ide.year_value == 2016

    def test_empty_identifies_nothing(self):
        ide = identify("")
        assert ide.media_type is MediaType.UNKNOWN
        assert ide.status is Status.UNRESOLVED
