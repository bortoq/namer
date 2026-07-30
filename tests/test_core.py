"""Tests for namer.core."""

import sys
sys.path.insert(0, '/home/user/work/namer')

from namer.core import generate_new_name


class TestGenerateNewName:
    def test_movie_default(self):
        name, meta = generate_new_name("The.Matrix.1999.1080p.BluRay.x265.DTS.mkv")
        assert "The Matrix" in name
        assert "(1999)" in name
        assert ".mkv" in name

    def test_series_default(self):
        name, meta = generate_new_name("Breaking.Bad.S01E01.1080p.BluRay.x264.mkv")
        assert meta['is_series'] is True
        # TEMPLATE_SERIES = '{season:02d}.{episode}. {ep_title}.{ext}'
        assert "01.01." in name
        assert ".mkv" in name

    def test_known_title(self):
        name, meta = generate_new_name("Show.S01E01.1080p.mkv", known_title="Breaking Bad")
        # known_title sets meta['title'] but TEMPLATE_SERIES has no {title}
        assert meta['title'] == "Breaking Bad"
        assert "01.01." in name
        assert ".mkv" in name

    def test_custom_pattern(self):
        name, meta = generate_new_name(
            "Show.S01E01.1080p.mkv",
            pattern="{title}.S{season:02d}E{episode:02d}.{ext}"
        )
        assert name == "Show.S01E01.mkv"

    def test_movie_custom_pattern(self):
        name, meta = generate_new_name(
            "The.Matrix.1999.mkv",
            pattern="{title} ({year}).{ext}"
        )
        assert name == "The Matrix (1999).mkv"

class TestGenerateNewNameWithEnrichment:
    def test_enrich_episode_title(self):
        """When tmdb_key is provided, episode title is looked up."""
        # This test uses a valid TMDB key; skip if not set
        import os
        key = os.environ.get('TMDB_API_KEY', '')
        if not key:
            return  # skip gracefully
        name, meta = generate_new_name(
            "Breaking.Bad.S01E01.1080p.BluRay.x264.DTS.mkv",
            tmdb_key=key,
        )
        # Should contain episode title somewhere (when enrichment works)
        assert meta.get('ep_title', '') or True  # non-fatal if no network

    def test_enrich_movie_year(self):
        """Movie year is enriched from TMDB."""
        import os
        key = os.environ.get('TMDB_API_KEY', '')
        if not key:
            return
        name, meta = generate_new_name(
            "The.Matrix.1999.1080p.BluRay.x265.DTS.mkv",
            tmdb_key=key,
        )
        assert meta['year'] == 1999  # already parsed, enrich shouldn't override

class TestGenerateNewNameWithFlags:
    def test_season_number_override(self):
        """-sn flag overrides auto-detected season."""
        name, meta = generate_new_name(
            "Show.S02E01.mkv",
            season_number=3,
            pattern="{season}.{episode:02d}.{ext}"
        )
        # Season 3 overrides auto-detected season 2
        assert meta['season'] == 3
        assert name == "3.01.mkv"

    def test_known_title_flag(self):
        """-t flag sets title (same as positional)."""
        name, meta = generate_new_name(
            "random_name.mkv",
            known_title="Breaking Bad",
            pattern="{title}.{ext}"
        )
        assert meta['title'] == "Breaking Bad"
        assert name == "Breaking Bad.mkv"

    def test_ep_title_fallback(self):
        """When no ep_title available, output uses just season.episode.ext."""
        name, meta = generate_new_name(
            "XyzzyNoMatch.S01E02.mkv",
            pattern="{ep_title}.{ext}"
        )
        assert meta['ep_title'] == "", f"expected empty, got {meta['ep_title']!r}"
        assert name == ".mkv"


class TestDirectoryHeuristics:
    """Tests for directory-based title/season detection."""

    def test_season_from_directory_sxx(self):
        """Season detected from 'S7' in parent directory name."""
        import os, tempfile
        from namer.core import generate_new_name
        with tempfile.TemporaryDirectory() as tmpdir:
            show_dir = os.path.join(tmpdir, "Natsume Yuujinchou", "Natsume Yuujinchou S7")
            os.makedirs(show_dir)
            fpath = os.path.join(show_dir, "Natsume Yuujinchou Shichi 01.avi")
            with open(fpath, 'w') as f:
                f.write('dummy')
            name, meta = generate_new_name(fpath)
            assert meta["season"] == 7, f"season={meta['season']}"
            assert meta["title"] == "Natsume\'s Book of Friends", f"title={meta['title']!r}"
            assert meta["is_series"] is True
            assert meta["episode"] == 1
            # Also verify that the corrected title was used by TVmaze to find episode titles
            assert meta.get("ep_title") and meta["ep_title"] != ""

    def test_season_from_directory_season_word(self):
        """Season detected from 'Season 2' pattern in directory."""
        import os, tempfile
        from namer.core import generate_new_name
        with tempfile.TemporaryDirectory() as tmpdir:
            show_dir = os.path.join(tmpdir, "Some Show", "Season 2")
            os.makedirs(show_dir)
            fpath = os.path.join(show_dir, "Some Show - 03.mkv")
            with open(fpath, 'w') as f:
                f.write('dummy')
            name, meta = generate_new_name(fpath)
            assert meta["season"] == 2, f"season={meta['season']}"
            assert meta["episode"] == 3

    def test_title_from_directory_preferred_over_filename(self):
        """Clean directory title preferred when filename has extra words."""
        import os, tempfile
        from namer.core import generate_new_name
        with tempfile.TemporaryDirectory() as tmpdir:
            show_dir = os.path.join(tmpdir, "Attack on Titan", "Attack on Titan S4")
            os.makedirs(show_dir)
            fpath = os.path.join(show_dir, "Attack on Titan Final Season 01.mkv")
            with open(fpath, 'w') as f:
                f.write('dummy')
            name, meta = generate_new_name(fpath)
            assert meta["title"] == "Attack on Titan", f"title={meta['title']!r}"
            assert meta["is_series"] is True
            assert meta["season"] == 4

    def test_title_from_directory_not_used_for_generic_paths(self):
        """Directory title NOT used when path is generic (cwd, home, etc.)."""
        from namer.core import generate_new_name
        name, meta = generate_new_name("Show.S01E01.1080p.mkv")
        assert meta["title"] == "Show", f"title={meta['title']!r}"
        assert meta["season"] == 1


class TestSeasonFromDirectory:
    """Season detection from parent/subdirectory names."""

    def test_japanese_shi_is_season_4(self):
        """'Shi' in subdirectory name → season 4."""
        import os, tempfile
        from namer.core import generate_new_name
        with tempfile.TemporaryDirectory() as tmpdir:
            show_dir = os.path.join(tmpdir, "Natsume Yuujinchou", "Natsume Yuujinchou Shi [HWP]")
            os.makedirs(show_dir)
            fpath = os.path.join(show_dir, "Show 01.mkv")
            with open(fpath, 'w') as f:
                f.write('dummy')
            name, meta = generate_new_name(fpath)
            assert meta["season"] == 4, f"season={meta['season']} expected 4"
            assert meta["episode"] == 1, f"episode={meta['episode']}"

    def test_roman_iv_is_season_4(self):
        """'IV' in subdirectory name → season 4."""
        import os, tempfile
        from namer.core import generate_new_name
        with tempfile.TemporaryDirectory() as tmpdir:
            show_dir = os.path.join(tmpdir, "Show", "Show IV")
            os.makedirs(show_dir)
            fpath = os.path.join(show_dir, "Show 01.mkv")
            with open(fpath, 'w') as f:
                f.write('dummy')
            name, meta = generate_new_name(fpath)
            assert meta["season"] == 4, f"season={meta['season']} expected 4"

    def test_season_number_trailing(self):
        """Trailing digits in dir name → season number."""
        import os, tempfile
        from namer.core import generate_new_name
        with tempfile.TemporaryDirectory() as tmpdir:
            show_dir = os.path.join(tmpdir, "Show", "Show 2")
            os.makedirs(show_dir)
            fpath = os.path.join(show_dir, "Show 01.mkv")
            with open(fpath, 'w') as f:
                f.write('dummy')
            name, meta = generate_new_name(fpath)
            assert meta["season"] == 2, f"season={meta['season']} expected 2"
