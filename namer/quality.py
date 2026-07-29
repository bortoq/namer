#!/usr/bin/env python3
"""Quality parser for torrent titles."""

import re
from dataclasses import dataclass
from typing import List

# ═══════════════════════════════════════════════════════════════════════════════
# QUALITY PARSER (from Radarr QualityParser.cs)
# ═══════════════════════════════════════════════════════════════════════════════

RESOLUTION_PATTERNS = [
    (2160, re.compile(r'\b(?:2160p|3840x2160|4096x2160|4k[-_. ](?:UHD|HEVC|BD|H\.?265)|(?:UHD|HEVC|BD|H\.?265)[-_. ]4k)\b', re.IGNORECASE)),
    (2160, re.compile(r'\bUHD\b', re.IGNORECASE)),
    (1080, re.compile(r'\b(?:1080p|1920x1080|1440p|FHD|1080i)\b', re.IGNORECASE)),
    (720, re.compile(r'\b(?:720p|1280x720|960p)\b', re.IGNORECASE)),
    (576, re.compile(r'\b576p\b', re.IGNORECASE)),
    (480, re.compile(r'\b(?:480p|480i|640x480|848x480)\b', re.IGNORECASE)),
    (360, re.compile(r'\b360p\b', re.IGNORECASE)),
    (540, re.compile(r'\b540p\b', re.IGNORECASE)),
]

SOURCE_PATTERNS = [
    ("BluRay", re.compile(r'\b(?:M?Blu[-_. ]?Ray|HD[-_. ]?DVD|BD(?!$)|UHD2?BD|BDISO|BDMux|BD25|BD50|BR[-_. ]?DISK)\b', re.IGNORECASE)),
    ("WEB-DL", re.compile(r'\b(?:WEB[-_. ]?DL(?:mux)?|AmazonHD|AmazonSD|iTunesHD|MaxdomeHD|NetflixU?HD|WebHD|HBOMaxHD|DisneyHD)\b', re.IGNORECASE)),
    ("WEB-DL", re.compile(r'[. ]WEB[. ](?:[xh][ .]?26[45]|AVC|HEVC|DDP?5[. ]1)', re.IGNORECASE)),
    ("WEB-DL", re.compile(r'\bAMZN[. -]WEB[. -](?!Rip)\b', re.IGNORECASE)),
    ("WEBRip", re.compile(r'\b(?:WebRip|Web-Rip|WEBMux)\b', re.IGNORECASE)),
    ("HDTV", re.compile(r'\bHDTV\b', re.IGNORECASE)),
    ("BDRip", re.compile(r'\b(?:BDRip|BDLight|HD[-_. ]?DVDRip|UHDBDRip)\b', re.IGNORECASE)),
    ("BRRip", re.compile(r'\bBRRip\b', re.IGNORECASE)),
    ("DVD", re.compile(r'\bDVD(?!-R)\b', re.IGNORECASE)),
    ("DVDR", re.compile(r'\b\d?x?M?DVD-?[R59]\b', re.IGNORECASE)),
    ("SCREENER", re.compile(r'\b(?:SCR|SCREENER|DVDSCR|DVDSCREENER)\b', re.IGNORECASE)),
    ("TELESYNC", re.compile(r'\b(?:TS[-_. ]|TELESYNCH?|HD-TS|HDTS|PDVD|TSRip|HDTSRip)\b', re.IGNORECASE)),
    ("TELECINE", re.compile(r'\b(?:TC|TELECINE|HD-TC|HDTC)\b', re.IGNORECASE)),
    ("CAM", re.compile(r'\b(?:CAMRIP|(?:NEW)?CAM|HD-?CAM(?:Rip)?|HQCAM)\b', re.IGNORECASE)),
    ("WORKPRINT", re.compile(r'\b(?:WORKPRINT|WP)\b', re.IGNORECASE)),
    ("PDTV", re.compile(r'\bPDTV\b', re.IGNORECASE)),
    ("SDTV", re.compile(r'\bSDTV\b', re.IGNORECASE)),
    ("TVRip", re.compile(r'\bTVRip\b', re.IGNORECASE)),
]

CODEC_PATTERNS = [
    ("AV1", re.compile(r'\bAV1\b', re.IGNORECASE)),
    ("HEVC", re.compile(r'\b(?:HEVC|h\.?265|x265)\b', re.IGNORECASE)),
    ("x264", re.compile(r'\b(?:x264|h\.?264|AVC)\b', re.IGNORECASE)),
    ("VP9", re.compile(r'\bVP9\b', re.IGNORECASE)),
    ("XviD", re.compile(r'\bX-?vid\b', re.IGNORECASE)),
    ("DivX", re.compile(r'\bdivx\b', re.IGNORECASE)),
    ("VC-1", re.compile(r'\bVC[-_. ]?1\b', re.IGNORECASE)),
    ("MPEG-2", re.compile(r'\bMPEG[-_. ]?2\b', re.IGNORECASE)),
]

AUDIO_PATTERNS = [
    ("TrueHD", re.compile(r'\bTrueHD\b', re.IGNORECASE)),
    ("DTS-HD", re.compile(r'\bDTS[-_. ]?HD(?:MA)?\b', re.IGNORECASE)),
    ("DTS", re.compile(r'\bDTS(?![-_.]HD\b)\b', re.IGNORECASE)),
    ("FLAC", re.compile(r'\bFLAC\b', re.IGNORECASE)),
    ("AAC", re.compile(r'\bAAC\b', re.IGNORECASE)),
    ("AC3", re.compile(r'\b(?:AC3|DDP?5[. ]1)\b', re.IGNORECASE)),
    ("MP3", re.compile(r'\bMP3\b', re.IGNORECASE)),
    ("PCM", re.compile(r'\bPCM\b', re.IGNORECASE)),
    ("Opus", re.compile(r'\bOpus\b', re.IGNORECASE)),
]

HDR_PATTERNS = [
    ("Dolby Vision", re.compile(r'\b(?:Dolby[ .-]?Vision|DOVI|DV)\b', re.IGNORECASE)),
    ("HDR10+", re.compile(r'\bHDR10\+?\b', re.IGNORECASE)),
    ("HDR10", re.compile(r'\bHDR10\b(?!\+)', re.IGNORECASE)),
    ("HLG", re.compile(r'\bHLG\b', re.IGNORECASE)),
    ("HDR", re.compile(r'\bHDR\b(?!10)', re.IGNORECASE)),
]

REMUX_PATTERN = re.compile(r'(?:[_. \[]|\d{4}p-|\bHybrid-)(?:(BD|UHD)[-_. ]?)?Remux\b|(?:(BD|UHD)[-_. ]?)?Remux[_. ]\d{4}p', re.IGNORECASE)
THREE_D_PATTERN = re.compile(r'\b3D\b', re.IGNORECASE)

# ── Modifiers (edition / cut indicators) ──────────────────────────────────
# Order matters: longer patterns first to avoid partial matches.
MODIFIERS = [
    # Multi-word modifiers (longest first)
    ("Special Edition", re.compile(r'\bSpecial[. ]Edition\b', re.IGNORECASE)),
    ("Collector's Edition", re.compile(r"\bCollector['´`]?s[. ]Edition\b", re.IGNORECASE)),
    ("Alternative Cut", re.compile(r'\b(?:Alternative|Alternate)[. ]Cut\b', re.IGNORECASE)),
    ("Director's Cut", re.compile(r"\b(?:Director['´`]?s|Directors)[. ]?Cut\b", re.IGNORECASE)),
    ("Theatrical Cut", re.compile(r'\bTheatrical[. ]Cut\b', re.IGNORECASE)),
    ("Extended Cut", re.compile(r'\bExtended[. ]Cut\b', re.IGNORECASE)),
    ("Fan Edit", re.compile(r'\bFan[. ]Edit\b', re.IGNORECASE)),
    ("Open Matte", re.compile(r'\bOpen[. ]?Matte\b', re.IGNORECASE)),
    ("IMAX Enhanced", re.compile(r'\bIMAX[. ]Enhanced\b', re.IGNORECASE)),
    ("Criterion Edition", re.compile(r'\bCriterion[. ]Edition\b', re.IGNORECASE)),
    # Single-word (and short) modifiers
    ("Extended", re.compile(r'\bExtended\b', re.IGNORECASE)),
    ("Unrated", re.compile(r'\bUnrated\b', re.IGNORECASE)),
    ("Uncut", re.compile(r'\bUncut\b', re.IGNORECASE)),
    ("Remastered", re.compile(r'\bRemastered\b', re.IGNORECASE)),
    ("Restored", re.compile(r'\bRestored\b', re.IGNORECASE)),
    ("Theatrical", re.compile(r'\bTheatrical\b', re.IGNORECASE)),
    ("IMAX", re.compile(r'\bIMAX\b', re.IGNORECASE)),
    ("Internal", re.compile(r'\bINTERNAL\b', re.IGNORECASE)),
    ("Proper", re.compile(r'\b(?:PROPER|REPACK)\b', re.IGNORECASE)),
    ("Convert", re.compile(r'\bCONVERT\b', re.IGNORECASE)),
    ("Upscaled", re.compile(r'\b(?:Upscaled|Upscale|UPSCALED)\b', re.IGNORECASE)),
    ("Hybrid", re.compile(r'\bHybrid\b', re.IGNORECASE)),
    ("DC", re.compile(r'\bDC\b', re.IGNORECASE)),  # Director's Cut abbreviation
    ("SE", re.compile(r'\bSE\b', re.IGNORECASE)),  # Special Edition
    ("CE", re.compile(r'\bCE\b', re.IGNORECASE)),  # Collector's Edition
    ("OM", re.compile(r'\bOM\b', re.IGNORECASE)),  # Open Matte
    ("INT", re.compile(r'\bINT\b', re.IGNORECASE)),  # Internal
]

# Build a combined pattern for stripping modifiers from title text
_MODIFIER_ALTERNATION = '|'.join(f'(?:{pat.pattern})' for _, pat in MODIFIERS)
MODIFIER_STRIP_PATTERN = re.compile(rf'\b(?:{_MODIFIER_ALTERNATION})\b', re.IGNORECASE)


@dataclass
class QualityInfo:
    resolution: int = 0
    source: str = ""
    codec: str = ""
    audio: str = ""
    hdr: str = ""
    is_remux: bool = False
    is_3d: bool = False
    quality_label: str = "Unknown"
    modifiers: List[str] = None  # will default to empty list

    def __post_init__(self):
        if self.modifiers is None:
            self.modifiers = []


def parse_quality(title: str) -> QualityInfo:
    """Parse quality information from a torrent/release title."""
    qi = QualityInfo()
    normalized = title.replace('_', ' ')

    # Resolution
    for res, pat in RESOLUTION_PATTERNS:
        if pat.search(normalized):
            if res > qi.resolution:
                qi.resolution = res
            break

    # Source
    for src, pat in SOURCE_PATTERNS:
        if pat.search(normalized):
            qi.source = src
            break

    # Codec
    for codec, pat in CODEC_PATTERNS:
        if pat.search(normalized):
            qi.codec = codec
            break

    # Audio
    for aud, pat in AUDIO_PATTERNS:
        if pat.search(normalized):
            qi.audio = aud
            break

    # HDR
    for hdr, pat in HDR_PATTERNS:
        if pat.search(normalized):
            qi.hdr = hdr
            break

    # Remux
    qi.is_remux = bool(REMUX_PATTERN.search(normalized))

    # 3D
    qi.is_3d = bool(THREE_D_PATTERN.search(normalized))

    # Modifiers — collect all matching modifiers
    for mod_name, pat in MODIFIERS:
        if pat.search(normalized):
            if mod_name not in qi.modifiers:
                qi.modifiers.append(mod_name)

    # Quality label
    qi.quality_label = _make_quality_label(qi)
    return qi


def _make_quality_label(qi: QualityInfo) -> str:
    """Generate a human-readable quality label."""
    parts = []
    if qi.source:
        parts.append(qi.source)
    if qi.is_remux:
        parts.append("Remux")
    if qi.resolution:
        parts.append(f"{qi.resolution}p")
    if qi.hdr:
        parts.append(qi.hdr)
    if qi.codec:
        parts.append(qi.codec)
    if qi.audio:
        parts.append(qi.audio)
    if qi.is_3d:
        parts.append("3D")
    if qi.modifiers:
        parts.append("/".join(qi.modifiers))
    return " ".join(parts) if parts else "Unknown"


def strip_modifiers(title: str) -> str:
    """Remove modifier tokens from a title string (for clean name generation)."""
    return MODIFIER_STRIP_PATTERN.sub('', title).strip()
