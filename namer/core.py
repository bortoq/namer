"""Rename engine — generates new names and performs (or previews) rename."""

import os
import re
import sys
from typing import List, Tuple

from namer import settings
from namer.parser import parse_file
from namer.settings import TEMPLATE_MOVIE, TEMPLATE_SERIES


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
    # Collapse double dots from empty fields (e.g. "Title..S01" when ep_title is empty)
    new_name = re.sub(r'\.{2,}', '.', new_name)
    new_name = re.sub(r'\s+', ' ', new_name).strip()
    new_name = re.sub(r'[. ]$', '', new_name)
    return new_name


def generate_new_name(
    file_path: str,
    known_title: str = '',
    pattern: str = '',
    tmdb_key: str = '',
    season_number: int = 0,
) -> Tuple[str, dict]:
    """Generate a new filename for *file_path*.

    Args:
        file_path: Absolute or relative path to a video file.
        known_title: If provided, overrides the auto-detected title.
        pattern: Custom template.  If empty, uses default
                 (*TEMPLATE_SERIES* or *TEMPLATE_MOVIE*).
        tmdb_key: TMDB API key for episode title / year enrichment.
        season_number: Explicit season number (overrides auto-detection).

    Returns:
        ``(new_basename, metadata_dict)``
    """
    meta = parse_file(file_path)

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
        if ff_tags.get('show_name'):
            meta['title'] = ff_tags['show_name']
            meta['dot_title'] = re.sub(r'\s+', '.', ff_tags['show_name'].strip())
        if ff_tags.get('ep_title') and not filename_ep_title:
            # Only use ffprobe ep_title if filename didn't have one
            meta['ep_title'] = ff_tags['ep_title']
    except (ImportError, FileNotFoundError):
        pass

    # 1b. Directory path heuristic — use directory tree for show name
    #     Check if filename-extracted title looks like an episode name
    #     (short, or equal to ep_title from filename)
    from namer.parser import title_from_path
    title_from_filename = known_title or meta.get('_original_title', meta.get('title', ''))
    needs_dir_help = (
        not meta['title']
        or len(meta['title']) < 3
        or (filename_ep_title and meta['title'] == filename_ep_title)
        or (filename_ep_title and meta['title'] in filename_ep_title)
        or meta['title'] == os.path.splitext(os.path.basename(file_path))[0]
    )
    if needs_dir_help:
        dir_title = title_from_path(file_path)
        if dir_title:
            # Override title from path when:
            # - no title exists, OR
            # - path title is longer (more specific), OR
            # - filename title equals ep_title (formatted file — title is just episode name)
            if (not meta['title']
                or len(dir_title) > len(meta['title'])
                or (filename_ep_title and meta.get('title', '') == filename_ep_title)):
                meta['title'] = dir_title
                meta['dot_title'] = re.sub(r'\s+', '.', dir_title.strip())

    # ── Phase 2: Episode title enrichment ──────────────────────────────

    # 2a. TVmaze — always try if we have a show title + season/episode
    #     Only fills ep_title if not already set from FILENAME
    if meta['is_series'] and meta['title'] and meta.get('episode'):
        try:
            from namer.tvmaze import enrich_episode_titles
            enrich_episode_titles(meta)
        except Exception:
            pass

    # 2b. TMDB enrichment (episode titles + year) if key provided
    if tmdb_key:
        from namer.enricher import enrich_meta
        meta = enrich_meta(meta, tmdb_key)

    # 2c. Last-resort fallback (only if no ep_title at all)
    if not meta.get('ep_title') and meta['is_series'] and meta['episode']:
        meta['ep_title'] = 'Episode ' + str(meta['episode'])

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
        if not meta.get('is_series') and ('{season}' in pattern or '{episode}' in pattern):
            template = '{title} ({year}).{ext}'  # minimal movie fallback
        else:
            template = pattern
    else:
        template = TEMPLATE_SERIES if meta.get('is_series') else TEMPLATE_MOVIE

    # ── Validation: skip if metadata too incomplete ─────────────────
    if not meta.get('title') or len(meta['title']) < 2:
        return basename, meta
    if '{season}' in template and not meta.get('season'):
        return basename, meta
    if '{episode}' in template and not meta.get('episode'):
        return basename, meta
    if '{ep_title}' in template and not meta.get('ep_title'):
        return basename, meta

    new_name = _format_template(template, meta)
    if not new_name:
        new_name = os.path.basename(file_path)

    return new_name, meta


def rename_file(
    file_path: str,
    new_name: str,
    dry_run: bool = False,
) -> bool:
    """Rename *file_path* to *new_name* in the same directory.

    Returns True on success (or simulated success in dry-run).
    """
    directory = os.path.dirname(file_path) or '.'
    dest = os.path.join(directory, new_name)

    if file_path == dest:
        return True

    if dry_run:
        print(f'  mv "{os.path.basename(file_path)}" → "{new_name}"')
        return True

    # Conflict check
    if os.path.exists(dest):
        base, ext = os.path.splitext(new_name)
        counter = 1
        while os.path.exists(os.path.join(directory, f'{base}_{counter}{ext}')):
            counter += 1
        dest = os.path.join(directory, f'{base}_{counter}{ext}')

    try:
        os.rename(file_path, dest)
        print(f'  ✓ "{os.path.basename(file_path)}" → "{os.path.basename(dest)}"')
        return True
    except OSError as e:
        print(f'  ✗ Rename failed: {e}', file=sys.stderr)
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

        new_name, meta = generate_new_name(fpath, known_title, pattern, tmdb_key, season_number)
        results.append((fpath, new_name, meta))

    # ── Second pass: perform renames, warn on skips ────────────────────
    renamed = 0
    for fpath, new_name, meta in results:
        # Check if file would be skipped (incomplete metadata)
        basename = os.path.basename(fpath)
        # Determine effective template (same logic as generate_new_name)
        if pattern:
            if not meta.get('is_series') and ('{season}' in pattern or '{episode}' in pattern):
                _effective = '{title} ({year}).{ext}'  # minimal movie fallback
            else:
                _effective = pattern
        else:
            _effective = TEMPLATE_SERIES if meta.get('is_series') else TEMPLATE_MOVIE

        skip_reason = ''
        if not meta.get('title') or len(meta.get('title', '') or '') < 2:
            skip_reason = 'could not determine title (use -t NAME)'
        elif '{season}' in _effective and not meta.get('season'):
            skip_reason = 'could not determine season (use -sn N)'
        elif '{episode}' in _effective and not meta.get('episode'):
            skip_reason = 'could not determine episode'
        elif '{ep_title}' in _effective and not meta.get('ep_title'):
            skip_reason = 'could not determine episode title'

        if skip_reason:
            print(f'  ⚠ {basename}', file=sys.stderr)
            print(f'    skipped — {skip_reason}', file=sys.stderr)
            continue

        if not new_name or new_name == basename:
            if verbose:
                print(f'  = {basename} (unchanged)')
            continue

        success = rename_file(fpath, new_name, dry_run)
        if success or dry_run:
            renamed += 1

    return renamed, total
