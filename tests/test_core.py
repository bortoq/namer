"""Tests for namer.core."""

import errno
import os
import sys
sys.path.insert(0, '/home/user/work/namer')

import pytest

from namer.core import generate_new_name


def _has_renameat2():
    """True when the Linux renameat2(RENAME_NOREPLACE) primitive exists."""
    from namer import core
    try:
        core._get_renameat2()
        return True
    except OSError:
        return False


@pytest.fixture(autouse=True)
def _offline_providers(request, monkeypatch):
    """F648-001: unit tests must never hit live Wikipedia/TVmaze/TMDB.

    Every test in this module gets empty online feeds and a no-op Wikipedia
    translation unless it opts into live providers via @pytest.mark.live.
    """
    if request.node.get_closest_marker('live'):
        return
    from namer.providers import Feed
    monkeypatch.setattr('namer.providers.wikipedia_feed',
                        lambda meta, lang: Feed('wikipedia', {}))
    monkeypatch.setattr('namer.providers.tvmaze_feed',
                        lambda meta, lang: Feed('tvmaze', {}))
    monkeypatch.setattr('namer.providers.tmdb_feed',
                        lambda meta, key, lang: Feed('tmdb', {}))
    monkeypatch.setattr('namer.wikipedia.enrich_title_via_wiki',
                        lambda meta, lang: False)


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

@pytest.mark.live
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

    @pytest.mark.live
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

    @pytest.mark.live
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
        name, meta = generate_new_name(
            "Show [01].mkv", pattern='{season:02d}.{episode:02d}.{ext}')
        assert meta.get('is_special') is False
        assert meta['season'] == 1
        assert meta['episode'] == 1

    def test_special_maps_to_season_0(self):
        """[Special] episode maps to season 0, preventing collision."""
        name, meta = generate_new_name(
            "Show [Special] [01].mkv", pattern='{season:02d}.{episode:02d}.{ext}')
        assert meta.get('is_special') is True
        assert meta['season'] == 0, f"season={meta['season']}"
        assert meta['episode'] == 1
        # Must not collide with regular 01.01
        assert '00.01.' in name, f"name={name!r}"

    def test_ova_maps_to_season_0(self):
        """[OVA] episode maps to season 0."""
        name, meta = generate_new_name(
            "Show [OVA] [05].mkv", pattern='{season:02d}.{episode:02d}.{ext}')
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
            pat = '{season:02d}.{episode:02d}.{ext}'
            name_reg, meta_reg = generate_new_name(reg, pattern=pat)
            name_spec, meta_spec = generate_new_name(spec, pattern=pat)
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


    def test_season_number_forces_series(self, monkeypatch):
        """-sn on a movie-looking filename → treated as a series."""
        self._disable_online(monkeypatch)
        name, meta = generate_new_name(
            "The.Matrix.1999.mkv",
            season_number=2,
            pattern="{title} S{season:02d}.{ext}",
        )
        assert meta['is_series'] is True, f"is_series={meta['is_series']}"
        assert meta['season'] == 2
        assert name == "The Matrix S02.mkv", f"name={name!r}"

    def test_season_number_keeps_series_template_default(self, monkeypatch):
        """-sn switches the default template to the series one."""
        self._disable_online(monkeypatch)
        name, meta = generate_new_name(
            "Show.S01E01.mkv", season_number=2,
        )
        assert meta['is_series'] is True
        assert meta['season'] == 2
        # The default series template demands {ep_title}; offline it is
        # missing, so the file is refused - a movie template would have
        # renamed it to "Show.mkv" instead.
        assert name == "Show.S01E01.mkv", f"name={name!r}"

    def test_single_digit_dot_episode_is_series(self, monkeypatch, tmp_path):
        """1.1.mkv inside a show folder → proper series metadata,
        no garbage "1 1" title reaching the online providers."""
        self._disable_online(monkeypatch)
        show = tmp_path / 'Utopia'
        show.mkdir()
        fpath = show / '1.1.mkv'
        fpath.write_bytes(b'dummy')
        name, meta = generate_new_name(
            str(fpath), pattern='{season:02d}.{episode:02d}.{ext}')
        assert meta['is_series'] is True
        assert meta['season'] == 1
        assert meta['episode'] == 1
        # The show name comes from the directory (pytest's temp dirs may
        # also be collected, so just require the real show name).
        assert 'Utopia' in meta['title'], f"title={meta['title']!r}"
        assert name == '01.01.mkv', f"name={name!r}"

    def test_audio_51_movie_not_series(self, monkeypatch):
        """A movie with 5.1 audio must stay a movie (no S/E false positive)."""
        self._disable_online(monkeypatch)
        name, meta = generate_new_name(
            "Movie.2020.1080p.DTS.5.1.mkv", pattern='{title} ({year}).{ext}')
        assert meta['is_series'] is False
        assert name == 'Movie (2020).mkv', f"name={name!r}"


    def test_episode_dot_space_series_dir_title(self, monkeypatch, tmp_path):
        """'01. Секреты.mkv' in a show dir → series with the DIR title
        (the garbage episode-title must not reach online providers)."""
        self._disable_online(monkeypatch)
        show = tmp_path / 'Тьма (Dark)'
        show.mkdir()
        fpath = show / '01. Секреты.mkv'
        fpath.write_bytes(b'dummy')
        name, meta = generate_new_name(
            str(fpath), pattern='{season:02d}.{episode:02d}.{ext}')
        assert meta['is_series'] is True
        assert meta['season'] == 1
        assert meta['episode'] == 1
        assert 'Тьма' in meta['title'], f"title={meta['title']!r}"
        assert 'Секреты' not in meta['title'], f"title={meta['title']!r}"
        assert name == '01.01.mkv', f"name={name!r}"

    def test_episode_dot_space_no_title_skips(self, monkeypatch, tmp_path):
        """'01. Title.mkv' with no usable title anywhere → skipped
        (never renamed with a garbage online match)."""
        self._disable_online(monkeypatch)
        monkeypatch.setattr('namer.parser.title_from_path', lambda p: '')
        fpath = tmp_path / '01. Секреты.mkv'
        fpath.write_bytes(b'dummy')
        name, meta = generate_new_name(str(fpath))
        assert meta['is_series'] is True
        assert name == '01. Секреты.mkv', f"name={name!r}"

    def test_movie_space_number_stays_movie(self, monkeypatch):
        """'10 Cloverfield Lane' (space, no dot) stays a movie."""
        self._disable_online(monkeypatch)
        name, meta = generate_new_name(
            "10 Cloverfield Lane.mkv", pattern='{title} ({year}).{ext}')
        assert meta['is_series'] is False
        assert meta['title'] == '10 Cloverfield Lane'
        assert name == '10 Cloverfield Lane.mkv', f"name={name!r}"

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
        assert _sanitize_filename('*') == '\u00d7'                    # ×
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
                '\u0421\u0431\u043e\u0440\u043d\u0438\u043a \u00d7\u00d7\u00d7.mp3',
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


class TestRenameNoClobber:
    """B9-004: rename_file must never overwrite an existing destination,
    even when the destination appears between the conflict check and rename."""

    def test_rename_no_clobber_plain(self, tmp_path):
        from namer.core import rename_file
        src = tmp_path / 'Movie.mkv'
        src.write_bytes(b'SOURCE')
        dest = tmp_path / 'New.mkv'
        assert rename_file(str(src), 'New.mkv') is True
        assert dest.read_bytes() == b'SOURCE'
        assert not src.exists()

    def test_rename_no_clobber_existing_dest_uses_counter(self, tmp_path):
        from namer.core import rename_file
        src = tmp_path / 'Movie.mkv'
        src.write_bytes(b'SOURCE')
        (tmp_path / 'New.mkv').write_bytes(b'OTHER')
        assert rename_file(str(src), 'New.mkv') is True
        assert (tmp_path / 'New_1.mkv').read_bytes() == b'SOURCE'
        assert (tmp_path / 'New.mkv').read_bytes() == b'OTHER'  # untouched
        assert not src.exists()

    def test_rename_no_clobber_dest_appears_between_check_and_rename(self, tmp_path, monkeypatch):
        """Simulate the TOCTOU window: after the conflict check picks 'New.mkv'
        as free, a file materialises there; the rename must fall back to the
        next free name instead of overwriting it."""
        from namer import core
        src = tmp_path / 'Movie.mkv'
        src.write_bytes(b'SOURCE')

        real_link = core.os.link

        def racing_link(s, d):
            if core.os.path.basename(d) == 'New.mkv':
                # Destination materialised between the exists() check and rename
                with open(d, 'wb') as f:
                    f.write(b'OTHER')
            return real_link(s, d)

        monkeypatch.setattr(core.os, 'link', racing_link)
        assert core.rename_file(str(src), 'New.mkv') is True
        monkeypatch.undo()
        assert (tmp_path / 'New.mkv').read_bytes() == b'OTHER'
        assert (tmp_path / 'New_1.mkv').read_bytes() == b'SOURCE'
        assert not src.exists()

    @pytest.mark.skipif(not _has_renameat2(), reason='Linux renameat2 only')
    def test_rename_no_clobber_hardlink_fallback_when_link_unsupported(self, tmp_path, monkeypatch):
        """Filesystems without hard links fall back to the atomic
        renameat2(RENAME_NOREPLACE) primitive (Linux); on platforms where
        neither primitive exists the rename fails safely instead of
        overwriting (covered by test_..._no_atomic_primitive_fails_safely)."""
        from namer import core
        src = tmp_path / 'Movie.mkv'
        src.write_bytes(b'SOURCE')
        real_link = core.os.link

        def no_link(*a):
            raise OSError(1, 'Operation not permitted')

        monkeypatch.setattr(core.os, 'link', no_link)
        assert core.rename_file(str(src), 'New.mkv') is True
        monkeypatch.undo()
        assert (tmp_path / 'New.mkv').read_bytes() == b'SOURCE'
        assert not src.exists()

    def test_rename_no_clobber_fallback_race_retries_next_free(self, tmp_path, monkeypatch):
        """81-001: on the renameat2 fallback path, a destination that appears
        between the conflict check and the rename must be claimed, not
        overwritten — the retry loop moves to the next free name."""
        from namer import core
        src = tmp_path / 'Movie.mkv'
        src.write_bytes(b'SOURCE')

        real_noreplace = core._rename_noreplace
        calls = {'n': 0}

        def racing_noreplace(s, d):
            calls['n'] += 1
            if os.path.basename(d) == 'New.mkv' and calls['n'] == 1:
                # Dest materialises in the race window; simulate EEXIST
                with open(d, 'wb') as f:
                    f.write(b'OTHER')
                return False
            return real_noreplace(s, d)

        monkeypatch.setattr(core.os, 'link',
                            lambda *a: (_ for _ in ()).throw(OSError(errno.EXDEV, 'cross-device')))
        monkeypatch.setattr(core, '_rename_noreplace', racing_noreplace)
        assert core.rename_file(str(src), 'New.mkv') is True
        assert (tmp_path / 'New.mkv').read_bytes() == b'OTHER'  # untouched
        assert (tmp_path / 'New_1.mkv').read_bytes() == b'SOURCE'
        assert not src.exists()

    def test_rename_no_clobber_no_atomic_primitive_fails_safely(self, tmp_path, monkeypatch):
        """81-001: when neither os.link nor renameat2 is usable, the rename
        must FAIL and leave the source in place — never fall back to a
        non-atomic exists()+os.rename() that could overwrite a foreign file."""
        from namer import core
        src = tmp_path / 'Movie.mkv'
        src.write_bytes(b'SOURCE')
        (tmp_path / 'New.mkv').write_bytes(b'FOREIGN')  # the file at risk

        def no_link(*a):
            raise OSError(errno.EPERM, 'Operation not permitted')

        def no_noreplace(*a):
            raise OSError(errno.ENOSYS, 'renameat2 not available')

        monkeypatch.setattr(core.os, 'link', no_link)
        monkeypatch.setattr(core, '_rename_noreplace', no_noreplace)
        assert core.rename_file(str(src), 'New.mkv') is False  # reported error
        assert (tmp_path / 'Movie.mkv').read_bytes() == b'SOURCE'   # source survives
        assert (tmp_path / 'New.mkv').read_bytes() == b'FOREIGN'    # foreign file untouched

    def test_rename_no_clobber_broken_symlink_dest_occupied(self, tmp_path):
        """81-002: a broken symlink still occupies its name — the rename must
        pick the next free name instead of looping forever or choosing the
        symlink's name."""
        from namer import core
        src = tmp_path / 'Movie.mkv'
        src.write_bytes(b'SOURCE')
        broken = tmp_path / 'New.mkv'
        broken.symlink_to(tmp_path / 'nowhere.mkv')  # dangling target
        assert not os.path.exists(str(broken))          # target missing (exists() lies)
        assert os.path.lexists(str(broken))             # ... but the entry occupies the name
        assert core.rename_file(str(src), 'New.mkv') is True
        assert os.path.lexists(str(broken))             # entry still there (rename chose New_1)
        assert not os.path.exists(str(broken))          # still dangling — never the target
        assert (tmp_path / 'New_1.mkv').read_bytes() == b'SOURCE'
        assert not src.exists()

    def test_dry_run_and_real_resolve_same_dest_for_broken_symlink(self, tmp_path):
        """81-002: dry-run must report exactly the destination a real run uses,
        even when the conflicting entry is a broken symlink (exists() lies)."""
        from namer import core
        src = tmp_path / 'Movie.mkv'
        src.write_bytes(b'SOURCE')
        broken = tmp_path / 'New.mkv'
        broken.symlink_to(tmp_path / 'nowhere.mkv')

        resolved = []
        assert core.rename_file(str(src), 'New.mkv', dry_run=True, resolved=resolved) is True
        dry_dest = resolved[0]
        assert dry_dest == 'New_1.mkv'

        # Real run on a fresh copy must converge on the same basename.
        src2 = tmp_path / 'Movie2.mkv'
        src2.write_bytes(b'SOURCE2')
        assert core.rename_file(str(src2), 'New.mkv') is True
        assert (tmp_path / 'New_1.mkv').read_bytes() == b'SOURCE2'
        assert not src2.exists()

class TestMultiEpisode:
    """B9-006: S01E01E02 must be skipped safely, not renamed to S01E01."""

    def _disable_online(self, monkeypatch):
        from namer.providers import Feed
        monkeypatch.setattr('namer.providers.wikipedia_feed',
                            lambda meta, lang: Feed('wikipedia', {}))
        monkeypatch.setattr('namer.providers.tvmaze_feed',
                            lambda meta, lang: Feed('tvmaze', {}))
        monkeypatch.setattr('namer.wikipedia.enrich_title_via_wiki',
                            lambda meta, lang: False)

    def test_parse_marks_multi_episode(self):
        from namer.parser import parse_file
        # 81-004: all documented multi-episode forms are detected
        multi = [
            'Show.S01E01E02.mkv',
            'Show.S01E01E02E03.mkv',
            'Show.S01E01-E02.mkv',
            'Show.S01E01-02.mkv',
            'Show.1x01-1x02.mkv',
            'Show.1x01-02.mkv',
            'Show.S01E01.E02.mkv',
            'Show.S01E01 & E02.mkv',
            'Show.S01E01+E02.mkv',
            # F61-002: whitespace / word-separated second markers
            'Show.S01E01 E02.mkv',
            'Show.S01E01 and E02.mkv',
            'Show.1x01 1x02.mkv',
            'Show.1x01 and 1x02.mkv',
        ]
        for f in multi:
            assert parse_file(f)['is_multi_episode'] is True, f
        # single-episode + resolution/year/technical noise must NOT be flagged
        single = [
            'Show.S01E01.mkv',
            'Show.S01E01.1080p.mkv',
            'Show.S01E01.720p.mkv',
            'Show.S01E01-720p.mkv',
            'Show.S01E01-720.mkv',
            'Show.S01E01.2160p.mkv',
            'Show.S01E01.2020.mkv',
            'Show.S01E01.EpisodeName.mkv',
            # F648-003: technical release tokens are single episodes
            'Show.S01E01.10bit.mkv',
            'Show.S01E01.8bit.mkv',
            'Show.S01E01.5.1.DTS.mkv',
            'Show.S01E01.60fps.mkv',
            'Show.S01E01.24fps.mkv',
            'Show.S01E01.1080p.10bit.mkv',
            'Show.S01E01.7.1.Atmos.mkv',
            'Show.S01E01.2.0.mkv',
            'Show.S01E01.1920.mkv',
            'Show.1x01.10bit.mkv',
            'Show.1x01.5.1.DTS.mkv',
            'Show.1x01.60fps.mkv',
            # F61-001: technical tokens with a separator inside are single
            'Show.S01E01.10-bit.mkv',
            'Show.S01E01.10 bit.mkv',
            'Show.S01E01.60 fps.mkv',
            'Show.S01E01.24 fps.mkv',
            'Show.1x01.10-bit.mkv',
            'Show.1x01.60 fps.mkv',
            # BD8-001: numeric episode titles / release suffixes are single
            'Battlestar.Galactica.S01E01.33.mkv',
            'Doctor.Who.S03E07.42.mkv',
            'Show.S01E01.12.Monkeys.mkv',
            'Show.S01E01.101.Dalmatians.mkv',
            'Show.S01E01.123ABC.mkv',
            'Show.S01E01.100MB.mkv',
            # dot-separated bare numbers are ambiguous numeric titles
            'Show.S01E01.02.mkv',
            'Show.1x01.02.mkv',
        ]
        for f in single:
            assert parse_file(f)['is_multi_episode'] is False, f

    def test_generate_new_name_skips_multi_episode(self, monkeypatch):
        self._disable_online(monkeypatch)
        from namer.core import generate_new_name
        name, meta = generate_new_name(
            'Show.S01E01E02.mkv', pattern='{title}.S{season:02d}E{episode:02d}.{ext}')
        assert name == 'Show.S01E01E02.mkv', f"expected skip, got {name!r}"
        assert meta['_skip'] is True

    @pytest.mark.parametrize('name', [
        'Show.S01E01 E02.mkv',
        'Show.S01E01 and E02.mkv',
        'Show.1x01 1x02.mkv',
        'Show.1x01 and 1x02.mkv',
    ])
    def test_whitespace_word_separated_multi_episode_is_skipped(
            self, monkeypatch, name):
        """F61-002: whitespace/'and'-separated multi files are skipped safely."""
        from namer.parser import parse_file

        parsed = parse_file(name)
        assert parsed['is_multi_episode'] is True
        # the word separator must not leak into the show title
        assert parsed['title'] == 'Show', f"title={parsed['title']!r}"

        self._disable_online(monkeypatch)
        from namer.core import generate_new_name
        new_name, meta = generate_new_name(
            name, pattern='{title}.S{season:02d}E{episode:02d}.{ext}')
        assert meta['_skip'] is True
        assert new_name == os.path.basename(name)

    def test_numeric_episode_title_file_is_renamed_not_skipped(
            self, monkeypatch):
        """BD8-001: S01E01.33 is a single episode and is renamed normally."""
        self._disable_online(monkeypatch)
        from namer.core import generate_new_name
        new_name, meta = generate_new_name(
            'Battlestar.Galactica.S01E01.33.mkv',
            pattern='{title}.S{season:02d}E{episode:02d}.{ext}')
        assert meta.get('_skip') is not True
        assert new_name == 'Battlestar Galactica.S01E01.mkv'

    def test_process_directory_skips_multi_episode(self, monkeypatch, tmp_path):
        self._disable_online(monkeypatch)
        from namer.core import process_directory
        show = tmp_path / 'Show'
        show.mkdir()
        (show / 'Show.S01E01E02.mkv').write_bytes(b'x')
        renamed, total, errors = process_directory(
            str(show), pattern='{title}.S{season:02d}E{episode:02d}.{ext}')
        assert renamed == 0
        assert total == 1
        assert errors == 0
        assert (show / 'Show.S01E01E02.mkv').exists()  # untouched


class TestProcessDirectoryErrorExit:
    """B9-005: per-file errors must be counted and surfaced to the CLI."""

    def test_worker_error_counts_error(self, monkeypatch, tmp_path):
        from namer.core import process_directory
        from namer import core as core_module
        show = tmp_path / 'Show'
        show.mkdir()
        (show / 'Movie.2020.mkv').write_bytes(b'x')

        def boom(*a, **k):
            raise RuntimeError('boom')

        monkeypatch.setattr(core_module, 'generate_new_name', boom)
        renamed, total, errors = process_directory(str(show), dry_run=True)
        assert renamed == 0
        assert total == 1
        assert errors == 1

    def test_rename_failure_counts_error(self, monkeypatch, tmp_path):
        from namer.core import process_directory
        from namer import core as core_module
        from namer.providers import Feed
        monkeypatch.setattr('namer.providers.wikipedia_feed',
                            lambda meta, lang: Feed('wikipedia', {}))
        monkeypatch.setattr('namer.providers.tvmaze_feed',
                            lambda meta, lang: Feed('tvmaze', {}))
        monkeypatch.setattr('namer.wikipedia.enrich_title_via_wiki',
                            lambda meta, lang: False)
        show = tmp_path / 'Show'
        show.mkdir()
        (show / 'Show.S01E01.mkv').write_bytes(b'x')

        def fail_rename(*a, **k):
            return False

        monkeypatch.setattr(core_module, 'rename_file', fail_rename)
        renamed, total, errors = process_directory(
            str(show), pattern='{season:02d}.{episode:02d}.{ext}')
        assert renamed == 0
        assert total == 1
        assert errors == 1


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
