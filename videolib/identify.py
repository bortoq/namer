"""Identity resolution for a media file using all available information.

This is the library entry point that other tools should call instead of
reimplementing the namer pipeline.  Given a file path it produces a flat
``{field: value}`` dictionary describing the file: title, season, episode,
ep_title, year, quality as well as one mention of the source.  It may use
local-only information (filename, directories, embedded container tags) and
optionally online databases (Wikipedia, TVmaze, TMDB) to resolve names and
episode titles.  Localization to a requested language is a separate,
opt-in step (see :func:`get_video_info`).
"""

from __future__ import annotations

import os
import re
from typing import Dict, Optional

from namer.parser import parse_file, title_from_path  # noqa: F401  (re-exported for tests)


def identify_video(path: str, *, title: str = "", allow_online: bool = True) -> Dict[str, object]:
    """Identify *path* and return a video_info dict.

    Args:
        path: Absolute or relative path to a video file.
        title: Explicit show title (overrides auto-detection).  Equivalent
            to the :option:`-t` flag in the CLI.
        allow_online: When True, also consult internet databases
            (Wikipedia / TVmaze / TMDB) to confirm the identity and provide
            title / episode-title / keyword context.  When False, only local
            evidence (filename, directories, container tags) is used — fast
            and offline- safe.
    Returns:
        Dict with the same fields a rename template would consume:
        title, dot_title, season, episode, year, quality, ...
    """
    from namer.providers import local_feeds, online_feeds
    from namer.fusion import fuse

    # ── Round 0: local parse (filename).  ──────────────────────────────
    meta = parse_file(path)

    # ── Explicit title override (like `-t`).  ──────────────────────────
    if title:
        meta['title'] = title
        meta['dot_title'] = re.sub(r'\s+', '.', title.strip())
    else:
        dir_title = title_from_path(path)
        if dir_title:
            fn_title = meta.get('title', '') or ''
            if (not fn_title or len(fn_title) < 3
                    or (dir_title.lower() != fn_title.lower()
                        and dir_title.lower() in fn_title.lower()
                        and len(dir_title) < len(fn_title))):
                meta['title'] = dir_title
                meta['dot_title'] = re.sub(r'\s+', '.', dir_title.strip())

    # ── Round 1: local providers vote on season / episode.  ────────────
    scores: Dict = {}
    local = local_feeds(path, title)
    v1 = fuse(local, scores)
    refused = [f for f in ('season', 'episode') if f in v1 and not v1[f].usable]
    for f in ('season', 'episode'):
        if f in v1 and v1[f].usable:
            meta[f] = v1[f].value
    meta['season_assumed'] = 'season' in refused
    meta['_refused_fields'] = refused

    # ── Round 2: online providers → title / year / ep_title.  ──────────
    if allow_online and meta.get('title'):
        language = 'en'  # identify is language-neutral; localization is `get_video_info`
        online = online_feeds(meta, '', language) if meta.get('title') else []
        all_feeds = local + online
        v = fuse(all_feeds, scores)
        for f, verdict in v.items():
            if verdict.usable and f not in ('season', 'episode'):
                meta[f] = verdict.value
    # When offline, the ep_title from parse_file (clean filename) is kept.

    if meta.get('title'):
        meta['dot_title'] = re.sub(r'\s+', '.', str(meta['title']).strip())

    # Simplify the dict: drop internal bookkeeping keys that belong to the
    # namer pipeline, not to a generic consumer.
    meta.pop('_skip', None)
    meta.pop('_skip_reason', None)
    return meta


def get_video_info(path: str, *, language: str = "en") -> Dict[str, object]:
    """Identify *path* and localize its title / episode title to *language*.

    Works exactly like :func:`identify_video` but additionally (a) translates
    the show/movie title and (b) fills the episode title (where available) in
    the requested language — using both Wikipedia and online metadata
    providers as reliable and up to date as possible.

    Args:
        path: Absolute or relative path to a video file.
        language: Two-letter Wikipedia language code (e.g. 'en', 'ru', de).
    Returns:
        Same dict as :func:`identify_video`, with localized ``title``,
        ``ep_title`` and its best ``year``.
    """
    meta = identify_video(path, allow_online=True)

    if not meta.get('title'):
        return meta

    # Localize the show title (Wikipedia source-language → target).
    try:
        from namer.wikipedia import enrich_title_via_wiki
        enrich_title_via_wiki(meta, language)
    except Exception:
        pass

    # Localize / fill the episode title via online providers in target lang.
    if meta.get('is_series') and meta.get('season') is not None and \
            meta.get('episode') and not meta.get('season_assumed'):
        try:
            from namer.tvmaze import enrich_episode_titles
            from namer.enricher import enrich_meta
            from namer.providers import local_feeds, online_feeds
            from namer.fusion import fuse

            local = local_feeds(path)
            online = online_feeds(dict(meta), '', language)
            v = fuse(local + online, {})
            for f, verdict in v.items():
                if verdict.usable and f == 'ep_title':
                    meta['ep_title'] = verdict.value
        except Exception:
            pass

    if meta.get('title'):
        meta['dot_title'] = re.sub(r'\s+', '.', str(meta['title']).strip())
    return meta
