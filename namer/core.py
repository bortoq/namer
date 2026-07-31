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

    Pipeline: every provider (filename, dirname, file, wikipedia, tvmaze,
    tmdb) casts a feed; providers are clustered by agreement per field, the
    strongest cluster wins, and the template is filled from the winning
    values.  When the expensive fields (season/episode) are genuinely
    disputed, the file is refused instead of being renamed with a guess.

    Returns:
        ``(new_basename, metadata_dict)``
    """
    from namer.voting import vote, update_scores, Scores

    meta = parse_file(file_path)
    meta['_skip'] = False
    meta['_language_explicit'] = language_explicit
    meta['_title_enriched'] = False

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
        meta['_title_enriched'] = True

    # ep_title is NOT scraped from filename — comes only from enrichment (voting)

    # ── Directory title cleanup (before translation) ──────────────────
    # A clean directory title ("Attack on Titan") wins over a filename
    # with extra words ("Attack on Titan Final Season 01") so the
    # wikipedia translation starts from the clean name.
    if not known_title:
        from namer.parser import title_from_path
        dir_title = title_from_path(file_path)
        if dir_title:
            fn_title = meta.get('title', '') or ''
            fn_lower, dir_lower = fn_title.lower(), dir_title.lower()
            if (not fn_title or len(fn_title) < 3
                    or (dir_lower != fn_lower and dir_lower in fn_lower
                        and len(dir_title) < len(fn_title))):
                meta['title'] = dir_title
                meta['dot_title'] = re.sub(r'\s+', '.', dir_title.strip())

    # ── Language validation + Wikipedia title translation ──────────────
    # Runs before the feeds so the corrected title helps online lookups.
    if meta.get("title"):
        try:
            from namer.wikipedia import enrich_title_via_wiki, is_valid_language, _detect_language
            if not is_valid_language(language):
                print(f'error: unknown language code {language!r}.', file=sys.stderr)
                meta["_skip"] = True
                return os.path.basename(file_path), meta
            wiki_ok = enrich_title_via_wiki(meta, language)
            if wiki_ok:
                meta['_title_enriched'] = True
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

    # ── Round 1: local providers vote on season/episode ────────────────
    from namer.providers import local_feeds, online_feeds
    scores: Scores = {}  # per-run success ratings (tie-break for votes)
    local = local_feeds(file_path, known_title)
    v1 = vote(local, scores)

    refused = [f for f in ('season', 'episode') if f in v1 and not v1[f].usable]
    for f in ('season', 'episode'):
        if f in v1 and v1[f].usable:
            meta[f] = v1[f].value
    # An unresolved/refused season must not feed episode-title lookups;
    # an accepted one is no longer an assumption.
    meta['season_assumed'] = 'season' in refused
    meta['_refused_fields'] = refused

    # Explicit season override resolves any dispute.
    if season_number > 0:
        meta['season'] = season_number
        meta['season_assumed'] = False
        if 'season' in refused:
            refused.remove('season')
        meta['_refused_fields'] = refused

    # ── Round 2: online providers vote on title/year/ep_title ──────────
    online = online_feeds(meta, tmdb_key, language) if meta.get('title') else []
    all_feeds = local + online
    v = vote(all_feeds, scores)
    update_scores(scores, all_feeds, v)

    # Apply usable verdicts (accept + guess) to the metadata dict.
    for f, verdict in v.items():
        if verdict.usable and f not in ('season', 'episode'):
            meta[f] = verdict.value
    if meta.get('title'):
        meta['dot_title'] = re.sub(r'\s+', '.', str(meta['title']).strip())
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

    # ── Validation: skip if metadata too incomplete or disputed ─────
    if not meta.get('title') or len(meta['title']) < 2:
        return basename, meta
    if _template_uses(template, 'season') and meta.get('season') is None:
        return basename, meta
    if _template_uses(template, 'episode') and meta.get('episode') is None:
        return basename, meta
    # Disputed expensive fields → refuse rather than guess.
    if 'season' in meta.get('_refused_fields', []) and _template_uses(template, 'season'):
        return basename, meta
    if 'episode' in meta.get('_refused_fields', []) and _template_uses(template, 'episode'):
        return basename, meta
    # ep_title is required when template uses it — skip if missing
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

    # ── Second pass: perform renames, warn on skips ───────────────────────────
    renamed = 0
    reserved: set = set()  # track claimed destinations for intra-batch conflict
    try:
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
            elif _template_uses(_effective, 'season') and meta.get('season') is None:
                skip_reason = 'could not determine season (use -sn N)'
            elif _template_uses(_effective, 'episode') and meta.get('episode') is None:
                skip_reason = 'could not determine episode'
            # Allow missing ep_title — _format_template handles the gap

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
    except KeyboardInterrupt:
        print('\nInterrupted during rename pass.', file=sys.stderr)
        print(f'Renamed {renamed}/{total} files before interrupt.')

    return renamed, total
