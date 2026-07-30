"""Rename engine — generates new names and performs (or previews) rename."""

import os
import re
import string
import sys
from typing import List, Tuple

from namer import settings
from namer.parser import parse_file
from namer.settings import TEMPLATE_MOVIE, TEMPLATE_SERIES


def _template_uses(template: str, field: str) -> bool:
    """Check if a format-string *template* uses *field* (with any format spec)."""
    for _, field_name, _, _ in string.Formatter().parse(template):
        if field_name == field:
            return True
    return False


def _sanitize_filename(name: str) -> str:
    """Replace filesystem-invalid characters with safe alternatives.

    Handles characters invalid on Windows (NTFS/FAT/exFAT) and POSIX:
      \\  /  :  *  ?  "  <  >  |  and control chars (0x00-0x1F).
    Also replaces trailing dots/spaces which are invalid on Windows.
    """
    # Replace invalid chars with underscore
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', name)
    # Windows forbids trailing dot or space
    name = re.sub(r'[. ]+$', '', name)
    return name




def _format_template(template: str, meta: dict) -> str:
    """Apply *meta* dict to *template* via str.format().

    Cleans up empty brackets and double-spaces afterward.
    """
    try:
        new_name = template.format(**meta)
    except KeyError as e:
        print(f'  ⚠ Unknown placeholder in template: {e}', file=sys.stderr)
        return ''

    # Remove empty/falsy brackets / parens
    new_name = re.sub(r'\s*\[\s*\]\s*', '', new_name)
    new_name = re.sub(r'\s*\(\s*\)\s*', '', new_name)
    new_name = re.sub(r'\s*\{\s*}', '', new_name)
    new_name = re.sub(r'\s*\(\s*0\s*\)\s*', '', new_name)  # (0) = missing year
    # Remove space before dot when the dot starts the extension (e.g. "{title} {mod}.{ext}" -> ".mkv")
    # Must NOT match space before content dots like "...In Translation" in the ep_title.
    # Use a positive lookahead for known video extensions.
    new_name = re.sub(r'\s+(?=\.(?:mkv|mp4|avi|m2ts|ts|m4v|mov|wmv|flv|webm|mpg|mpeg|vob|iso)$)', '', new_name)
    # Collapse double dots from empty fields (e.g. "Title..S01" when ep_title is empty)
    # Only collapse when surrounded by non-dot, non-space characters, preserving
    # triple-dot ellipsis in episode titles like "...In Translation"
    new_name = re.sub(r'(?<![.\s])\.{2,}(?![.\s])', '.', new_name)
    new_name = re.sub(r'\s+', ' ', new_name).strip()
    new_name = re.sub(r'[. ]$', '', new_name)
    new_name = _sanitize_filename(new_name)
    return new_name


def generate_new_name(
    file_path: str,
    known_title: str = '',
    pattern: str = '',
    tmdb_key: str = '',
    season_number: int = 0,
    language: str = "en",
    language_explicit: bool = False,
) -> Tuple[str, dict]:
    """Generate a new filename for *file_path*.

    Args:
        file_path: Absolute or relative path to a video file.
        known_title: If provided, overrides the auto-detected title.
        pattern: Custom template.  If empty, uses default
                 (*TEMPLATE_SERIES* or *TEMPLATE_MOVIE*).
        tmdb_key: TMDB API key for episode title / year enrichment.
        season_number: Explicit season number (overrides auto-detection).
        language: Two-letter language code (e.g. "en", "ru", "de").

    Returns:
        ``(new_basename, metadata_dict)``
    """
    meta = parse_file(file_path)
    meta['_skip'] = False
    meta['_language_explicit'] = language_explicit

    # ── Supplementary content check ────────────────────────────────────
    if not meta.get('_skip'):
        from namer.extras import is_supplementary, describe_supplementary
        if is_supplementary(file_path):
            meta['_skip'] = True
            meta['_skip_reason'] = describe_supplementary(file_path)
            return os.path.basename(file_path), meta

    # ── Override title ─────────────────────────────────────────────────
    if known_title:
        meta['title'] = known_title
        meta['dot_title'] = re.sub(r'\s+', '.', known_title.strip())

    # ── Season override ────────────────────────────────────────────────
    if season_number > 0:
        meta['season'] = season_number

    # Save whether ep_title was extracted FROM FILENAME (vs from ffprobe etc.)
    filename_ep_title = meta.get('ep_title', '')

    # ── Phase 1: Collect show name hints ───────────────────────────────

    # 1a. ffprobe format tags — may contain show_name / embedded title
    try:
        from namer.ffprobe import get_format_metadata
        ff_tags = get_format_metadata(file_path)
        if ff_tags.get('show_name') and not known_title:
            meta['title'] = ff_tags['show_name']
            meta['dot_title'] = re.sub(r'\s+', '.', ff_tags['show_name'].strip())
        if ff_tags.get('ep_title') and not filename_ep_title:
            # Only use ffprobe ep_title if filename didn't have one
            meta['ep_title'] = ff_tags['ep_title']
    except (ImportError, FileNotFoundError):
        pass

    # 1b. Directory path heuristic — use directory tree for show name
    #     Also detect season from directory names (e.g. "Show S7", "Season 7")
    from namer.parser import title_from_path, _SERIES_PATTERN
    title_from_filename = known_title or meta.get('_original_title', meta.get('title', ''))
    needs_dir_help = (
        not meta['title']
        or len(meta['title']) < 3
        or (filename_ep_title and meta['title'] == filename_ep_title)
        or (filename_ep_title and meta['title'] in filename_ep_title)
        or meta['title'] == os.path.splitext(os.path.basename(file_path))[0]
    )

    dir_title = title_from_path(file_path) if (needs_dir_help or meta.get('title')) else ''
    if dir_title:
        fn_lower = meta.get('title', '').lower()
        dir_lower = dir_title.lower()
        # Prefer directory title when:
        #   - original conditions (needs_dir_help), OR
        #   - dir title is a clean subset of filename title (filename has extra junk)
        prefer_dir = (
            needs_dir_help
            or (not meta['title'])
            or (filename_ep_title and meta.get('title', '') == filename_ep_title)
            or (dir_lower != fn_lower and dir_lower in fn_lower and len(dir_title) < len(meta['title']))
        )
        if prefer_dir:
            meta['title'] = dir_title
            meta['dot_title'] = re.sub(r'\s+', '.', dir_title.strip())

    # ── Season from directory path ────────────────────────────────────
    # If season is the default (0 or 1 from fallback), walk up directories
    # looking for "Sxx" or "Season N" patterns.
    if meta.get('is_series') and (not meta.get('season') or meta['season'] in (0, 1)):
        parent = os.path.dirname(os.path.abspath(file_path))
        while parent:
            dirname = os.path.basename(parent)
            if not dirname or dirname == os.path.sep:
                break
            m = _SERIES_PATTERN.search(dirname)
            if m:
                s = int(m.group('season'))
                if s:
                    meta['season'] = s
                    break
            m = re.search(r'season\s*(\d{1,2})', dirname, re.IGNORECASE)
            if m:
                s = int(m.group(1))
                if s:
                    meta['season'] = s
                    break
            parent = os.path.dirname(parent)

    # ── Phase 2: Episode title enrichment ──────────────────────────────

    # 2a. TVmaze — always try if we have a show title + season/episode
    #     Only fills ep_title if not already set from FILENAME
    if meta['is_series'] and meta['title'] and meta.get('episode'):
        try:
            from namer.tvmaze import enrich_episode_titles
            enrich_episode_titles(meta, language=language)
        except Exception:
            pass

    # 2ab. Wikipedia — translate foreign movie titles to target language (free, no key)
    #      TMDB below can still override if key is available.
    if not meta["is_series"] and meta.get("title"):
        try:
            from namer.wikipedia import enrich_title_via_wiki, is_valid_language, _detect_language
            if not is_valid_language(language):
                print(f'error: unknown language code {language!r}.', file=sys.stderr)
                meta["_skip"] = True
                return os.path.basename(file_path), meta
            wiki_ok = enrich_title_via_wiki(meta, language)
            if not wiki_ok and meta.get("_language_explicit"):
                source = _detect_language(meta.get("title", "") or "")
                if source and source != language:
                    print(
                        f'warning: no Wikipedia translation available '
                        f'from {source!r} to {language!r}',
                        file=sys.stderr,
                    )
                    meta["_skip"] = True
                    return os.path.basename(file_path), meta
        except Exception:
            pass

    # 2b. TMDB enrichment (episode titles + year) if key provided
    if tmdb_key:
        from namer.enricher import enrich_meta
        meta = enrich_meta(meta, tmdb_key, language)

    # 2c. Last-resort fallback (only if no ep_title at all)
    if not meta.get('ep_title') and meta['is_series'] and meta['episode']:
        meta['ep_title'] = f'Episode {meta["episode"]:02d}'

    # ── Phase 3: Technical metadata (ffprobe) ─────────────────────────
    try:
        from namer.ffprobe import enrich_from_file
        fmeta = enrich_from_file(file_path)
        if fmeta.get('codec'):
            meta['codec'] = fmeta['codec']
        if fmeta.get('resolution'):
            meta['resolution'] = f"{fmeta['resolution']}p"
        if fmeta.get('hdr'):
            meta['hdr'] = fmeta['hdr']
        if fmeta.get('audio'):
            meta['audio'] = fmeta['audio']
        if fmeta.get('audio_lang'):
            meta['audio_lang'] = fmeta['audio_lang']
        if fmeta.get('sub_lang'):
            meta['sub_lang'] = fmeta['sub_lang']
        if fmeta.get('channels'):
            meta['channels'] = fmeta['channels']
    except (ImportError, FileNotFoundError):
        pass

    # ── Choose template ─────────────────────────────────────────────
    basename = os.path.basename(file_path)

    if pattern:
        # User provided a custom template.
        # If file is a movie but template expects series fields,
        # fall back to the movie template.
        if not meta.get('is_series') and (_template_uses(pattern, 'season') or _template_uses(pattern, 'episode')):
            template = '{title} ({year}).{ext}'  # minimal movie fallback
        else:
            template = pattern
    else:
        template = TEMPLATE_SERIES if meta.get('is_series') else TEMPLATE_MOVIE

    # ── Validation: skip if metadata too incomplete ─────────────────
    if not meta.get('title') or len(meta['title']) < 2:
        return basename, meta
    if _template_uses(template, 'season') and not meta.get('season'):
        return basename, meta
    if _template_uses(template, 'episode') and not meta.get('episode'):
        return basename, meta
    if _template_uses(template, 'ep_title') and not meta.get('ep_title'):
        return basename, meta

    new_name = _format_template(template, meta)
    if not new_name:
        new_name = os.path.basename(file_path)

    return new_name, meta


def rename_file(
    file_path: str,
    new_name: str,
    dry_run: bool = False,
    reserved: set = None,
) -> bool:
    """Rename *file_path* to *new_name* in the same directory.

    Sanitizes the new name and resolves conflicts BEFORE dry-run or rename,
    so dry-run shows the exact destination that would be used.

    If *reserved* set is provided, it tracks destinations claimed within
    a batch to prevent intra-batch collisions in dry-run mode.
    Returns True on success (or simulated success in dry-run).
    """
    directory = os.path.dirname(file_path) or '.'

    # Step 1: sanitize immediately (before conflict check)
    safe_name = _sanitize_filename(new_name)
    dest = os.path.join(directory, safe_name)

    if file_path == dest:
        return True

    # Step 2: resolve conflicts (checks both filesystem and reserved set)
    dest_basename = safe_name
    if os.path.exists(dest) or (reserved is not None and dest_basename in reserved):
        base, ext = os.path.splitext(safe_name)
        counter = 1
        while True:
            candidate = f'{base}_{counter}{ext}'
            candidate_path = os.path.join(directory, candidate)
            if not os.path.exists(candidate_path) and (reserved is None or candidate not in reserved):
                dest_basename = candidate
                dest = candidate_path
                break
            counter += 1

    if reserved is not None:
        reserved.add(dest_basename)

    if dry_run:
        print(f'  mv "{os.path.basename(file_path)}" → "{dest_basename}"')
        return True

    # Safety: verify source still exists BEFORE rename
    if not os.path.exists(file_path):
        print(f'  ✗ CRITICAL: source vanished before rename: {file_path}', file=sys.stderr)
        return False

    try:
        os.rename(file_path, dest)
        print(f'  ✓ "{os.path.basename(file_path)}" → "{os.path.basename(dest)}"')
        return True
    except OSError as e:
        print(f'  ✗ Rename failed: {e}', file=sys.stderr)
        # —— Data-loss guard: verify source survived failed rename ——
        if not os.path.exists(file_path):
            print(f'  ✗ CRITICAL: source file LOST after failed rename: {file_path}', file=sys.stderr)
            print(f'  ✗ Attempted destination: {dest}', file=sys.stderr)
        return False


def process_directory(
    directory: str,
    known_title: str = '',
    pattern: str = '',
    tmdb_key: str = '',
    season_number: int = 0,
    dry_run: bool = False,
    recursive: bool = True,
    verbose: bool = False,
    language: str = 'en',
    language_explicit: bool = False,
) -> Tuple[int, int]:
    """Scan *directory* and rename all video files.

    Validates metadata first: if season or title could not be determined,
    prints a recommendation and exits early.
    Returns (renamed_count, total_count).
    """
    from namer.scanner import find_video_files

    if not os.path.isdir(directory):
        print(f'error: directory not found: {directory}', file=sys.stderr)
        return 0, 0

    files = find_video_files(directory, recursive=recursive)
    if not files:
        print('No video files found.')
        return 0, 0

    total = len(files)
    if total > 1:
        print(f'Found {total} video file{"s" if total > 1 else ""}.')

    # ── First pass: collect all results ────────────────────────────────
    results: List[Tuple[str, str, dict]] = []  # (filepath, new_name, meta)

    for fpath in files:
        rel = os.path.relpath(fpath, directory)
        if verbose and rel != os.path.basename(fpath):
            print(f'\n[{rel}]')

        new_name, meta = generate_new_name(
                fpath,
                known_title=known_title,
                pattern=pattern,
                tmdb_key=tmdb_key,
                season_number=season_number,
                language=language,
                language_explicit=language_explicit,
            )
        results.append((fpath, new_name, meta))

    # ── Second pass: perform renames, warn on skips ────────────────────
    renamed = 0
    reserved: set = set()  # track claimed destinations for intra-batch conflict
    for fpath, new_name, meta in results:
        # Check if file would be skipped (incomplete metadata)
        basename = os.path.basename(fpath)
        # Determine effective template (same logic as generate_new_name)
        if pattern:
            if not meta.get('is_series') and (_template_uses(pattern, 'season') or _template_uses(pattern, 'episode')):
                _effective = '{title} ({year}).{ext}'  # minimal movie fallback
            else:
                _effective = pattern
        else:
            _effective = TEMPLATE_SERIES if meta.get('is_series') else TEMPLATE_MOVIE

        skip_reason = ''
        if meta.get('_skip'):
            skip_reason = meta.get('_skip_reason', 'skipped by user request')
        elif not meta.get('title') or len(meta.get('title', '') or '') < 2:
            skip_reason = 'could not determine title (use -t NAME)'
        elif _template_uses(_effective, 'season') and not meta.get('season'):
            skip_reason = 'could not determine season (use -sn N)'
        elif _template_uses(_effective, 'episode') and not meta.get('episode'):
            skip_reason = 'could not determine episode'
        elif _template_uses(_effective, 'ep_title') and not meta.get('ep_title'):
            skip_reason = 'could not determine episode title'

        if skip_reason:
            print(f'  ⚠ {basename}', file=sys.stderr)
            print(f'    skipped — {skip_reason}', file=sys.stderr)
            continue

        if not new_name or new_name == basename:
            if verbose:
                print(f'  = {basename} (unchanged)')
            continue

        success = rename_file(fpath, new_name, dry_run, reserved=reserved)
        if success or dry_run:
            renamed += 1

    return renamed, total
