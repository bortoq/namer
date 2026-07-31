"""Live progress display for batch operations.

One file = one line.  On a TTY the lines are redrawn in place on stderr
using ANSI cursor moves (throttled to ~10 Hz); on a pipe or file a
compact one-line-per-completion log is written instead.  Every state
change is guarded by a lock, so worker threads may update freely.

The caller prints the final per-file results to stdout after ``close()``.
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
_THROTTLE = 0.1          # seconds between redraws


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
    """One file's progress line.  All methods are thread-safe."""

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
        """Generation finished; hide the line until the rename pass."""
        with self.progress._lock:
            if self.state != 'active':
                return
            self.state = 'parked'
            self.progress._queued += 1
            self.progress._touch_locked()

    def unpark(self, action: str = None):
        """Bring the line back for the rename pass."""
        with self.progress._lock:
            if self.state != 'parked':
                return
            self.state = 'active'
            self.progress._queued -= 1
            if action:
                idx = _STAGE_IDX.get(action)
                if idx is not None and idx > self.stage:
                    self.stage = idx
            self.progress._touch_locked()

    def finish(self, status: str):
        """Mark the file processed; its line leaves the live region."""
        with self.progress._lock:
            if self.state == 'done':
                return
            if self.state == 'parked':
                self.progress._queued -= 1
            self.state = 'done'
            self.status = status
            self.progress._done += 1
            self.progress._touch_locked()
            if not self.progress._use_ansi:
                self.progress._write(
                    f'  {status} [{self.index}/{self.total}] {self.basename}\n')


class Progress:
    """Batch progress: one live line per in-flight file + a bottom summary.

    Args:
        total: Number of files in the batch.
        mode:  Bottom-line label ('dry-run' or 'rename').
        max_concurrent: Upper bound on simultaneously shown lines.
        stream: Where to draw (defaults to stderr).
        enabled: Force live region on/off; None = auto-detect TTY.
    """

    def __init__(self, total: int, mode: str = 'rename',
                 max_concurrent: int = 4, stream=None, enabled=None):
        self.total = max(int(total), 1)
        self.mode = mode
        self.max_concurrent = max(1, int(max_concurrent) or 1)
        self._stream = stream if stream is not None else sys.stderr
        self._use_ansi = enabled if enabled is not None else bool(
            getattr(self._stream, 'isatty', lambda: False)())
        self._lock = threading.Lock()
        self._tasks = {}      # index -> Task
        self._order = []      # claim order of indices
        self._done = 0
        self._queued = 0      # parked, awaiting the rename pass
        self._closed = False
        self._drawn = 0       # lines currently occupying the region
        self._dirty = False
        self._last_render = 0.0
        self._timer = None

    # ── public API ───────────────────────────────────────────────────────

    def task(self, index: int, basename: str) -> Task:
        """Claim the progress line for file *index* (1-based)."""
        with self._lock:
            handle = Task(self, index, self.total, basename)
            self._tasks[index] = handle
            self._order.append(index)
            self._touch_locked()
            return handle

    def is_live(self) -> bool:
        """True when an ANSI live region is active (caller may suppress
        verbose per-file output that would interleave with it)."""
        return self._use_ansi

    def close(self):
        """Erase the live region and print the final summary line."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if self._use_ansi and self._drawn:
                self._erase_region_locked()
            self._write(self._bottom_locked() + '\n')

    # ── internals ────────────────────────────────────────────────────────

    def _write(self, text: str):
        self._stream.write(text)
        self._stream.flush()

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
        if not self._dirty or self._closed:
            return
        width = self._width()
        lines = []
        for i in self._order:
            t = self._tasks.get(i)
            if t is not None and t.state == 'active':
                lines.append(self._format_line(t, width))
        lines.append(self._bottom_locked())
        self._last_render = time.monotonic()
        self._dirty = False

        out = self._stream
        n_prev, n_new = self._drawn, len(lines)
        if self._drawn == 0:
            out.write('\x1b[?25l')  # hide cursor while live
        else:
            out.write(f'\x1b[{self._drawn}A\r')  # up to region start
        for j, line in enumerate(lines):
            if j < n_prev:
                out.write('\x1b[2K')  # erase previous content of this row
            out.write(line + '\n')
        if n_new < n_prev:  # region shrank: clear leftover rows
            for _ in range(n_prev - n_new):
                out.write('\x1b[2K\n')
            out.write(f'\x1b[{n_prev - n_new}A')  # back below new region
        self._drawn = n_new
        out.flush()

    def _erase_region_locked(self):
        out = self._stream
        out.write(f'\x1b[{self._drawn}A\r')
        for j in range(self._drawn):
            out.write('\x1b[2K')
            if j < self._drawn - 1:
                out.write('\n')
        out.write('\x1b[?25h')  # show cursor again
        out.flush()
        self._drawn = 0

    def _format_line(self, t: Task, width: int) -> str:
        prefix = f'{t.index:>{len(str(t.total))}}/{t.total} '
        filled = t.stage * (_BAR_WIDTH // len(STAGES)) if t.stage else 0
        bar = _BAR_FILLED * filled + _BAR_EMPTY * (_BAR_WIDTH - filled)
        action = STAGES[t.stage - 1] if t.stage else ''
        fixed = display_width(prefix) + _BAR_WIDTH + 3 + display_width(action) + 3
        remaining = width - fixed
        if t.new_name:
            body = remaining - display_width(_ARROW)
            old = truncate(t.basename, body * 3 // 5)
            new = truncate(t.new_name, body * 2 // 5)
            line = f'{prefix}[{bar}] {action} \u00b7 {old}{_ARROW}{new}'
        else:
            old = truncate(t.basename, remaining)
            line = f'{prefix}[{bar}] {action} \u00b7 {old}'
        return line

    def _bottom_locked(self) -> str:
        bottom = f'{self.mode}: {self._done}/{self.total} \u0444\u0430\u0439\u043b\u043e\u0432 \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u0430\u043d\u043e'
        if self._queued:
            bottom += f' \u00b7 {self._queued} \u0433\u043e\u0442\u043e\u0432\u043e \u043a \u043f\u0435\u0440\u0435\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u044e'
        return bottom

    def _width(self) -> int:
        try:
            size = os.get_terminal_size(self._stream.fileno())
        except (OSError, ValueError, AttributeError):
            size = shutil.get_terminal_size()
        return max(40, size.columns)
