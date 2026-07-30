"""Tests for namer.parser."""

import sys
import pytest
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
        assert meta['episode'] == 1
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

    def test_dot_format_ep_title_not_scraped(self):
        """ep_title is NOT extracted from filename — comes only from enrichment."""
        from namer.parser import parse_file
        meta = parse_file("1.01. Departure.mkv")
        assert meta['ep_title'] == "", f"expected empty, got {meta['ep_title']!r}"
        assert meta['season'] == 1

    def test_dot_format_title_vs_ep_title(self):
        """For formatted names, title is empty (no show name in filename),
        ep_title is empty too (no longer scraped from filename)."""
        from namer.parser import parse_file
        meta = parse_file("1.01. Departure.mkv")
        assert meta['title'] == ""  # filename has no show name
        assert meta['ep_title'] == ""  # no longer scraped from filename


class TestBugFixes:
    """Regression tests for reported bugs."""

    # ── Bug 1: AAC5.1 not cleaned from title ──────────────────────────────

    def test_clean_title_aac51(self):
        """AAC5.1 should be stripped from title by quality tokens."""
        result = clean_title(
            "Bad.Santa.2003.1080p.BluRay.x264.AAC5.1-[YTS.MX] [merged].mkv"
        )
        # "AAC5.1" must not appear (neither as "AAC5.1" nor "AAC5 1")
        assert "AAC" not in result, f"AAC leaked into title: {result!r}"
        assert result == "Bad Santa", f"Expected 'Bad Santa', got {result!r}"

    def test_parse_file_aac51(self):
        """parse_file should correctly handle AAC5.1 in filename."""
        meta = parse_file(
            "Bad.Santa.2003.1080p.BluRay.x264.AAC5.1-[YTS.MX] [merged].mkv"
        )
        assert meta["title"] == "Bad Santa", f"title={meta['title']!r}"
        assert meta["year"] == 2003
        assert meta["is_series"] is False
        # "AAC5.1" must not leak into mod or resolution
        assert "AAC" not in meta["mod"], f"AAC leaked into mod: {meta['mod']!r}"

    def test_quality_audio_aac51(self):
        """parse_quality should detect AAC in AAC5.1."""
        from namer.quality import parse_quality
        qi = parse_quality("Bad.Santa.2003.1080p.BluRay.x264.AAC5.1-[YTS.MX] [merged].mkv")
        assert qi.audio == "AAC", f"audio={qi.audio!r}"

    # ── Bug 2: Episode number in parentheses not detected (anime style) ──

    def test_anime_episode_parentheses(self):
        """Episode number before parentheses should be detected."""
        s, e = parse_season_episode(
            "Mieruko-chan - 01 (WEBRip 1920x1080 x264 AAC Rus + Jap).mkv"
        )
        assert s == 1, f"season={s}"
        assert e == 1, f"episode={e}"

    def test_anime_episode_parentheses_v2(self):
        """Episode with v2 suffix before parentheses."""
        s, e = parse_season_episode(
            "Show - 05v2 (WEBRip 1080p).mkv"
        )
        assert s == 1
        assert e == 5

    def test_clean_title_anime_parentheses(self):
        """Episode number in parentheses should be stripped from title."""
        result = clean_title(
            "Mieruko-chan - 01 (WEBRip 1920x1080 x264 AAC Rus + Jap).mkv"
        )
        assert result == "Mieruko chan", f"title={result!r}"
        assert "01" not in result.split(), f"episode number leaked: {result!r}"

    def test_parse_file_anime_parentheses(self):
        """parse_file should detect series from anime with parens."""
        meta = parse_file(
            "Mieruko-chan - 01 (WEBRip 1920x1080 x264 AAC Rus + Jap).mkv"
        )
        assert meta["is_series"] is True, "should be series"
        assert meta["season"] == 1
        assert meta["episode"] == 1
        assert meta["title"] == "Mieruko chan", f"title={meta['title']!r}"
        assert "01" not in meta["title"], f"episode leaked into title: {meta['title']!r}"

    def test_parse_file_series_with_year_anime(self):
        """Anime with year in brackets + episode number."""
        meta = parse_file(
            "Mieruko-chan - 02 (WEBRip 1920x1080 x264 AAC Rus + Jap).mkv"
        )
        assert meta["is_series"] is True
        assert meta["episode"] == 2
        assert meta["title"] == "Mieruko chan"


    # ── Bug 3: Episode in brackets [01_of_74] (anime Monster style) ────

    def test_episode_in_brackets_of_n(self):
        """[01_of_74] format should be detected as episode number."""
        s, e = parse_season_episode(
            "Monster_[01_of_74]_[ru_jp]_[animereactor.ru].avi"
        )
        assert s == 1, f"season={s}"
        assert e == 1, f"episode={e}"

    def test_episode_in_brackets_plain(self):
        """[01] format should be detected as episode number."""
        s, e = parse_season_episode(
            "Monster_[01]_[ru_jp].avi"
        )
        assert s == 1
        assert e == 1

    def test_episode_in_brackets_larger(self):
        """[99_of_99] format with larger number."""
        s, e = parse_season_episode(
            "Show_[42_of_99]_[group].mkv"
        )
        assert s == 1
        assert e == 42

    def test_parse_file_episode_in_brackets(self):
        """parse_file correctly handles [01_of_74] format."""
        meta = parse_file(
            "Monster_[01_of_74]_[ru_jp]_[animereactor.ru].avi"
        )
        assert meta["is_series"] is True
        assert meta["season"] == 1
        assert meta["episode"] == 1
        assert meta["title"] == "Monster", f"title={meta['title']!r}"

    def test_clean_title_episode_in_brackets(self):
        """clean_title strips [01_of_74] brackets content."""
        t = clean_title(
            "Monster_[01_of_74]_[ru_jp]_[animereactor.ru].avi"
        )
        assert t == "Monster", f"clean_title={t!r}"
        assert "01" not in t


# ── NMR-005 regression tests: clean_title + parse_file ─────────────────────

class TestNmr005Regression:
    """Verify clean_title and parse_file handle legitimate titles correctly.

    These tests guard against regressions where clean_title was overzealously
    stripping parts of legitimate movie/show titles (NMR-005).
    """

    # (input_filename, expected_title, expected_year)
    PARSE_CASES = [
        ("1917.2019.mkv", "1917", 2019),
        ("2001.A.Space.Odyssey.1968.mkv", "2001 A Space Odyssey", 1968),
        ("Spider-Man.mkv", "Spider Man", 0),
        ("X-Men.mkv", "X Men", 0),
        ("Uncut.Gems.2019.mkv", "Uncut Gems", 2019),
        ("Extended.Family.S01E01.mkv", "Extended Family", 0),
        ("Cam.2018.mkv", "Cam", 2018),
    ]

    @staticmethod
    def test_clean_title_no_destructive_stripping():
        """clean_title preserves full title for known NMR-005 cases."""
        cases = [
            ("1917.2019.mkv", "1917"),
            ("2001.A.Space.Odyssey.1968.mkv", "2001 A Space Odyssey"),
            ("Spider-Man.mkv", "Spider Man"),
            ("X-Men.mkv", "X Men"),
            ("Uncut.Gems.2019.mkv", "Uncut Gems"),
            ("Extended.Family.S01E01.mkv", "Extended Family"),
            ("Cam.2018.mkv", "Cam"),
        ]
        for fname, expected in cases:
            t = clean_title(fname)
            assert t == expected, (
                f"clean_title({fname!r}) = {t!r}, expected {expected!r}"
            )

    @staticmethod
    @pytest.mark.parametrize("fname,exp_title,exp_year", PARSE_CASES)
    def test_parse_file_title_and_year(fname, exp_title, exp_year):
        """parse_file returns correct (title, year) for NMR-005 cases."""
        meta = parse_file(fname)
        title = meta.get("title", "")
        year = meta.get("year", 0)
        assert title == exp_title, (
            f"parse_file({fname!r}) title = {title!r}, expected {exp_title!r}"
        )
        assert year == exp_year, (
            f"parse_file({fname!r}) year = {year}, expected {exp_year}"
        )


    # ── Bug 4: S01 without Exx + Ep.XX format (Yuru Camp) ──────────────

    def test_yuru_camp_s01_ep01_parsing(self):
        """S01 without Exx + Ep.01 → season=1, episode=1."""
        s, e = parse_season_episode(
            "Yuru.Camp.S01.2018.AniDub.BDRip.Deadmauvlad.Ep.01.avi"
        )
        assert s == 1, f"season={s}"
        assert e == 1, f"episode={e}"

    def test_yuru_camp_parse_file_ep_title_empty(self):
        """ep_title is NOT scraped from filename."""
        meta = parse_file(
            "Yuru.Camp.S01.2018.AniDub.BDRip.Deadmauvlad.Ep.01.avi"
        )
        assert meta['season'] == 1
        assert meta['episode'] == 1
        assert meta['ep_title'] == "", f"ep_title={meta['ep_title']!r}"
        assert meta['is_series'] is True
        assert meta['title'] == "Yuru Camp", f"title={meta['title']!r}"

    def test_yuru_camp_s01_without_episode_returns_season_none(self):
        """S01 alone (no episode number anywhere) returns (1, None)."""
        s, e = parse_season_episode("Yuru.Camp.S01.mkv")
        assert s == 1, f"season={s}"
        assert e is None, f"episode={e}"

    def test_sxx_falls_through_to_episode_fallback(self):
        """Sxx without Exx continues to fallback patterns."""
        s, e = parse_season_episode("Show.S02.1080p.BluRay.05.mkv")
        assert s == 2, f"season={s}"
        assert e == 5, f"episode={e}"

class TestSpecialEpisodeDetection:
    """Tests for [Special]/[OVA] detection in parse_file."""

    def test_regular_episode_not_special(self):
        """Regular episode without special marker has is_special=False."""
        from namer.parser import parse_file
        meta = parse_file("/dummy/Show [01].mkv")
        assert meta.get('is_special') is False

    def test_bracketed_special(self):
        """[Special] in filename sets is_special=True."""
        from namer.parser import parse_file
        meta = parse_file("/dummy/Show [Special] [01].mkv")
        assert meta.get('is_special') is True

    def test_bracketed_ova(self):
        """[OVA] in filename sets is_special=True."""
        from namer.parser import parse_file
        meta = parse_file("/dummy/Show [OVA] [01].mkv")
        assert meta.get('is_special') is True

    def test_bracketed_oav(self):
        """[OAV] in filename sets is_special=True."""
        from namer.parser import parse_file
        meta = parse_file("/dummy/Show [OAV] [01].mkv")
        assert meta.get('is_special') is True

    def test_bracketed_oad(self):
        """[OAD] in filename sets is_special=True."""
        from namer.parser import parse_file
        meta = parse_file("/dummy/Show [OAD] [01].mkv")
        assert meta.get('is_special') is True

    def test_bracketed_extra(self):
        """[Extra] in filename sets is_special=True."""
        from namer.parser import parse_file
        meta = parse_file("/dummy/Show [Extra] [01].mkv")
        assert meta.get('is_special') is True

    def test_bracketed_movie(self):
        """[Movie] in filename sets is_special=True."""
        from namer.parser import parse_file
        meta = parse_file("/dummy/Show [Movie] [01].mkv")
        assert meta.get('is_special') is True

    def test_bracketed_sp(self):
        """[SP] in filename sets is_special=True."""
        from namer.parser import parse_file
        meta = parse_file("/dummy/Show [SP] [01].mkv")
        assert meta.get('is_special') is True

    def test_dotted_special(self):
        """.Special. in filename sets is_special=True."""
        from namer.parser import parse_file
        meta = parse_file("/dummy/Show.Special.01.mkv")
        assert meta.get('is_special') is True

    def test_dotted_ova(self):
        """.OVA. in filename sets is_special=True."""
        from namer.parser import parse_file
        meta = parse_file("/dummy/Show.OVA.01.mkv")
        assert meta.get('is_special') is True

    def test_special_in_title_word_not_detected(self):
        """'Special' as part of title (not bracketed/dotted) is NOT flagged."""
        from namer.parser import parse_file
        meta = parse_file("/dummy/Special Edition [01].mkv")
        # "Special Edition" is a common modifier, not a special episode
        # The title will be cleaned, and is_special should be False
        assert meta.get('is_special') is False

    def test_ova_in_title_word_not_detected(self):
        """'Ovation' shouldn't match OVA."""
        from namer.parser import parse_file
        meta = parse_file("/dummy/Ovation [01].mkv")
        assert meta.get('is_special') is False
