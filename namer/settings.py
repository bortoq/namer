"""Namer configuration — templates and constants."""

# ── Video file extensions ────────────────────────────────────────────────
VIDEO_EXTENSIONS = {
    '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm',
    '.m4v', '.m2ts', '.ts', '.mpg', '.mpeg', '.vob', '.iso',
}

# ── Rename templates ─────────────────────────────────────────────────────
# These are Python format-strings. Available placeholders:
#
#   {title}     — Clean movie/show name (with spaces)
#   {dot_title} — Clean name with dots instead of spaces (torrent-style)
#   {season}    — Season number (int, use :02d for zero-padding)
#   {episode}   — Episode number (int, use :02d for zero-padding)
#   {ext}       — File extension (without dot, e.g. "mkv")
#   {year}      — Year (int, 0 if not detected)
#   {quality}    — Full quality label (e.g. "BluRay 1080p x264")
#   {dot_quality}— Quality label with dots (e.g. "BluRay.1080p.x264")
#   {resolution}— Resolution string (e.g. "1080p")
#   {source}    — Source string (e.g. "BluRay", "WEB-DL")
#   {codec}     — Codec string (e.g. "x264", "HEVC")
#   {audio}     — Audio codec (e.g. "DTS", "AAC")
#   {hdr}       — HDR type (e.g. "HDR10")
#   {mod}       — Modifier string (e.g. "Director's Cut", "Extended")
#   {ep_title}   — Episode title (from TMDB enrichment)
#   {audio_lang} — Audio languages (comma-separated, from ffprobe, e.g. "jpn,eng")
#   {sub_lang}  — Subtitle languages (comma-separated, from ffprobe, e.g. "eng")
#   {channels}  — Max audio channels (from ffprobe, e.g. 6 for 5.1)
#

TEMPLATE_MOVIE = '{title} ({year}) {mod}.{ext}'
TEMPLATE_SERIES = '{season:02d}.{episode:02d}. {ep_title}.{ext}'

# ── Concurrency ──────────────────────────────────────────────────────────
# How many files are processed in parallel.  Lookups are I/O-bound
# (network requests with timeouts), so a handful of workers hides
# per-request latency; keep it small to stay polite to the APIs.
MAX_CONCURRENT_FILES = 4

# ── Invalid filename characters ──────────────────────────────────────────
# Characters forbidden in filenames (Windows NTFS/FAT/exFAT and POSIX).
INVALID_CHARS = frozenset('\\/:*?"<>|') | frozenset(chr(c) for c in range(0x20))

# Unicode lookalikes for forbidden characters, so a readable name survives
# instead of being mangled into underscores.  A value may be:
#   - a string: the character is replaced 1:1;
#   - an (open, close) pair: the first occurrence becomes *open*, the
#     second *close*, and so on — paired quotes come out as “...” rather
#     than “...“.
# Forbidden characters without an entry fall back to '_' (see core.py).
#
#   forbidden  →  replacement                  example
#   ?          →  ？ fullwidth question mark    Lost S02E21 - ？.mp4
#   *          →  × heavy asterisk              Сборник ×××.mp3
#   :          →  ∶ ratio sign                  Лекция 1∶ Введение.mkv
#   /          →  ∕ division slash              Проект 2026∕07.docx
#   \          →  ∖ set minus                   Папка ∖ Архив.zip
#   "          →  “ ” smart double quotes       Фильм “Матрица”.mkv
#   <          →  ‹ single left angle           Эпизод ‹Режиссерская версия›.mkv
#   >          →  › single right angle
INVALID_CHAR_REPLACEMENTS = {
    '?': '？',
    '*': '×',
    ':': '∶',
    '/': '∕',
    '\\': '∖',
    '"': ('“', '”'),
    '<': '‹',
    '>': '›',
}
