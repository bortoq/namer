"""Live progress display for batch operations.

One file = one terminal row, appended in its FINAL state when the file is
processed (renamed / skipped / unchanged / error), so rows that scroll
into the scrollback always show the completed result — like any ordinary
CLI tool.  While the batch is being analysed (the slow, parallel phase)
a single live "activity" line shows the file currently being processed
and its pipeline stage; it is dropped when the rename pass starts.

On a pipe or file (no TTY) a compact line is logged per completed file
instead.  Every state change is guarded by a lock, so worker threads may
update freely.  The caller prints no diagnostics after ``close()``: the
skip/error status is visible on each file's own row.
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
_THROTTLE = 0.1          # seconds between activity-line redraws


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
                 'stage', 'status', 'state', 'committed')

    def __init__(self, progress, index: int, total: int, basename: str):
        self.progress = progress
        self.index = index
        self.total = total
        self.basename = basename
        self.new_name = None
        self.stage = 0            # ordinal in STAGES (0 = none yet)
        self.status = None        # terminal state label, e.g. 'skipped'
        self.state = 'active'     # 'active' | 'parked' | 'done'
        self.committed = False    # row already written to the stream

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
        """Generation finished; the row appears later in its final state."""
        with self.progress._lock:
            if self.state != 'active':
                return
            self.state = 'parked'
            self.progress._settle_locked()
            self.progress._touch_locked()

    def unpark(self, action: str = None):
        """Bring the row back for the rename pass."""
        with self.progress._lock:
            if self.state != 'parked':
                return
            self.state = 'active'
            self.progress._active_count += 1
            if action:
                idx = _STAGE_IDX.get(action)
                if idx is not None and idx > self.stage:
                    self.stage = idx
            self.progress._touch_locked()

    def finish(self, status: str):
        """Mark the file processed; its row appears in this final state."""
        with self.progress._lock:
            if self.state == 'done':
                return
            from_active = self.state == 'active'
            self.state = 'done'
            self.status = status
            if from_active:
                self.progress._settle_locked()
            if not self.progress._use_ansi:
                line = f'  {status} [{self.index}/{self.total}] {self.basename}'
                if self.new_name:
                    line += f'{_ARROW}{self.new_name}'
                self.progress._write(line + '\n')
            elif self.progress._activity is None:
                self.progress._append_locked(self)
            # else: generation still running — the row is appended by
            # commit() during the rename pass.

    def commit(self):
        """Append the row if the finish happened during generation and was
        deferred (e.g. an error in a worker while others still run)."""
        with self.progress._lock:
            if self.state != 'done' or self.committed:
                return
            if not self.progress._use_ansi:
                return  # line mode already printed at finish()
            self.progress._append_locked(self)


class Progress:
    """Batch progress: one row per processed file, rows scroll like a
    plain CLI and always show the final per-file state.

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
        self._tasks = {}        # index -> Task
        self._order = []        # claim order of indices
        self._closed = False
        self._drawn = 0         # committed rows on screen; never shrinks
        self._active_count = 0  # tasks still in the 'active' state
        self._activity = None   # index of the task on the live line
        self._activity_text = ''
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
            self._active_count += 1
            self._activity = index
            self._touch_locked()
            return handle

    def is_live(self) -> bool:
        """True when an ANSI live display is active (caller may suppress
        verbose per-file output that would interleave with it)."""
        return self._use_ansi

    def close(self):
        """Drop the live line, restore the cursor and leave it on a fresh
        row (committed rows stay on screen)."""
        with self._lock:
            if self._closed:
                return
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if self._use_ansi:
                if self._activity is not None:
                    if self._cursor_hidden:
                        self._write('\r\x1b[2K')
                    self._activity = None
                    self._activity_text = ''
                elif self._drawn:
                    self._write('\n')
                if self._cursor_hidden:
                    self._write('\x1b[?25h')
            self._closed = True

    # ── internals ────────────────────────────────────────────────────────

    def _write(self, text: str):
        self._stream.write(text)
        self._stream.flush()

    def _settle_locked(self):
        """A task left the 'active' state.  When the whole generation phase
        is over, drop the live activity line."""
        self._active_count -= 1
        if self._active_count <= 0 and self._activity is not None:
            if self._use_ansi and self._cursor_hidden:
                self._write('\r\x1b[2K')
            self._activity = None
            self._activity_text = ''
            self._dirty = False

    def _append_locked(self, t: Task):
        """Write the finished row at the bottom (appends, scrolls)."""
        if self._closed or not self._use_ansi:
            return
        line = self._format_line(t, self._width())
        out = self._stream
        if not self._cursor_hidden:
            out.write('\x1b[?25l')   # hide cursor while live
            self._cursor_hidden = True
        if self._activity is not None:
            if self._cursor_hidden:
                out.write('\r\x1b[2K')  # the live line becomes this row
            self._activity = None
            self._activity_text = ''
        elif self._drawn:
            out.write('\n')             # fresh row; scrolls at the edge
        out.write(line + '\r')
        t.committed = True
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
        """Refresh the live activity line (shown while files are being
        analysed in pass 1)."""
        if not self._dirty or self._closed:
            return
        self._dirty = False
        if self._drawn or self._activity is None:
            return
        line = self._format_line(self._tasks[self._activity], self._width())
        if line == self._activity_text:
            return
        out = self._stream
        if not self._cursor_hidden:
            out.write('\x1b[?25l')
            self._cursor_hidden = True
        out.write('\r\x1b[2K' + line + '\r')
        self._activity_text = line
        self._last_render = time.monotonic()
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
