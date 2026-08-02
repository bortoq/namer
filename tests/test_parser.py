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

    def test_dot_format_ep_title_scraped_from_filename(self):
        """ep_title IS extracted from a clean formatted filename."""
        from namer.parser import parse_file
        meta = parse_file("1.01. Departure.mkv")
        assert meta['ep_title'] == "Departure", f"got {meta['ep_title']!r}"
        assert meta['season'] == 1

    def test_dot_format_title_vs_ep_title(self):
        """For formatted names, title is empty (no show name in filename),
        but ep_title IS filled from the filename."""
        from namer.parser import parse_file
        meta = parse_file("1.01. Departure.mkv")
        assert meta['title'] == ""  # filename has no show name
        assert meta['ep_title'] == "Departure"



class TestSingleDigitDotEpisode:
    """N.N names with a single-digit episode (e.g. '1.1.mkv') are series.

    Regression: previously '1.1.mkv' parsed as the movie title "1 1" and
    online lookups turned it into garbage renames (Wikipedia/TVmaze false
    matches like '9-1-1', '2 + 2 = 5', 'Formation').
    """

    def test_parse_single_digit_dot_episode(self):
        s, e = parse_season_episode("1.1.mkv")
        assert (s, e) == (1, 1)

    def test_parse_season2_episode6(self):
        s, e = parse_season_episode("2.6.mkv")
        assert (s, e) == (2, 6)

    def test_parse_multi_digit_season(self):
        s, e = parse_season_episode("12.3.mkv")
        assert (s, e) == (12, 3)

    def test_audio_51_not_episode(self):
        """'DTS.5.1.' inside a filename must NOT become season=5."""
        s, e = parse_season_episode("Movie.2020.1080p.DTS.5.1.mkv")
        assert (s, e) == (None, None)

    def test_audio_51_bare_not_episode(self):
        s, e = parse_season_episode("DTS.5.1.mkv")
        assert (s, e) == (None, None)

    def test_movie_year_pair_not_episode(self):
        """'1917.2019' must stay a movie (NMR-005 regression)."""
        s, e = parse_season_episode("1917.2019.mkv")
        assert (s, e) == (None, None)

    def test_odyssey_not_episode(self):
        s, e = parse_season_episode("2001.A.Space.Odyssey.1968.mkv")
        assert (s, e) == (None, None)

    def test_parse_file_series(self):
        meta = parse_file("1.1.mkv")
        assert meta['is_series'] is True
        assert meta['season'] == 1
        assert meta['episode'] == 1
        assert meta['season_assumed'] is False
        assert meta['title'] == ""  # show name comes from the directory

    def test_parse_file_season2(self):
        meta = parse_file("2.1.mkv")
        assert meta['is_series'] is True
        assert meta['season'] == 2
        assert meta['episode'] == 1

    def test_clean_title_strips_dot_episode(self):
        assert clean_title("1.1.mkv") == ""
        assert clean_title("2.6.mkv") == ""

    def test_two_digit_episode_unaffected(self):
        """'1.01.' still parses (and is not touched by the new pattern)."""
        s, e = parse_season_episode("1.01. Departure.mkv")
        assert (s, e) == (1, 1)
        assert parse_file("1.01. Departure.mkv")['season'] == 1



class TestEpisodeNumberDotSpace:
    """'NN. Title.mkv' (episode number, dot, space) is a series.

    Regression: '01. Секреты.mkv' was parsed as a movie titled '01 Секреты'
    and the garbage title reached the online providers ('Mi secreto',
    'Petr Vrána', 'Genesis creation narrative' ...).
    """

    def test_parse_episode_number_dot_space(self):
        s, e = parse_season_episode("01. Секреты.mkv")
        assert (s, e) == (1, 1)

    def test_parse_later_episode(self):
        s, e = parse_season_episode("08. Что посеешь, то и пожнешь.mkv")
        assert (s, e) == (1, 8)

    def test_parse_file_series(self):
        meta = parse_file("01. Секреты.mkv")
        assert meta['is_series'] is True
        assert meta['season'] == 1
        assert meta['episode'] == 1
        assert meta['season_assumed'] is True
        # no show name in the filename (number is at the start) -> the
        # directory supplies it; a garbage title must NOT go online
        assert meta['title'] == ""

    def test_show_name_before_marker_kept(self):
        """'Show [01].mkv' still derives its title from the filename."""
        meta = parse_file("Show [01].mkv")
        assert meta['title'] == "Show"
        assert meta['is_series'] is True

    def test_space_without_dot_is_movie(self):
        """'10 Cloverfield Lane' (no dot) stays a movie."""
        s, e = parse_season_episode("10 Cloverfield Lane.mkv")
        assert (s, e) == (None, None)

    def test_dot_without_space_is_movie(self):
        """'10.Cloverfield.Lane.2016' (dot, no space) stays a movie."""
        s, e = parse_season_episode("10.Cloverfield.Lane.2016.mkv")
        assert (s, e) == (None, None)

    def test_year_number_ignored(self):
        s, e = parse_season_episode("2001. A Space Odyssey.mkv")
        assert (s, e) == (None, None)

    def test_clean_title_keeps_movie(self):
        assert clean_title("10 Cloverfield Lane.mkv") == "10 Cloverfield Lane"


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

    def test_release_junk_parse_file_ep_title_cleaned(self):
        """Release junk after the marker is stripped before keep; garbage
        '2018 AniDub ... ' yields an empty ep_title, not junk."""
        from namer.parser import parse_file
        meta = parse_file("Yuru.Camp.S01E01.2018.AniDub.BDRip.avi")
        # release-year junk is stripped from the leading edge
        assert "2018" not in meta['ep_title']

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

class TestModifierInTitle:
    """Release modifiers (Uncut/Unrated/Director's Cut) must not leak into
    the movie title; they belong to the 'mod' field only."""

    @staticmethod
    @pytest.mark.parametrize("fname,exp_title,exp_mod", [
        ("Midsommar (2019) DiRECTORS CUT.mkv", "Midsommar", "Director's Cut"),
        ("American Psycho (2000) uncut.mkv", "American Psycho", "Uncut"),
        ("Basic Instinct (1992) Unrated.mkv", "Basic Instinct", "Unrated"),
    ])
    def test_modifier_stripped_from_title_kept_in_mod(fname, exp_title, exp_mod):
        meta = parse_file(fname)
        assert meta["title"] == exp_title, f"title={meta['title']!r}"
        assert meta["mod"] == exp_mod, f"mod={meta['mod']!r}"

    def test_gone_girl_uncut_black(self):
        """"uncut_black" is uncropped black bars: no title words, no mod."""
        meta = parse_file("Gone Girl (2014).uncut_black.mkv")
        assert meta["title"] == "Gone Girl", f"title={meta['title']!r}"
        assert meta["mod"] == "", f"mod={meta['mod']!r}"

    def test_clean_title_with_year_present_strips_modifier(self):
        """Year counts as a release marker, so modifiers after it are removed."""
        assert clean_title("Gone Girl (2014).uncut.mkv") == "Gone Girl"
        assert clean_title("Midsommar (2019) DiRECTORS CUT.mkv") == "Midsommar"

    def test_title_first_word_modifier_word_is_preserved(self):
        """'Uncut' in 'Uncut Gems' and 'Extended' in 'Extended Family' are titles."""
        assert clean_title("Uncut.Gems.2019.mkv") == "Uncut Gems"
        assert clean_title("Extended.Family.S01E01.mkv") == "Extended Family"

    def test_uncut_black_is_video_technical_tag_not_modifier(self):
        """"uncut_black" = uncropped black bars; not an edition modifier."""
        for fname in ("Gone Girl (2014).uncut_black.mkv",
                      "Gone Girl (2014).black_uncut.mkv",
                      "Gone Girl (2014).uncut.black.mkv"):
            meta = parse_file(fname)
            assert meta["title"] == "Gone Girl", f"title={meta['title']!r}"
            assert meta["mod"] == "", f"mod={meta['mod']!r} for {fname!r}"
        assert clean_title("Gone Girl (2014).uncut_black.mkv") == "Gone Girl"

    def test_standalone_uncut_is_still_an_edition_modifier(self):
        """A lone 'uncut' (not followed by black) is a real edition modifier."""
        meta = parse_file("American Psycho (2000) uncut.mkv")
        assert meta["title"] == "American Psycho"
        assert meta["mod"] == "Uncut"


class TestTitleCaseNormalization:
    """Uniform-case Latin titles are title-cased; mixed/non-Latin are kept."""

    @staticmethod
    @pytest.mark.parametrize("fname,exp_title", [
        ("MALICE (1993).avi", "Malice"),
        ("disclosure (1994).avi", "Disclosure"),
        ("невидимый гость.2016.mkv", "невидимый гость"),
        ("Mieruko.chan.S01E01.mkv", "Mieruko chan"),
        ("2001.A.Space.Odyssey.1968.mkv", "2001 A Space Odyssey"),
        ("The.Matrix.1999.1080p.BluRay.x264.mkv", "The Matrix"),
    ])
    def test_title_case(fname, exp_title):
        assert parse_file(fname)["title"] == exp_title, f"title={parse_file(fname)['title']!r}"


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
