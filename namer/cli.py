#!/usr/bin/env python3
"""CLI entry point for namer."""

import argparse
import os
import sys

from namer import __version__
from namer.core import process_directory


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='namer',
        description='Rename video/series files using metadata from filenames.',
        epilog=(
            'Examples:\n'
            '  namer                                    # rename all videos in current dir\n'
            '  namer "Breaking Bad"                     # use "Breaking Bad" as show name\n'
            '  namer -t "Show Name"                     # same via -t flag\n'
            '  namer -sn 2 -t "Show Name"               # force season 2\n'
            '  namer -p "{title}.{ext}"                 # simple: just clean name + ext\n'
            '  namer -p "{dot_title}.S{season:02d}E{episode:02d}.{quality}.{ext}"\n'
            '  namer -n                                 # dry-run (preview only)\n'
            '  namer --tmdb-key YOUR_KEY                # enrich with episode titles from TMDB\n'
            '  namer -d /path/to/videos                 # process specific directory\n'
            '  namer -l ru                               # russian episode titles\n'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        'title', nargs='?', default='',
        help='Show/movie name (overrides auto-detection from filename)',
    )
    p.add_argument(
        '-t', '--title', default='', dest='title_opt', metavar='TITLE',
        help='Show/movie name (overrides auto-detection, same as positional title)',
    )
    p.add_argument(
        '-sn', '--season-number', type=int, default=0,
        help='Explicit season number (overrides auto-detection)',
    )
    p.add_argument(
        '-p', '--pattern', default='',
        help=(
            'Custom rename pattern. '
            'Fields: {title} {dot_title} {season} {episode} {ext} {year} {audio_lang} {sub_lang} {channels} '
            '{quality} {resolution} {source} {codec} {audio} {hdr} {mod}. '
            'Default movie:  "{title} ({year}) {mod}.{ext}"  '
            'Default series: "{season:02d}.{episode:02d}. {ep_title}.{ext}"'
        ),
    )
    p.add_argument(
        '-n', '--dry-run', action='store_true',
        help='Preview changes without renaming',
    )
    p.add_argument(
        '--tmdb-key', default='',
        help='TMDB API key for episode title / year enrichment',
    )
    p.add_argument(
        '-V', '--version', action='version',
        version=f'namer {__version__}',
    )
    p.add_argument(
        '-v', '--verbose', action='store_true',
        help='Verbose output (show subdirectory paths)',
    )
    p.add_argument(
        '-d', '--directory', default='',
        help='Target directory (default: current directory)',
    )
    p.add_argument(
        '-l', '--language', default='en',
        help=(
            'Language for episode/show names (TVmaze + TMDB). '
            'Examples: en, ru, de, fr, es, ja. '
            'Default: en'
        ),
    )
    return p


def main(argv: list = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Allow explicit -d/--directory to bypass os.getcwd() issues
    if args.directory:
        directory = args.directory
    else:
        try:
            directory = os.getcwd()
        except FileNotFoundError:
            # On FUSE filesystems (NTFS-3G, etc.), os.getcwd() can fail with
            # ENOENT due to transient I/O errors even when the directory exists.
            pwd = os.environ.get('PWD')
            if pwd and os.path.isdir(pwd):
                directory = pwd
            else:
                print('error: cannot determine current directory',
                      file=sys.stderr)
                print('  use -d DIR to specify the target directory explicitly.',
                      file=sys.stderr)
                return 1

    # Validate language code against known Wikipedia languages
    from namer.wikipedia import is_valid_language
    if not is_valid_language(args.language):
        print(
            f'error: unknown language code {args.language!r}. '
            f'Use a valid Wikipedia language code (e.g. en, ru, de, fr, es, ja).',
            file=sys.stderr,
        )
        return 1
    _lang_explicit = args.language != 'en'

    # Merge -t/--title with positional title (positional takes precedence)
    # Clean input to strip extension, year, quality tokens (user may pass a filename)
    from namer.parser import clean_title
    raw = args.title.strip() if args.title else (args.title_opt.strip() if args.title_opt else '')
    known = clean_title(raw) if raw else ''

    if not os.path.isdir(directory):
        print(f'error: directory not found: {directory}', file=sys.stderr)
        return 1

    try:
        renamed, total = process_directory(
            directory=directory,
            known_title=known,
            pattern=args.pattern,
            tmdb_key=args.tmdb_key,
            season_number=args.season_number,
            dry_run=args.dry_run,
            recursive=True,
            verbose=args.verbose,
            language=args.language,
            language_explicit=_lang_explicit,
        )
    except KeyboardInterrupt:
        print('\nInterrupted.', file=sys.stderr)
        return 130

    if args.dry_run:
        print(f'\nDry-run: {renamed}/{total} files would be renamed.')
    else:
        if renamed:
            print(f'\nRenamed {renamed}/{total} files.')

    return 0


if __name__ == '__main__':
    sys.exit(main())
