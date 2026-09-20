"""Batch book renaming. Sequential, atomic no-clobber. Never crashes a batch."""
from __future__ import annotations

import os
from typing import Callable, List, Optional

from namer.books.detect import find_book_files
from namer.books.identify import build_query
from namer.books.naming import generate_book_name

# A searcher maps a BookQuery to provider opinions (see providers.py).
# Injectable for tests; network is opt-in (searchers=None -> offline only).
Searcher = Callable[[object], list]


def process_books_directory(directory: str, pattern: str = '',
                            known_title: str = '',
                            known_author: str = '',
                            dry_run: bool = False, recursive: bool = True,
                            verbose: bool = False,
                            searchers: Optional[List[Searcher]] = None,
                            allow_local: bool = True) -> tuple:
    """Rename book files under *directory*. Returns (renamed, total, errors).

    Network enrichment (AUDIT roadmap gap): pass searchers=[search_openlibrary,
    search_googlebooks] to let fused network records override local hints
    (canonical-from-network). Default None keeps the offline provisional
    behaviour; without any usable record the file is left in place.
    """
    try:
        if not isinstance(directory, str) or not directory:
            return 0, 0, 0
        if not os.path.isdir(directory):
            try:
                print(f'error: directory not found: {directory}')
            except Exception:
                pass
            return 0, 0, 0
        files = find_book_files(directory, recursive=recursive)
        if not files:
            return 0, 0, 0
        total = len(files)
        renamed = 0
        errors = 0
        reserved: set = set()
        try:
            from namer.core import rename_file
        except Exception:
            rename_file = None  # type: ignore
        for fpath in files:
            try:
                basename = os.path.basename(fpath)
                opinions: Optional[list] = None
                if searchers:
                    try:
                        query = build_query(fpath, known_title, known_author)
                    except Exception:
                        query = None
                    if query is not None and not query.is_empty():
                        collected: list = []
                        for search in searchers:
                            try:
                                found = search(query)
                            except Exception:
                                continue
                            if found:
                                collected.extend(found)
                        opinions = collected or None
                new_name, ident = generate_book_name(
                    fpath, pattern=pattern,
                    known_title=known_title, known_author=known_author,
                    opinions=opinions, allow_local=allow_local)
                if verbose:
                    try:
                        print(f'[{os.path.relpath(fpath, directory)}] -> {new_name}')
                    except Exception:
                        pass
                if not ident.usable or not new_name or new_name == basename:
                    continue
                if rename_file is None:
                    # fallback: dry preview only
                    if dry_run:
                        renamed += 1
                    else:
                        errors += 1
                    continue
                ok = rename_file(fpath, new_name, dry_run,
                                 reserved=reserved, quiet=True)
                if ok or dry_run:
                    renamed += 1
                else:
                    errors += 1
            except Exception:
                errors += 1
                continue
        return renamed, total, errors
    except Exception:
        return 0, 0, 0
