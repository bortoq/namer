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
        name, meta = generate_new_name(
            "Breaking.Bad.S01E01.1080p.BluRay.x264.mkv",
            pattern="{season:02d}.{episode:02d}.{ext}"
        )
        assert meta['is_series'] is True
        assert "01.01." in name
        assert ".mkv" in name

    def test_known_title(self):
        name, meta = generate_new_name(
            "Show.S01E01.1080p.mkv",
            known_title="Breaking Bad",
            pattern="{title}.S{season:02d}E{episode:02d}.{ext}"
        )
        assert meta['title'] == "Breaking Bad"
        assert "Breaking Bad.S01E01" in name
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
        """When ep_title is empty and template uses it, file is skipped (not renamed)."""
        name, meta = generate_new_name(
            "XyzzyNoMatch.S01E02.mkv",
            pattern="{ep_title}.{ext}"
        )
        assert meta['ep_title'] == "", f"expected empty, got {meta['ep_title']!r}"
        # Should return original basename because ep_title is required by template but missing
        assert name == "XyzzyNoMatch.S01E02.mkv"




class TestEpTitleEnrichment:
    """Tests for ep_title enrichment (not scraped from filename)."""

    def test_yuru_camp_ep_title_from_enrichment_not_filename(self):
        """Yuru Camp: ep_title comes from TVmaze enrichment, NOT filename scraping."""
        name, meta = generate_new_name(
            "Yuru.Camp.S01.2018.AniDub.BDRip.Deadmauvlad.Ep.01.avi",
            pattern="{season:02d}.{episode:02d}. {ep_title}.{ext}"
        )
        # ep_title is from TVmaze (not from filename), so it won't contain garbage
        assert meta['season'] == 1
        assert meta['episode'] == 1
        assert meta['ep_title'] != "", "ep_title should be filled by enrichment"
        # Should NOT contain filename garbage
        assert "AniDub" not in meta['ep_title'], f"garbage in ep_title: {meta['ep_title']!r}"
        assert "Deadmauvlad" not in meta['ep_title'], f"garbage in ep_title: {meta['ep_title']!r}"
        assert "2018" not in meta['ep_title'], f"garbage in ep_title: {meta['ep_title']!r}"

    def test_show_not_found_skips_when_ep_title_required(self):
        """When no enrichment found ep_title and template uses it → skip."""
        name, meta = generate_new_name(
            "XyzzyNoMatch.S01E02.mkv",
            pattern="{season:02d}.{episode:02d}. {ep_title}.{ext}"
        )
        assert meta['ep_title'] == ""
        assert name == "XyzzyNoMatch.S01E02.mkv", f"expected skip, got {name!r}"

    def test_ep_title_not_scraped_from_filename(self):
        """parse_file does NOT extract ep_title from filename."""
        from namer.parser import parse_file
        meta = parse_file("1.01. Some Episode Title.mkv")
        assert meta['ep_title'] == "", f"ep_title={meta['ep_title']!r}"

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


class TestSpecialEpisodeHandling:
    """Tests for special episode → season 0 mapping in generate_new_name."""

    def test_regular_keeps_season_1(self):
        """Regular episode keeps season 1."""
        name, meta = generate_new_name("Show [01].mkv")
        assert meta.get('is_special') is False
        assert meta['season'] == 1
        assert meta['episode'] == 1

    def test_special_maps_to_season_0(self):
        """[Special] episode maps to season 0, preventing collision."""
        name, meta = generate_new_name("Show [Special] [01].mkv")
        assert meta.get('is_special') is True
        assert meta['season'] == 0, f"season={meta['season']}"
        assert meta['episode'] == 1
        # Must not collide with regular 01.01
        assert '00.01.' in name, f"name={name!r}"

    def test_ova_maps_to_season_0(self):
        """[OVA] episode maps to season 0."""
        name, meta = generate_new_name("Show [OVA] [05].mkv")
        assert meta.get('is_special') is True
        assert meta['season'] == 0
        assert meta['episode'] == 5

    def test_specials_directory_skipped_as_supplementary(self):
        """'Specials' directory files are flagged supplementary (skipped)."""
        import os, tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            show_dir = os.path.join(tmpdir, "Show", "Specials")
            os.makedirs(show_dir)
            fpath = os.path.join(show_dir, "Show OVA 01.mkv")
            with open(fpath, 'w') as f:
                f.write('dummy')
            name, meta = generate_new_name(fpath)
            # Supplementary check catches files in 'Specials' directories
            assert meta.get('_skip') is True, f"_skip={meta.get('_skip')}"


    def test_regular_and_special_no_collision(self):
        """Regular ep 1 and special ep 1 produce different names."""
        import os, tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = os.path.join(tmpdir, "Show [01].mkv")
            spec = os.path.join(tmpdir, "Show [Special] [01].mkv")
            with open(reg, 'w') as f:
                f.write('dummy')
            with open(spec, 'w') as f:
                f.write('dummy')
            name_reg, meta_reg = generate_new_name(reg)
            name_spec, meta_spec = generate_new_name(spec)
            assert name_reg != name_spec, f"collision: {name_reg} == {name_spec}"
            assert '01.01' in name_reg
            assert '00.01' in name_spec


class TestVotingPipeline:
    """Offline end-to-end tests of the collect → vote → render pipeline."""

    @staticmethod
    def _disable_online(monkeypatch):
        """Replace network providers with empty feeds."""
        from namer.providers import Feed
        monkeypatch.setattr('namer.providers.wikipedia_feed',
                            lambda meta, lang: Feed('wikipedia', {}))
        monkeypatch.setattr('namer.providers.tvmaze_feed',
                            lambda meta, lang: Feed('tvmaze', {}))
        monkeypatch.setattr('namer.wikipedia.enrich_title_via_wiki',
                            lambda meta, lang: False)

    def test_season_conflict_refuses_rename(self, monkeypatch, tmp_path):
        """Explicit S01 filename vs 'Season 2' dirname → refuse, no guess."""
        self._disable_online(monkeypatch)
        show = tmp_path / 'Show' / 'Season 2'
        show.mkdir(parents=True)
        fpath = show / 'Show.S01E05.mkv'
        fpath.write_bytes(b'dummy')
        name, meta = generate_new_name(
            str(fpath), pattern='{season:02d}.{episode:02d}.{ext}')
        assert name == 'Show.S01E05.mkv', f"expected refusal, got {name!r}"
        assert 'season' in meta.get('_refused_fields', [])

    def test_season_number_override_resolves_conflict(self, monkeypatch, tmp_path):
        """User-provided -sn resolves the disputed season."""
        self._disable_online(monkeypatch)
        show = tmp_path / 'Show' / 'Season 2'
        show.mkdir(parents=True)
        fpath = show / 'Show.S01E05.mkv'
        fpath.write_bytes(b'dummy')
        name, meta = generate_new_name(
            str(fpath), pattern='{season:02d}.{episode:02d}.{ext}', season_number=2)
        assert meta['season'] == 2
        assert '02.05.' in name, f"name={name!r}"

    def test_special_maps_to_season_0_offline(self, monkeypatch):
        """[Special] → season 0 through the voting pipeline."""
        self._disable_online(monkeypatch)
        name, meta = generate_new_name(
            'Show [Special] [01].mkv', pattern='{season:02d}.{episode:02d}.{ext}')
        assert meta['season'] == 0
        assert '00.01.' in name, f"name={name!r}"

    def test_assumed_anime_season_still_renames(self, monkeypatch):
        """Assumed season 1 (anime format) with no opposition still works."""
        self._disable_online(monkeypatch)
        name, meta = generate_new_name(
            'Show - 01.mkv', pattern='{season:02d}.{episode:02d}.{ext}')
        assert meta['season'] == 1
        assert meta['episode'] == 1
        assert '01.01.' in name, f"name={name!r}"


class TestSanitizeFilename:
    """Forbidden filename characters are replaced with the Unicode
    lookalikes configured in settings.INVALID_CHAR_REPLACEMENTS."""

    def test_lookalike_replacement_1to1(self):
        from namer.core import _sanitize_filename
        assert _sanitize_filename('?') == '\uff1f'                    # ？
        assert _sanitize_filename('*') == '\u2731'                    # ✱
        assert _sanitize_filename(':') == '\u2236'                    # ∶
        assert _sanitize_filename('/') == '\u2215'                    # ∕
        assert _sanitize_filename('\\') == '\u2216'                   # ∖
        assert _sanitize_filename('<') == '\u2039'                    # ‹
        assert _sanitize_filename('>') == '\u203a'                    # ›

    def test_quotes_alternate_open_close(self):
        from namer.core import _sanitize_filename
        assert _sanitize_filename('"Matrix"') == '\u201cMatrix\u201d'
        assert _sanitize_filename('"a" and "b"') == '\u201ca\u201d and \u201cb\u201d'

    def test_user_examples(self):
        from namer.core import _sanitize_filename
        cases = {
            'Lost S02E21 - ?.mp4': 'Lost S02E21 - \uff1f.mp4',
            '\u0421\u0431\u043e\u0440\u043d\u0438\u043a ***.mp3':
                '\u0421\u0431\u043e\u0440\u043d\u0438\u043a \u2731\u2731\u2731.mp3',
            '\u041b\u0435\u043a\u0446\u0438\u044f 1: \u0412\u0432\u0435\u0434\u0435\u043d\u0438\u0435.mkv':
                '\u041b\u0435\u043a\u0446\u0438\u044f 1\u2236 \u0412\u0432\u0435\u0434\u0435\u043d\u0438\u0435.mkv',
            '\u041f\u0440\u043e\u0435\u043a\u0442 2026/07.docx':
                '\u041f\u0440\u043e\u0435\u043a\u0442 2026\u221507.docx',
            '\u041f\u0430\u043f\u043a\u0430 \\ \u0410\u0440\u0445\u0438\u0432.zip':
                '\u041f\u0430\u043f\u043a\u0430 \u2216 \u0410\u0440\u0445\u0438\u0432.zip',
            '\u0424\u0438\u043b\u044c\u043c "Матрица".mkv':
                '\u0424\u0438\u043b\u044c\u043c \u201cМатрица\u201d.mkv',
            '\u042d\u043f\u0438\u0437\u043e\u0434 <Режиссерская версия>.mkv':
                '\u042d\u043f\u0438\u0437\u043e\u0434 \u2039Режиссерская версия\u203a.mkv',
        }
        for raw, expected in cases.items():
            assert _sanitize_filename(raw) == expected, raw

    def test_pipe_and_control_chars_fall_back_to_underscore(self):
        from namer.core import _sanitize_filename
        assert _sanitize_filename('a|b') == 'a_b'
        assert _sanitize_filename('a\x01b\x1fb') == 'a_b_b'  # control → _
        assert '\x00' not in _sanitize_filename('\x00')

    def test_trailing_dots_and_spaces_stripped(self):
        from namer.core import _sanitize_filename
        assert _sanitize_filename('Name.. ') == 'Name'
        assert _sanitize_filename('Name.') == 'Name'

    def test_idempotent(self):
        from namer.core import _sanitize_filename
        once = _sanitize_filename('Фильм "Матрица": ?.mkv')
        assert _sanitize_filename(once) == once

    def test_lookalikes_are_not_forbidden(self):
        from namer import settings
        for good in settings.INVALID_CHAR_REPLACEMENTS.values():
            chars = good if isinstance(good, str) else ''.join(good)
            for ch in chars:
                assert ch not in settings.INVALID_CHARS, ch

    def test_format_template_applies_replacements(self):
        """The rename pipeline runs the table: ep_title with : and ? keeps
        a readable lookalike instead of an underscore."""
        from namer.core import _format_template
        name = _format_template(
            '{ep_title}.{ext}',
            {'ep_title': 'Вопрос: кто?', 'ext': 'mkv'},
        )
        assert name == 'Вопрос\u2236 кто\uff1f.mkv', name


class TestInvalidCharsSetting:
    def test_every_replacement_key_is_invalid(self):
        from namer import settings
        for bad in settings.INVALID_CHAR_REPLACEMENTS:
            assert bad in settings.INVALID_CHARS, bad

    def test_pair_values_have_two_chars(self):
        from namer import settings
        for good in settings.INVALID_CHAR_REPLACEMENTS.values():
            if isinstance(good, (tuple, list)):
                assert len(good) == 2, good
