"""Live progress display for batch operations.

One file = one terminal row.  Each row is printed when the file is claimed
and rewritten in place (ANSI cursor moves on a TTY) as the file advances
through the pipeline stages.  When the batch is taller than the terminal
the oldest rows scroll off the top into the scrollback, exactly like any
ordinary CLI tool — nothing is ever erased.  On a pipe or file a compact
line is logged per completed file instead.  Every state change is guarded
by a lock, so worker threads may update freely.

The caller prints diagnostics (skip reasons) to stderr after ``close()``.
"""

import os
import shutil
import sys
import threading
import time
import unicodedata

# Stage pipeline in execution order; the per-file bar fills up as the
# file advances through these stages.
STAGES = ('querying providers', 'parsing feeds', 'voting', 'rendering', 'renaming')
_STAGE_IDX = {name: i for i, name in enumerate(STAGES, start=1)}

_BAR_FILLED = '\u2588'   # █
_BAR_EMPTY = '\u2591'    # ░
_ELLIPSIS = '\u2026'     # …
_ARROW = ' \u2192 '      # →
_BAR_WIDTH = 20
_THROTTLE = 0.1          # seconds between in-place redraws


def _char_width(ch: str) -> int:
    """Terminal columns taken by one character (East-Asian wide = 2)."""
    return 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1


def display_width(text: str) -> int:
    """Number of terminal columns *text* occupies."""
    return sum(_char_width(ch) for ch in text)


def truncate(text: str, max_width: int) -> str:
    """Truncate *text* to at most *max_width* terminal columns, adding …."""
    if max_width <= 0:
        return ''
    if display_width(text) <= max_width:
        return text
    result = ''
    width = 0
    for ch in text:
        w = _char_width(ch)
        if width + w > max_width - 1:  # leave room for the ellipsis
            break
        result += ch
        width += w
    return result + _ELLIPSIS


class Task:
    """One file's progress row.  All methods are thread-safe."""

    __slots__ = ('progress', 'index', 'total', 'basename', 'new_name',
                 'stage', 'status', 'state')

    def __init__(self, progress, index: int, total: int, basename: str):
        self.progress = progress
        self.index = index
        self.total = total
        self.basename = basename
        self.new_name = None
        self.stage = 0            # ordinal in STAGES (0 = none yet)
        self.status = None        # terminal state label, e.g. 'skipped'
        self.state = 'active'     # 'active' | 'parked' | 'done'

    # ── public API (callable from any thread) ────────────────────────────

    def set_action(self, action: str):
        """Switch the file to a pipeline stage (see STAGES)."""
        with self.progress._lock:
            if self.state == 'done':
                return
            idx = _STAGE_IDX.get(action)
            if idx is not None and idx > self.stage:
                self.stage = idx
            self.progress._touch_locked()

    def set_new_name(self, new_name: str):
        """Reveal the chosen name after '→' (rendering stage and later)."""
        with self.progress._lock:
            if self.state == 'done':
                return
            self.new_name = new_name
            self.progress._touch_locked()

    def park(self):
        """Generation finished; the row stays and shows the rendered name."""
        with self.progress._lock:
            if self.state != 'active':
                return
            self.state = 'parked'
            self.progress._touch_locked()

    def unpark(self, action: str = None):
        """Bring the row back for the rename pass."""
        with self.progress._lock:
            if self.state != 'parked':
                return
            self.state = 'active'
            if action:
                idx = _STAGE_IDX.get(action)
                if idx is not None and idx > self.stage:
                    self.stage = idx
            self.progress._touch_locked()

    def finish(self, status: str):
        """Mark the file processed; its row stays on screen forever."""
        with self.progress._lock:
            if self.state == 'done':
                return
            self.state = 'done'
            self.status = status
            self.progress._touch_locked()
            if not self.progress._use_ansi:
                line = f'  {status} [{self.index}/{self.total}] {self.basename}'
                if self.new_name:
                    line += f'{_ARROW}{self.new_name}'
                self.progress._write(line + '\n')


class Progress:
    """Batch progress: one row per file, rows scroll like a plain CLI.

    Rows are appended at the bottom (so the terminal scrolls the oldest
    ones into the scrollback) and only the *changed* rows are rewritten
    in place on a TTY; nothing is erased.

    Args:
        total: Number of files in the batch.
        mode:  Kept for backwards compatibility (unused).
        stream: Where to draw (defaults to stderr).
        enabled: Force live region on/off; None = auto-detect TTY.
    """

    def __init__(self, total: int, mode: str = 'rename',
                 stream=None, enabled=None):
        self.total = max(int(total), 1)
        self.mode = mode
        self._stream = stream if stream is not None else sys.stderr
        self._use_ansi = enabled if enabled is not None else bool(
            getattr(self._stream, 'isatty', lambda: False)())
        self._lock = threading.Lock()
        self._tasks = {}      # index -> Task
        self._order = []      # claim order of indices
        self._rendered = []   # last rendered text per row (parallel to _order)
        self._closed = False
        self._drawn = 0       # rows on screen; never shrinks
        self._cursor_hidden = False
        self._dirty = False
        self._last_render = 0.0
        self._timer = None

    # ── public API ───────────────────────────────────────────────────────

    def task(self, index: int, basename: str) -> Task:
        """Claim the progress row for file *index* (1-based)."""
        with self._lock:
            handle = Task(self, index, self.total, basename)
            self._tasks[index] = handle
            self._order.append(index)
            self._append_locked()
            return handle

    def is_live(self) -> bool:
        """True when an ANSI live display is active (caller may suppress
        verbose per-file output that would interleave with it)."""
        return self._use_ansi

    def close(self):
        """Render the final state, restore the cursor and leave it on a
        fresh line below the last row (rows stay on screen)."""
        with self._lock:
            if self._closed:
                return
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if self._use_ansi and self._drawn:
                self._render_locked()
                if self._cursor_hidden:
                    self._write('\x1b[?25h')
                self._write('\n')
            self._closed = True

    # ── internals ────────────────────────────────────────────────────────

    def _write(self, text: str):
        self._stream.write(text)
        self._stream.flush()

    def _append_locked(self):
        """Put the newly claimed row at the bottom (appends, scrolls)."""
        if self._closed or not self._use_ansi:
            return
        line = self._format_line(self._tasks[self._order[-1]], self._width())
        out = self._stream
        if self._drawn == 0:
            out.write('\x1b[?25l')   # hide cursor while live
            self._cursor_hidden = True
        else:
            out.write('\n')          # fresh row; scrolls at the bottom edge
        out.write('\x1b[2K' + line + '\r')
        self._rendered.append(line)
        self._drawn += 1
        self._last_render = time.monotonic()
        self._dirty = False
        out.flush()

    def _touch_locked(self):
        if self._closed:
            return
        self._dirty = True
        if not self._use_ansi:
            return
        now = time.monotonic()
        if now - self._last_render >= _THROTTLE:
            self._render_locked()
        elif self._timer is None:
            delay = _THROTTLE - (now - self._last_render)
            self._timer = threading.Timer(max(delay, 0.0), self._flush_timer)
            self._timer.daemon = True
            self._timer.start()

    def _flush_timer(self):
        with self._lock:
            self._timer = None
            if not self._closed and self._dirty:
                self._render_locked()

    def _render_locked(self):
        """Rewrite only the on-screen rows whose text changed; keep the
        cursor at the bottom row.  Rows that already scrolled into the
        terminal's scrollback are never redrawn (that would corrupt the
        visible tail), they keep their state at scroll time."""
        if not self._dirty or self._closed or not self._order:
            return
        width = self._width()
        height = max(3, self._height())
        start = max(0, self._drawn - (height - 1))  # first on-screen row
        self._last_render = time.monotonic()
        self._dirty = False
        out = self._stream
        for i, index in enumerate(self._order):
            t = self._tasks.get(index)
            if t is None:
                continue
            line = self._format_line(t, width)
            if i < start:
                continue                  # scrolled into history: keep as is
            if self._rendered[i] == line:
                continue
            from_bottom = self._drawn - 1 - i
            if from_bottom:
                out.write(f'\x1b[{from_bottom}A\r')
            out.write('\x1b[2K' + line)
            if from_bottom:
                out.write(f'\x1b[{from_bottom}B\r')
            self._rendered[i] = line
        out.flush()

    def _format_line(self, t: Task, width: int) -> str:
        prefix = f'{t.index:>{len(str(t.total))}}/{t.total} '
        if t.state == 'done':
            filled = _BAR_WIDTH
            action = t.status if t.status else 'done'
        else:
            filled = t.stage * (_BAR_WIDTH // len(STAGES)) if t.stage else 0
            action = STAGES[t.stage - 1] if t.stage else ''
        bar = _BAR_FILLED * filled + _BAR_EMPTY * (_BAR_WIDTH - filled)
        fixed = display_width(prefix) + _BAR_WIDTH + 3 + display_width(action) + 3
        remaining = width - fixed
        if t.new_name:
            body = remaining - display_width(_ARROW)
            old = truncate(t.basename, body * 3 // 5)
            new = truncate(t.new_name, body * 2 // 5)
            return f'{prefix}[{bar}] {action} \u00b7 {old}{_ARROW}{new}'
        old = truncate(t.basename, remaining)
        return f'{prefix}[{bar}] {action} \u00b7 {old}'

    def _width(self) -> int:
        try:
            size = os.get_terminal_size(self._stream.fileno())
        except (OSError, ValueError, AttributeError):
            size = shutil.get_terminal_size()
        return max(40, size.columns)

    def _height(self) -> int:
        try:
            size = os.get_terminal_size(self._stream.fileno())
        except (OSError, ValueError, AttributeError):
            size = shutil.get_terminal_size()
        return max(3, size.lines)
