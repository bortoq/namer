"""Supplementary material detection — identify and skip bonus content.

Looks at both filename patterns (trailers, interviews, making-of, etc.)
and directory names (Extras, Samples, Bonus, Features, etc.).
"""

import os
import re
from typing import List, Pattern

# ═══════════════════════════════════════════════════════════════════════════════
# DIRECTORY PATTERNS — if any path component matches, the file is supplementary
# ═══════════════════════════════════════════════════════════════════════════════

_SUPPLEMENTARY_DIRS: List[Pattern] = [
    # Bonus content folders
    re.compile(r'^extras$', re.IGNORECASE),
    re.compile(r'^bonus$', re.IGNORECASE),
    re.compile(r'^bonus[- .]?features?$', re.IGNORECASE),
    re.compile(r'^featurettes?$', re.IGNORECASE),
    re.compile(r'^supplemental$', re.IGNORECASE),
    re.compile(r'^extra[- .]?features?$', re.IGNORECASE),
    re.compile(r'^extra[- .]?episodes?$', re.IGNORECASE),
    re.compile(r'^extra$', re.IGNORECASE),
    # Trailers / Promos
    re.compile(r'^trailers?$', re.IGNORECASE),
    re.compile(r'^teasers?$', re.IGNORECASE),
    re.compile(r'^promos?$', re.IGNORECASE),
    # Deleted / Extended / Alternate scenes
    re.compile(r'^deleted[- .]?scenes?$', re.IGNORECASE),
    re.compile(r'^extended[- .]?scenes?$', re.IGNORECASE),
    re.compile(r'^alternate[- .]?scenes?$', re.IGNORECASE),
    # Behind the scenes / Making of
    re.compile(r'^behind[- .]?the[- .]?scenes$', re.IGNORECASE),
    re.compile(r'^making[- .]?of$', re.IGNORECASE),
    re.compile(r'^bts$', re.IGNORECASE),
    re.compile(r'^on[- .]?the[- .]?set$', re.IGNORECASE),
    # Interviews
    re.compile(r'^interviews?$', re.IGNORECASE),
    # Gag / Outtakes / Bloopers
    re.compile(r'^gag[- .]?reels?$', re.IGNORECASE),
    re.compile(r'^outtakes?$', re.IGNORECASE),
    re.compile(r'^bloopers?$', re.IGNORECASE),
    # Screen tests / Storyboards
    re.compile(r'^screen[- .]?tests?$', re.IGNORECASE),
    re.compile(r'^camera[- .]?tests?$', re.IGNORECASE),
    re.compile(r'^storyboards?$', re.IGNORECASE),
    re.compile(r'^animatics?$', re.IGNORECASE),
    # Documentaries
    re.compile(r'^documentar(?:y|ies)$', re.IGNORECASE),
    # Samples
    re.compile(r'^samples?$', re.IGNORECASE),
    # General
    re.compile(r'^specials?$', re.IGNORECASE),
    re.compile(r'^bdmv$', re.IGNORECASE),
    re.compile(r'^certificate$', re.IGNORECASE),
    # Plex-style extras folder marker
    re.compile(r'^\.extras$', re.IGNORECASE),
]


# ═══════════════════════════════════════════════════════════════════════════════
# FILENAME PATTERNS — matched against the stem (name without extension)
# ═══════════════════════════════════════════════════════════════════════════════

_SUPPLEMENTARY_FILENAMES: List[Pattern] = [
    # ── EXACT MATCH (stem IS the supplementary word) ────────────────────────
    # These words are too common in movie/show titles to use as prefix.
    re.compile(r'^trailer$', re.IGNORECASE),
    re.compile(r'^teaser$', re.IGNORECASE),
    re.compile(r'^promo$', re.IGNORECASE),
    re.compile(r'^sample$', re.IGNORECASE),
    re.compile(r'^featurette$', re.IGNORECASE),
    re.compile(r'^outtakes?$', re.IGNORECASE),
    re.compile(r'^bloopers?$', re.IGNORECASE),
    re.compile(r'^blooper$', re.IGNORECASE),
    re.compile(r'^screen[- .]?tests?$', re.IGNORECASE),
    re.compile(r'^camera[- .]?tests?$', re.IGNORECASE),
    re.compile(r'^storyboards?$', re.IGNORECASE),
    re.compile(r'^storyboard[- .]?comparisons?$', re.IGNORECASE),
    re.compile(r'^animatics?$', re.IGNORECASE),
    re.compile(r'^documentar(?:y|ies)$', re.IGNORECASE),
    # ── PREFIX MATCH (stem starts with term + separator) ────────────────────
    # Safe because these terms are not common movie/show title prefixes.
    re.compile(r'^interview[- .]', re.IGNORECASE),
    re.compile(r'^interviews[- .]', re.IGNORECASE),
    re.compile(r'^cast[- .]?interview', re.IGNORECASE),
    re.compile(r'^behind[- .]?the[- .]?scenes', re.IGNORECASE),
    re.compile(r'^making[- .]?of', re.IGNORECASE),
    re.compile(r'^on[- .]?the[- .]?set', re.IGNORECASE),
    re.compile(r'^bts[- .]', re.IGNORECASE),
    re.compile(r'^deleted[- .]?scenes?', re.IGNORECASE),
    re.compile(r'^extended[- .]?scenes?', re.IGNORECASE),
    re.compile(r'^alternate[- .]?scenes?', re.IGNORECASE),
    re.compile(r'^alternate[- .]?ending', re.IGNORECASE),
    re.compile(r'^gag[- .]?reel', re.IGNORECASE),
    re.compile(r'^short[- .]?film', re.IGNORECASE),
    re.compile(r'^mini[- .]?feature', re.IGNORECASE),
    re.compile(r'^behind[- .]?the[- .]?scenes', re.IGNORECASE),
    re.compile(r'^q[- .]?&?[- .]?a', re.IGNORECASE),
    # ── SUFFIX MATCH (stem ends with separator + term) ──────────────────────
    re.compile(r'making[- .]?of$', re.IGNORECASE),
    re.compile(r'the[- .]?making[- .]?of$', re.IGNORECASE),
    re.compile(r'behind[- .]?the[- .]?scenes$', re.IGNORECASE),
]


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════

def is_supplementary(filepath: str) -> bool:
    """Check if a file is supplementary/bonus content that should not be renamed.

    Checks:
      1. Any component of the parent path matches a known supplementary directory.
      2. The filename stem matches a known supplementary pattern.

    Args:
        filepath: Absolute or relative path to a video file.

    Returns:
        True if the file is supplementary content.
    """
    if not filepath:
        return False

    normalized = os.path.normpath(filepath)
    parts = normalized.replace('\\', '/').split('/')

    # 1. Check directory components
    for part in parts[:-1]:  # exclude the filename itself
        for pattern in _SUPPLEMENTARY_DIRS:
            if pattern.search(part):
                return True

    # 2. Check filename stem
    stem = os.path.splitext(os.path.basename(filepath))[0]
    # Normalise: replace underscores/dots with spaces for uniform matching
    stem_norm = re.sub(r'[._]', ' ', stem).strip()
    for pattern in _SUPPLEMENTARY_FILENAMES:
        # Try both original (with dots) and normalised (spaces)
        if pattern.search(stem) or pattern.search(stem_norm):
            return True

    return False


def describe_supplementary(filepath: str) -> str:
    """Return a human-readable reason why *filepath* is considered supplementary.

    Returns empty string if not supplementary.
    """
    if not filepath:
        return ''

    normalized = os.path.normpath(filepath)
    parts = normalized.replace('\\', '/').split('/')
    stem = os.path.splitext(os.path.basename(filepath))[0]
    stem_norm = re.sub(r'[._]', ' ', stem).strip()

    # Check directories first
    for part in parts[:-1]:
        for pattern in _SUPPLEMENTARY_DIRS:
            if pattern.search(part):
                return f'supplementary directory: {part!r}'

    # Check filename
    for pattern in _SUPPLEMENTARY_FILENAMES:
        if pattern.search(stem) or pattern.search(stem_norm):
            return f'supplementary filename: {stem!r}'

    return ''
