# namer

Rename video/series files using metadata extracted from filenames.

## Usage

```bash
# Rename all video files in the current directory (recursive)
namer

# Use a specific show name (overrides auto-detection)
namer "Breaking Bad"

# Custom pattern
namer -p "{dot_title}.S{season:02d}E{episode:02d}.{quality}.{ext}"

# Dry-run (preview only)
namer -n

# Verbose mode
namer -v
```

## Template Fields

| Field        | Description                           | Example           |
|--------------|---------------------------------------|-------------------|
| `{title}`    | Clean movie/show name (with spaces)   | Breaking Bad      |
| `{dot_title}`| Title with dots (torrent-style)       | Breaking.Bad      |
| `{season}`   | Season number (use `:02d` for padding)| 01                |
| `{episode}`  | Episode number (use `:02d` for padding)| 01               |
| `{ext}`      | File extension (without dot)          | mkv               |
| `{year}`     | Year                                  | 2008              |
| `{quality}`    | Full quality label (with spaces)      | BluRay 1080p x264 |
| `{dot_quality}`| Quality label with dots (torrent-style)| BluRay.1080p.x264 |
| `{resolution}` | Resolution                           | 1080p             |
| `{source}`   | Source                                | BluRay            |
| `{codec}`    | Codec                                 | x264              |
| `{audio}`    | Audio codec                           | DTS               |
| `{hdr}`      | HDR type                              | HDR10             |
| `{mod}`        | Edition modifiers                    | Extended/Unrated  |
| `{ep_title}`   | Episode title (from TMDB)            | Pilot             |
| `{audio_lang}` | Audio languages (comma-separated)    | jpn,eng           |
| `{sub_lang}`   | Subtitle languages (comma-separated) | eng               |
| `{channels}`   | Max audio channels                   | 6                 |

## Default Templates

**Movie:** `{title} ({year}) {mod}.{ext}`
→ `The Matrix (1999) .mkv`

**Series:** `{season:02d}.{episode:02d}. {ep_title}.{ext}`
→ `01.01. Pilot.mkv`
