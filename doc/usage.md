# namer — CLI reference

`namer` renames video files using metadata extracted from the filename, the
directory tree, and (when keys are available) online providers.  It is
deterministic and conservative: when the metadata is ambiguous it **leaves
the file in place** rather than risk a wrong rename.

## Synopsis

```
namer [TITLE] [options]
```

## Options

| Option | Description |
|---|---|
| `TITLE` (positional), `-t/--title` | Show/movie name; overrides auto-detection from the filename. |
| `-sn N`, `--season-number N` | Force season `N`; also marks the file as a series. |
| `-p PATTERN`, `--pattern` | Custom rename template (see *Template fields*). |
| `-n`, `--dry-run` | Preview changes without renaming. |
| `--tmdb-key KEY` | TMDB API key; enables episode-title and year enrichment. |
| `-l CODE`, `--language CODE` | Language for show/episode names (`en`, `ru`, `de`, ...). Default `en`. |
| `-d DIR`, `--directory DIR` | Process `DIR` instead of the current directory. |
| `-v`, `--verbose` | Verbose output (shows subdirectory paths). |
| `-V`, `--version` | Print version and exit. |

## Examples

```bash
# Rename all videos in the current directory (recursive)
namer

# Force a known show name (skips auto-detection)
namer "Breaking Bad"
namer -t "Breaking Bad"

# Force season 2 of a show
namer -sn 2 -t "Show Name"

# Custom pattern
namer -p "{dot_title}.S{season:02d}E{episode:02d}.{quality}.{ext}"

# Preview only (dry-run)
namer -n

# Enrich episode titles from TMDB
namer --tmdb-key YOUR_KEY

# Russian episode/show names
namer -l ru

# Process a specific directory
namer -d /path/to/videos
```

## Template fields

| Field | Meaning | Example |
|---|---|---|
| `{title}` | Clean movie/show name | Breaking Bad |
| `{dot_title}` | Title with dots (torrent-style) | Breaking.Bad |
| `{season}` | Season number | 1 |
| `{episode}` | Episode number | 1 |
| `{ext}` | Extension, no dot | mkv |
| `{year}` | Year | 2008 |
| `{quality}` | Full quality label (spaces) | BluRay 1080p x264 |
| `{dot_quality}` | Quality label with dots | BluRay.1080p.x264 |
| `{resolution}` | Resolution | 1080p |
| `{source}` | Source | BluRay |
| `{codec}` | Codec | x264 |
| `{audio}` | Audio codec | DTS |
| `{hdr}` | HDR type | HDR10 |
| `{mod}` | Edition modifiers | Extended/Unrated |
| `{ep_title}` | Episode title | Pilot |
| `{audio_lang}` | Audio languages (comma-separated) | jpn,eng |
| `{sub_lang}` | Subtitle languages (comma-separated) | eng |
| `{channels}` | Max audio channels | 6 |

Use `:02d` to zero-pad a numeric field, e.g. `{season:02d}`.

## Default templates

| Kind | Template | Example |
|---|---|---|
| Movie | `{title} ({year}) {mod}.{ext}` | `The Matrix (1999) .mkv` |
| Series | `{season:02d}.{episode:02d}. {ep_title}.{ext}` | `01.01. Pilot.mkv` |

## Behaviour notes

- **No-clobber rename.** `namer` never overwrites an existing file; the move
  is atomic (`renameat2(RENAME_NOREPLACE)` or `link+unlink` on filesystems
  without hard links).
- **Conservative on ambiguity.** If season/episode cannot be resolved
  confidently, or providers conflict on them, the file is left in place rather
  than renamed with a guessed value (`Decision L3`).
- **Specials** map to season `0` by convention.
- **Multi-episode** files (`S01E01-02`, `S01E01E02`, `1x01-1x02`) are detected
  and listed; the rename uses the single episode.
