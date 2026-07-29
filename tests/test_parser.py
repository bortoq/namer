"""Tests for namer.parser."""

import sys
sys.path.insert(0, '/home/user/work/namer')

from namer.parser import (
    parse_season_episode,
    extract_ext,
    extract_year,
    clean_title,
    parse_file,
)


class TestParseSeasonEpisode:
    def test_s01e01(self):
        assert parse_season_episode("Show.S01E01.mkv") == (1, 1)

    def test_s01(self):
        assert parse_season_episode("Show.S01.mkv") == (1, None)

    def test_s12e34(self):
        assert parse_season_episode("Show.S12E34.mkv") == (12, 34)

    def test_no_match(self):
        assert parse_season_episode("The.Movie.1999.mkv") == (None, None)

    def test_multi_episode(self):
        assert parse_season_episode("Show.S01E01E02.mkv") == (1, 1)


class TestExtractExt:
    def test_mkv(self):
        assert extract_ext("file.mkv") == "mkv"

    def test_mp4(self):
        assert extract_ext("file.mp4") == "mp4"

    def test_no_ext(self):
        assert extract_ext("file") == ""


class TestExtractYear:
    def test_1999(self):
        assert extract_year("The.Matrix.1999.mkv") == 1999

    def test_2025(self):
        assert extract_year("Show.2025.S01E01.mkv") == 2025

    def test_1080p_not_year(self):
        assert extract_year("Show.S01E01.1080p.mkv") is None

    def test_no_year(self):
        assert extract_year("Show.S01E01.mkv") is None

    def test_year_before_resolution(self):
        """Year before resolution should still be detected."""
        assert extract_year("Show.2008.1080p.BluRay.mkv") == 2008


class TestCleanTitle:
    def test_simple_movie(self):
        assert clean_title("The.Matrix.1999.1080p.BluRay.x264.mkv") == "The Matrix"

    def test_series(self):
        assert clean_title("Game.of.Thrones.S01E01.1080p.BluRay.x264.mkv") == "Game of Thrones"

    def test_with_uhd(self):
        assert clean_title("Interstellar.2014.2160p.UHD.BluRay.HEVC.mkv") == "Interstellar"

    def test_with_webdl(self):
        assert clean_title("Show.S01E01.1080p.WEB-DL.AAC.mkv") == "Show"

    def test_anime_brackets(self):
        assert clean_title("[Group] Show Name - 01 [1080p].mkv") == "Show Name"




    # ── Fallback episode number (anime-style) ─────────────────────────────
    def test_anime_episode_fallback(self):
        """Parse standalone episode number like ' - 01' with default season=1."""
        s, e = parse_season_episode("[Group] Show - 01 [1080p].mkv")
        assert s == 1
        assert e == 1

    def test_anime_episode_v2(self):
        """Episode with version suffix v2."""
        s, e = parse_season_episode("[Group] Show - 05v2 [1080p].mkv")
        assert s == 1
        assert e == 5

    def test_anime_episode_skips_resolution(self):
        """720 should NOT be treated as episode number."""
        s, e = parse_season_episode("[Group] Show - 720 [1080p].mkv")
        assert s is None
        assert e is None

    def test_anime_episode_skips_year(self):
        """Years (>=1900) should NOT be treated as episode number."""
        s, e = parse_season_episode("[Group] Show - 2024 [1080p].mkv")
        assert s is None
        assert e is None

class TestParseFile:
    def test_movie(self):
        meta = parse_file("The.Matrix.1999.1080p.BluRay.x265.DTS.mkv")
        assert meta['title'] == "The Matrix"
        assert meta['year'] == 1999
        assert meta['ext'] == "mkv"
        assert meta['is_series'] is False
        assert meta['season'] == 0
        assert meta['episode'] == 0

    def test_series(self):
        meta = parse_file("Game.of.Thrones.S01E01.1080p.BluRay.x264.DTS.mkv")
        assert meta['season'] == 1
        assert meta['episode'] == '01'
        assert meta['ext'] == "mkv"
        assert meta['is_series'] is True
        assert meta['year'] == 0  # no year in this filename

    def test_dot_quality(self):
        meta = parse_file("Show.S01E01.1080p.WEB-DL.AAC.mkv")
        assert 'dot_quality' in meta
        assert meta['dot_quality'] == "WEB-DL.1080p.AAC"

    def test_dot_title(self):
        meta = parse_file("Game.of.Thrones.S01E01.mkv")
        assert meta['dot_title'] == "Game.of.Thrones"

class TestTitleFromPath:
    def test_from_directory(self):
        """Extract clean title from parent directory name."""
        from namer.parser import title_from_path
        import os, tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            show_dir = os.path.join(tmpdir, "Hikaru Ga Shinda Natsu [1080p]")
            os.makedirs(show_dir)
            fpath = os.path.join(show_dir, "somefile.mkv")
            with open(fpath, 'w') as f: pass
            title = title_from_path(fpath)
            assert title == "Hikaru Ga Shinda Natsu"

    def test_walk_up_past_numeric(self):
        """Walk up past numeric/generic directories to find show name."""
        from namer.parser import title_from_path
        import os, tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            show_dir = os.path.join(tmpdir, "Angel Beats!")
            season_dir = os.path.join(show_dir, "1")
            os.makedirs(season_dir)
            fpath = os.path.join(season_dir, "file.mkv")
            with open(fpath, 'w') as f: pass
            # Walks up past "1" (numeric) to find "Angel Beats!"
            assert title_from_path(fpath) == "Angel Beats!"
            # Without the show dir, the tmpdir is detected as generic → empty
            fpath2 = os.path.join(tmpdir, "file.mkv")
            with open(fpath2, 'w') as f: pass
            title = title_from_path(fpath2)
            assert title == ''  # tmpdir is generic/temp → empty

    def test_dot_format_season_episode(self):
        """Parse 'N.NN.' already-formatted names like '1.01. Title.mkv'."""
        from namer.parser import parse_season_episode
        s, e = parse_season_episode("1.01. Departure.mkv")
        assert s == 1
        assert e == 1

    def test_dot_format_extracts_ep_title(self):
        """Episode title extracted from after '1.01.' prefix."""
        from namer.parser import parse_file
        meta = parse_file("1.01. Departure.mkv")
        assert meta['ep_title'] == "Departure"
        assert meta['season'] == 1

    def test_dot_format_title_vs_ep_title(self):
        """For formatted names, title is empty (no show name in filename),
        ep_title is extracted from after N.NN. prefix."""
        from namer.parser import parse_file
        meta = parse_file("1.01. Departure.mkv")
        assert meta['title'] == ""  # filename has no show name
        assert meta['ep_title'] == "Departure"
