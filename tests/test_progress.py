"""Tests for the live progress region (namer/progress.py) and its
integration into process_directory."""

import io

import pytest

from namer.progress import Progress, display_width, truncate


class TestWidthAndTruncate:
    def test_display_width_ascii(self):
        assert display_width('abc') == 3

    def test_display_width_cjk_is_double(self):
        # East-Asian wide chars occupy 2 terminal columns each
        assert display_width('\u65e5\u672c\u8a9e') == 6  # 日本語

    def test_truncate_keeps_short_text(self):
        assert truncate('hello', 10) == 'hello'

    def test_truncate_long_text_adds_ellipsis(self):
        assert truncate('hello world', 6) == 'hello\u2026'

    def test_truncate_zero_width(self):
        assert truncate('hello', 0) == ''

    def test_truncate_negative_width(self):
        assert truncate('hello', -3) == ''

    def test_truncate_respects_cjk_width(self):
        # 日本語 = 6 cols, limit 4 → keep 日 (2 cols) + …
        assert truncate('\u65e5\u672c\u8a9e', 4) == '\u65e5\u2026'

    def test_truncate_exact_fit(self):
        assert truncate('hello', 5) == 'hello'


class TestProgressLineMode:
    """enabled=False → no ANSI, compact lines per completion."""

    def test_finish_prints_line_and_bottom_summary(self):
        stream = io.StringIO()
        p = Progress(total=3, mode='dry-run', stream=stream, enabled=False)
        t1 = p.task(1, 'a.mkv')
        t2 = p.task(2, 'b.mkv')
        t1.set_action('voting')
        t1.park()
        t2.finish('renamed')
        p.close()
        out = stream.getvalue()
        assert '  renamed [2/3] b.mkv' in out
        assert 'dry-run: 1/3 \u0444\u0430\u0439\u043b\u043e\u0432 \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u0430\u043d\u043e' in out

    def test_parked_files_show_in_bottom_line(self):
        stream = io.StringIO()
        p = Progress(total=2, mode='rename', stream=stream, enabled=False)
        t = p.task(1, 'a.mkv')
        t.park()
        p.close()
        out = stream.getvalue()
        assert '1 \u0433\u043e\u0442\u043e\u0432\u043e \u043a \u043f\u0435\u0440\u0435\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u044e' in out

    def test_unpark_then_finish_clears_queue(self):
        stream = io.StringIO()
        p = Progress(total=2, mode='rename', stream=stream, enabled=False)
        t = p.task(1, 'a.mkv')
        t.park()
        t.unpark('renaming')
        t.finish('renamed')
        p.close()
        out = stream.getvalue()
        assert '\u0433\u043e\u0442\u043e\u0432\u043e' not in out
        assert 'rename: 1/2 \u0444\u0430\u0439\u043b\u043e\u0432 \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u0430\u043d\u043e' in out

    def test_finish_is_idempotent(self):
        stream = io.StringIO()
        p = Progress(total=1, mode='rename', stream=stream, enabled=False)
        t = p.task(1, 'a.mkv')
        t.finish('renamed')
        t.finish('skipped')  # must be a no-op
        p.close()
        out = stream.getvalue()
        assert out.count('  renamed [1/1]') == 1
        assert 'rename: 1/1' in out

    def test_set_action_after_done_is_ignored(self):
        stream = io.StringIO()
        p = Progress(total=1, mode='rename', stream=stream, enabled=False)
        t = p.task(1, 'a.mkv')
        t.finish('renamed')
        t.set_action('voting')
        t.set_new_name('x.mkv')
        p.close()
        assert 'rename: 1/1' in stream.getvalue()


class TestProgressAnsiFormat:
    """Line formatting for the live region (enabled=True)."""

    def _format(self, total=3, index=1, width=120, mutate=None):
        p = Progress(total=total, mode='rename', stream=io.StringIO(),
                     enabled=True)
        t = p.task(index, 'Old.Name.S01E01.1080p.mkv')
        mutate(p, t)
        line = p._format_line(t, width)
        p.close()
        return line

    def test_line_contains_index_and_bar_and_action(self):
        def mutate(p, t):
            t.set_action('voting')
        line = self._format(mutate=mutate)
        assert '1/3' in line
        assert '[ ' not in line          # bar brackets are tight
        assert '\u2588' in line          # filled bar cells
        assert 'voting' in line
        assert 'Old.Name.S01E01.1080p.mkv' in line

    def test_bar_fills_with_stage(self):
        def mutate(p, t):
            t.set_action('parsing feeds')
        line = self._format(mutate=mutate)
        filled = line.count('\u2588')
        # stage 2 of 5 on a 20-cell bar → 8 cells
        assert filled == 8, f'filled={filled}'

    def test_new_name_appears_after_arrow(self):
        def mutate(p, t):
            t.set_action('rendering')
            t.set_new_name('01.01. New Name.mkv')
        line = self._format(mutate=mutate)
        assert '\u2192' in line
        assert 'New Name.mkv' in line

    def test_long_names_are_truncated_to_width(self):
        def mutate(p, t):
            t.set_action('renaming')
            t.set_new_name('X' * 500)
        line = self._format(width=80, mutate=mutate)
        assert display_width(line) <= 80, f'line too wide: {display_width(line)}'

    def test_no_new_name_no_arrow(self):
        line = self._format(mutate=lambda p, t: None)
        assert '\u2192' not in line


class TestProgressAnsiRegion:
    def _progress(self, total=2, stream=None):
        return Progress(total=total, mode='rename',
                        stream=stream or io.StringIO(), enabled=True)

    def test_first_render_hides_cursor(self, monkeypatch):
        monkeypatch.setattr('namer.progress._THROTTLE', 0.0)
        stream = io.StringIO()
        p = self._progress(stream=stream)
        t = p.task(1, 'a.mkv')
        t.set_action('querying providers')
        out = stream.getvalue()
        assert '\x1b[?25l' in out  # hide cursor
        assert 'a.mkv' in out

    def test_close_erases_region_and_shows_cursor(self, monkeypatch):
        monkeypatch.setattr('namer.progress._THROTTLE', 0.0)
        stream = io.StringIO()
        p = self._progress(stream=stream)
        t = p.task(1, 'a.mkv')
        t.set_action('voting')
        t.park()  # one rendered line (file) + bottom = 2 rows drawn
        assert p._drawn == 1  # only the bottom line remains
        p.close()
        out = stream.getvalue()
        assert '\x1b[?25h' in out  # cursor restored
        assert p._drawn == 0
        # final summary is the trailing content (file still parked → queued)
        assert out.rstrip().endswith(
            'rename: 0/2 \u0444\u0430\u0439\u043b\u043e\u0432 \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u0430\u043d\u043e'
            ' \u00b7 1 \u0433\u043e\u0442\u043e\u0432\u043e \u043a \u043f\u0435\u0440\u0435\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u044e')

    def test_region_height_tracks_active_tasks(self, monkeypatch):
        monkeypatch.setattr('namer.progress._THROTTLE', 0.0)
        p = self._progress(stream=io.StringIO())
        t1 = p.task(1, 'a.mkv')
        t2 = p.task(2, 'b.mkv')
        assert p._drawn == 3  # two file lines + bottom
        t1.park()
        assert p._drawn == 2  # one file line + bottom
        t1.unpark('renaming')
        assert p._drawn == 3
        t1.finish('renamed')
        t2.finish('renamed')
        assert p._drawn == 1  # bottom only
        p.close()


class TestProcessDirectoryIntegration:
    """process_directory runs in parallel and defers history to stdout."""

    @staticmethod
    def _disable_online(monkeypatch):
        from namer.providers import Feed
        monkeypatch.setattr('namer.providers.wikipedia_feed',
                            lambda meta, lang: Feed('wikipedia', {}))
        monkeypatch.setattr('namer.providers.tvmaze_feed',
                            lambda meta, lang: Feed('tvmaze', {}))
        monkeypatch.setattr('namer.wikipedia.enrich_title_via_wiki',
                            lambda meta, lang: False)

    @staticmethod
    def _make_show(tmp_path):
        show = tmp_path / 'Cool Show'
        show.mkdir()
        (show / 'Cool Show S01E01.mkv').write_bytes(b'x')
        (show / 'Cool Show S01E02.mkv').write_bytes(b'x')
        return show

    def test_dry_run_history_to_stdout(self, monkeypatch, tmp_path, capsys):
        self._disable_online(monkeypatch)
        show = self._make_show(tmp_path)
        from namer.core import process_directory
        renamed, total = process_directory(
            str(show), pattern='{season:02d}.{episode:02d}.{ext}', dry_run=True)
        assert (renamed, total) == (2, 2)
        out = capsys.readouterr().out
        assert 'mv "Cool Show S01E01.mkv" \u2192 "01.01.mkv"' in out
        assert 'mv "Cool Show S01E02.mkv" \u2192 "01.02.mkv"' in out

    def test_real_rename_with_progress(self, monkeypatch, tmp_path, capsys):
        self._disable_online(monkeypatch)
        show = self._make_show(tmp_path)
        from namer.core import process_directory
        renamed, total = process_directory(
            str(show), pattern='{season:02d}.{episode:02d}.{ext}', dry_run=False)
        assert (renamed, total) == (2, 2)
        assert (show / '01.01.mkv').exists()
        assert (show / '01.02.mkv').exists()
        assert not (show / 'Cool Show S01E01.mkv').exists()
        out, err = capsys.readouterr()
        assert '\u2713 "Cool Show S01E01.mkv" \u2192 "01.01.mkv"' in out
        # line mode (pytest captures stderr → not a TTY) reports completions
        assert 'renamed [1/2]' in err
        assert 'renamed [2/2]' in err

    def test_empty_directory(self, tmp_path, capsys):
        from namer.core import process_directory
        renamed, total = process_directory(str(tmp_path))
        assert (renamed, total) == (0, 0)
        assert 'No video files found.' in capsys.readouterr().out
