"""Live progress display for batch operations.

One file = one line.  Lines accumulate: finished files stay visible and
scroll with the terminal, the summary is always the last line.  On a TTY
the lines are redrawn in place on stderr using ANSI cursor moves
(throttled to ~10 Hz); once the region is taller than the terminal only
the visible tail is rewritten and the older lines scroll into the
terminal's scrollback.  On a pipe or file a compact line is logged per
completed file instead.  Every state change is guarded by a lock, so
worker threads may update freely.

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


def visible_window(lines, height: int) -> list:
    """Tail of *lines* that fits the terminal: the last *height* rows.

    Older rows are left in the terminal scrollback and are not redrawn.
    """
    return lines[-min(len(lines), height):]


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
        """Generation finished; the line stays and shows the rendered name."""
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
        """Mark the file processed; its line stays on screen (scrolls)."""
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
                line = f'  {status} [{self.index}/{self.total}] {self.basename}'
                if self.new_name:
                    line += f'{_ARROW}{self.new_name}'
                self.progress._write(line + '\n')


class Progress:
    """Batch progress: one line per file (finished ones stay visible).

    Args:
        total: Number of files in the batch.
        mode:  Bottom-line label ('dry-run' or 'rename').
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
        self._done = 0
        self._queued = 0      # parked, awaiting the rename pass
        self._closed = False
        self._drawn = 0       # lines rendered so far (never shrinks)
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
        """Stop the region: keep the lines on screen, restore the cursor
        and leave it on a fresh line below them."""
        with self._lock:
            if self._closed:
                return
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if self._use_ansi and self._dirty:
                self._render_locked()  # show the final state
            self._closed = True
            if self._use_ansi and self._drawn:
                self._write('\x1b[?25h\n')  # keep region, cursor below it
            else:
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
        height = max(3, self._height())
        lines = []
        for i in self._order:
            t = self._tasks.get(i)
            if t is not None:
                lines.append(self._format_line(t, width))
        lines.append(self._bottom_locked())
        self._last_render = time.monotonic()
        self._dirty = False

        out = self._stream
        window = visible_window(lines, height)
        if self._drawn == 0:
            out.write('\x1b[?25l')  # hide cursor while live
        else:
            out.write(f'\x1b[{min(self._drawn, height) - 1}A\r')
        for j, ln in enumerate(window):
            out.write('\x1b[2K')  # erase previous content of this row
            if j < len(window) - 1:
                out.write(ln + '\n')
            else:
                out.write(ln + '\r')  # stay on the last row for redraws
        self._drawn = len(lines)
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

    def _bottom_locked(self) -> str:
        bottom = (f'{self.mode}: {self._done}/{self.total} '
                  f'\u0444\u0430\u0439\u043b\u043e\u0432 \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u0430\u043d\u043e')
        if self._queued:
            bottom += (f' \u00b7 {self._queued} '
                       f'\u0433\u043e\u0442\u043e\u0432\u043e \u043a \u043f\u0435\u0440\u0435\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u044e')
        return bottom

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
