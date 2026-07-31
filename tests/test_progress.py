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

    def test_finish_prints_compact_line(self):
        stream = io.StringIO()
        p = Progress(total=3, mode='dry-run', stream=stream, enabled=False)
        t1 = p.task(1, 'a.mkv')
        t2 = p.task(2, 'b.mkv')
        t1.set_action('voting')
        t1.park()
        t2.set_new_name('new.mkv')
        t2.finish('renamed')
        p.close()
        out = stream.getvalue()
        # only the completed file is logged, nothing else
        assert out == '  renamed [2/3] b.mkv \u2192 new.mkv\n'

    def test_finish_is_idempotent(self):
        stream = io.StringIO()
        p = Progress(total=1, mode='rename', stream=stream, enabled=False)
        t = p.task(1, 'a.mkv')
        t.finish('renamed')
        t.finish('skipped')  # must be a no-op
        p.close()
        out = stream.getvalue()
        assert out.count('  renamed [1/1]') == 1

    def test_set_action_after_done_is_ignored(self):
        stream = io.StringIO()
        p = Progress(total=1, mode='rename', stream=stream, enabled=False)
        t = p.task(1, 'a.mkv')
        t.finish('renamed')
        t.set_action('voting')
        t.set_new_name('x.mkv')
        p.close()
        # stage/name changes after done print nothing extra
        assert stream.getvalue() == '  renamed [1/1] a.mkv\n'

    def test_line_mode_prints_nothing_until_finish(self):
        stream = io.StringIO()
        p = Progress(total=2, mode='rename', stream=stream, enabled=False)
        p.task(1, 'a.mkv')
        p.task(2, 'b.mkv')
        assert stream.getvalue() == ''
        p.close()
        assert stream.getvalue() == ''  # unfinished files print nothing


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
        assert 'voting' in line
        assert 'Old.Name.S01E01.1080p.mkv' in line

    def test_bar_fills_with_stage(self):
        """The bar fills as the file advances through the stages."""
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


    def test_finished_line_shows_status_and_full_bar(self):
        def mutate(p, t):
            t.set_action('voting')
            t.set_new_name('01.01. New.mkv')
            t.finish('renamed')
        line = self._format(mutate=mutate)
        assert 'renamed' in line
        assert line.count('\u2588') == 20  # full bar
        assert '01.01. New.mkv' in line

    def test_finished_line_keeps_old_and_new_names(self):
        def mutate(p, t):
            t.set_new_name('01.01. New.mkv')
            t.finish('renamed')
        line = self._format(mutate=mutate)
        assert 'Old.Name.S01E01.1080p.mkv' in line
        assert '\u2192' in line
        assert '01.01. New.mkv' in line

    def test_skipped_line_shows_status_and_empty_bar(self):
        def mutate(p, t):
            t.finish('skipped')
        line = self._format(mutate=mutate)
        assert 'skipped' in line
        assert '\u2192' not in line
        assert '\u2588' not in line                       # no filled cells
        assert '[' + ' ' * 20 + ']' in line                # empty bar

    def test_unchanged_and_error_show_empty_bar(self):
        for status in ('unchanged', 'error'):
            def mutate(p, t, status=status):
                t.finish(status)
            line = self._format(mutate=mutate)
            assert status in line
            assert '\u2588' not in line, status
            assert '[' + ' ' * 20 + ']' in line, status


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

    def test_close_keeps_rows_and_shows_cursor(self, monkeypatch):
        monkeypatch.setattr('namer.progress._THROTTLE', 0.0)
        stream = io.StringIO()
        p = self._progress(stream=stream)
        t = p.task(1, 'a.mkv')
        t.set_action('voting')
        p.close()
        out = stream.getvalue()
        assert '\x1b[?25h' in out  # cursor restored
        assert p._drawn == 1        # the file row stays on screen
        assert out.endswith('\x1b[?25h\n')

    def test_finished_lines_stay_and_rows_never_shrink(self, monkeypatch):
        monkeypatch.setattr('namer.progress._THROTTLE', 0.0)
        p = self._progress(stream=io.StringIO())
        t1 = p.task(1, 'a.mkv')
        t2 = p.task(2, 'b.mkv')
        assert p._drawn == 2
        t1.park()             # parked row stays visible
        assert p._drawn == 2
        t1.unpark('renaming')
        t1.finish('renamed')  # finished row stays visible
        assert p._drawn == 2
        t2.finish('unchanged')
        assert p._drawn == 2  # never shrinks
        p.close()

    def test_rows_are_appended_and_never_erased(self, monkeypatch):
        monkeypatch.setattr('namer.progress._THROTTLE', 0.0)
        stream = io.StringIO()
        p = self._progress(total=30, stream=stream)
        for i in range(1, 31):
            p.task(i, f'file{i:02d}.mkv')
        p.close()
        out = stream.getvalue()
        # every row is appended once (with a newline so the terminal
        # scrolls naturally, like any CLI); nothing is rewritten away
        assert out.count('file01.mkv') == 1
        assert out.count('file30.mkv') == 1
        assert out.index('file01.mkv') < out.index('file30.mkv')
        assert out.count('\n') >= 29

    def test_scrolled_off_rows_are_not_redrawn(self, monkeypatch):
        monkeypatch.setattr('namer.progress._THROTTLE', 0.0)
        stream = io.StringIO()
        p = self._progress(total=10, stream=stream)
        p._height = lambda: 3  # tiny terminal: only the last 2 rows visible
        for i in range(1, 11):
            p.task(i, f'file{i:02d}.mkv')
        # now update the FIRST file — its row is in the scrollback
        p._tasks[1].set_action('voting')
        out = stream.getvalue()
        # the redraw must not target the scrolled-off row 1 (cursor-up
        # would clamp at the top edge and corrupt the visible tail)
        assert '\x1b[9A' not in out
        assert '\x1b[2A' not in out  # only rows within height-1 may move

    def test_row_update_rewrites_in_place(self, monkeypatch):
        monkeypatch.setattr('namer.progress._THROTTLE', 0.0)
        stream = io.StringIO()
        p = self._progress(total=2, stream=stream)
        p.task(1, 'a.mkv')
        p.task(2, 'b.mkv')
        t1 = p._tasks[1]
        t1.set_action('voting')       # only row 1 changes
        out = stream.getvalue()
        # row 1 is rewritten in place (cursor up 1, erase, write, back)
        assert '\x1b[1A\r\x1b[2K' in out
        # row 2 text appears exactly once (appended, never rewritten)
        assert out.count('2/2') == 1

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

    def test_dry_run_no_history_in_stdout(self, monkeypatch, tmp_path, capsys):
        self._disable_online(monkeypatch)
        show = self._make_show(tmp_path)
        from namer.core import process_directory
        renamed, total, errors = process_directory(
            str(show), pattern='{season:02d}.{episode:02d}.{ext}', dry_run=True)
        assert (renamed, total) == (2, 2)
        out, err = capsys.readouterr()
        assert 'mv "' not in out  # no deferred rename log on stdout
        # line mode (stderr not a TTY) shows completions with new names
        assert '  renamed [1/2] Cool Show S01E01.mkv \u2192 01.01.mkv' in err
        assert '  renamed [2/2] Cool Show S01E02.mkv \u2192 01.02.mkv' in err

    def test_real_rename_with_progress(self, monkeypatch, tmp_path, capsys):
        self._disable_online(monkeypatch)
        show = self._make_show(tmp_path)
        from namer.core import process_directory
        renamed, total, errors = process_directory(
            str(show), pattern='{season:02d}.{episode:02d}.{ext}', dry_run=False)
        assert (renamed, total) == (2, 2)
        assert (show / '01.01.mkv').exists()
        assert (show / '01.02.mkv').exists()
        assert not (show / 'Cool Show S01E01.mkv').exists()
        out, err = capsys.readouterr()
        assert '\u2713' not in out  # no rename log on stdout
        assert '\u2192' not in out
        # line mode (pytest captures stderr → not a TTY) reports completions
        assert 'renamed [1/2]' in err
        assert 'renamed [2/2]' in err

    def test_skip_shows_in_row_without_warning(self, monkeypatch, tmp_path, capsys):
        self._disable_online(monkeypatch)
        show = tmp_path / 'Cool Show'
        show.mkdir()
        extras = show / 'Featurettes'
        extras.mkdir()
        (extras / 'Episode 101 Animatic.mkv').write_bytes(b'x')
        from namer.core import process_directory
        renamed, total, errors = process_directory(str(show), dry_run=True)
        assert (renamed, total) == (0, 1)
        _, err = capsys.readouterr()
        assert '\u26a0' not in err                       # no ⚠ warning lines
        assert 'skipped [1/1] Episode 101 Animatic.mkv' in err

    def test_empty_directory(self, tmp_path, capsys):
        from namer.core import process_directory
        renamed, total, errors = process_directory(str(tmp_path))
        assert (renamed, total) == (0, 0)
        assert 'No video files found.' in capsys.readouterr().out


class TestDsrGeometry:
    """The live block is addressed from the REAL cursor row (DSR), never
    from the reported terminal height.  Regression: rows below the reported
    height froze at an intermediate state (stuck at 'voting'/'rendering')."""

    def _mark_all_done(self, p):
        """Flip every row to done+renamed without triggering renders."""
        with p._lock:
            for t in p._tasks.values():
                t.state = 'done'
                t.status = 'renamed'

    def test_uses_real_rows_not_reported_height(self, monkeypatch):
        """30 rows on a screen whose *reported* height is 24 (StringIO →
        default 24): DSR reports the cursor at row 30, so all 30 rows stay
        live instead of freezing after row 23."""
        monkeypatch.setattr('namer.progress._THROTTLE', 0.0)
        stream = io.StringIO()
        p = Progress(total=30, mode='rename', stream=stream, enabled=True)
        # cursor row tracks the block size exactly (nothing above the block)
        monkeypatch.setattr(Progress, '_dsr_row', lambda self: self._drawn)
        for i in range(1, 31):
            p.task(i, f'file{i:02d}.mkv')
        self._mark_all_done(p)
        p._dirty = True
        p._render_locked()
        out = stream.getvalue()
        # all 30 rows rewritten: block top = 1, cursor row 30 → move up 29
        assert '\x1b[29A\r' in out
        # the reported-height fallback would cap at 23 rows (\x1b[22A)
        assert '\x1b[22A' not in out
        assert out.count('file01.mkv') == 2   # appended + rewritten
        assert out.count('file30.mkv') == 2
        p.close()

    def test_scroll_tracking_rewrites_only_visible_rows(self, monkeypatch):
        """Once the block scrolls (cursor pinned at row 24 while rows keep
        appending), the block top moves up and only the visible 24 rows are
        rewritten; scrolled-off rows are left untouched."""
        monkeypatch.setattr('namer.progress._THROTTLE', 0.0)
        stream = io.StringIO()
        p = Progress(total=30, mode='rename', stream=stream, enabled=True)
        calls = {'n': 0}

        def fake_dsr(self):
            calls['n'] += 1
            return min(calls['n'], 24)   # cursor hits the bottom row, then scrolls

        monkeypatch.setattr(Progress, '_dsr_row', fake_dsr)
        for i in range(1, 31):
            p.task(i, f'file{i:02d}.mkv')
        assert p._block_top is not None
        self._mark_all_done(p)
        p._dirty = True
        p._render_locked()
        out = stream.getvalue()
        # exactly the 24 on-screen rows are rewritten (move up 23)
        assert '\x1b[23A\r' in out
        # rows 1..6 scrolled off — appended once, never rewritten
        assert out.count('file06.mkv') == 1
        # row 7 is the first visible one — appended and rewritten
        assert out.count('file07.mkv') == 2
        p.close()

    def test_dsr_failure_falls_back_to_reported_height(self):
        """No DSR answer (not a TTY) → the old height-based geometry still
        works and rows keep updating within the reported height."""
        stream = io.StringIO()
        p = Progress(total=10, mode='rename', stream=stream, enabled=True)
        for i in range(1, 11):
            p.task(i, f'file{i:02d}.mkv')
        assert p._block_top is None        # DSR unavailable
        self._mark_all_done(p)
        p._dirty = True
        p._render_locked()
        out = stream.getvalue()
        assert 'file10.mkv' in out
        p.close()

class TestCliExitCode:
    """B9-005: per-file errors must make the CLI exit non-zero (subprocess)."""

    @staticmethod
    def _run(directory, *extra):
        import subprocess, sys
        return subprocess.run(
            [sys.executable, '-m', 'namer', '-d', str(directory)] + list(extra),
            capture_output=True, text=True, timeout=120,
        )

    def test_malformed_pattern_returns_nonzero(self, tmp_path):
        """A worker error (invalid custom pattern) → exit code 1 + error count."""
        movie = tmp_path / 'Movie.2020.mkv'
        movie.write_bytes(b'x')
        proc = self._run(tmp_path, '-n', '-p', '{title')
        assert proc.returncode != 0, f'expected non-zero, got {proc.returncode}'
        combined = (proc.stdout or '') + (proc.stderr or '')
        assert 'error' in combined.lower()
        assert '0/1' in proc.stdout or '0/1' in proc.stderr

    def test_clean_batch_returns_zero(self, tmp_path):
        """A fully successful batch keeps exit code 0."""
        show = tmp_path / 'Show'
        show.mkdir()
        (show / 'Show.S01E01.mkv').write_bytes(b'x')
        proc = self._run(show, '-n', '-p', '{season:02d}.{episode:02d}.{ext}')
        assert proc.returncode == 0, proc.stderr

