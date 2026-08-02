"""Typed domain model for media-file identification.

This is the tagged, confidence-carrying result of deciding *what a file is*,
before any enrichment, voting or rename decision.  A file is identified
offline and deterministically; all fields carry a candidate value plus the
source, reasoning and an explicit ambiguity flag so the caller can decide
whether the result is safe to act on.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class MediaType(str, Enum):
    MOVIE = 'movie'
    SERIES_EPISODE = 'series_episode'
    UNKNOWN = 'unknown'


class Status(str, Enum):
    """Overall resolution confidence of the whole identification."""

    IDENTIFIED = 'identified'
    AMBIGUOUS = 'ambiguous'
    UNRESOLVED = 'unresolved'


@dataclass(frozen=True)
class FieldCandidate:
    """A single candidate value for one identifying field.

    ``value`` is guaranteed to be non-None (omit the candidate entirely when
    the field is unknown).  ``confidence`` is in [0, 1] and comes from the
    lexical parsing of the inputs.
    """

    value: Any
    confidence: float
    sources: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class Decision:
    """A boolean-ish field with an explicit confidence and a reason.

    Replaces raw booleans (``is_multi_episode``, ``is_series``) so a caller
    can distinguish "high-confidence multi" from "ambiguous, keep as-is".
    """

    value: bool
    confidence: float
    reason: str = ''
    ambiguity: bool = False


@dataclass(frozen=True)
class Evidence:
    """A single piece of evidence for an identification."""

    source: str  # filename / dirname / ffprobe / embedded / hint
    field: str  # title / season / episode / year / media_type / multi ...
    detail: str = ''


@dataclass
class IdentificationWarning:
    """A non-fatal note about why a field is ambiguous or guessed."""

    code: str
    message: str
    field: str = ''


@dataclass
class Identity:
    """Every signal derived from an ``IdentifyInput``.

    This is the single public result of the identification layer.  It carries
    per-field candidates, an overall status, and the supporting evidence and
    warnings so the upper layers can make a safe, explainable decision.
    """

    media_type: MediaType = MediaType.UNKNOWN
    status: Status = Status.UNRESOLVED
    title: Optional[FieldCandidate] = None
    original_title: Optional[FieldCandidate] = None
    year: Optional[FieldCandidate] = None
    season: Optional[FieldCandidate] = None
    episode: Optional[FieldCandidate] = None
    episodes: List[FieldCandidate] = field(default_factory=list)
    is_multi_episode: Optional[Decision] = None
    is_special: bool = False
    season_assumed: bool = False
    ext: str = ''
    quality: Optional[Dict[str, Any]] = None  # normalized quality dict
    duration: Optional[float] = None
    evidence: List[Evidence] = field(default_factory=list)
    warnings: List[IdentificationWarning] = field(default_factory=list)

    @property
    def is_series(self) -> bool:
        return self.media_type is MediaType.SERIES_EPISODE

    @property
    def title_value(self) -> Optional[str]:
        return self.title.value if self.title else None

    @property
    def year_value(self) -> Optional[int]:
        return self.year.value if self.year else None

    @property
    def is_multi_episode_value(self) -> bool:
        return bool(self.is_multi_episode and self.is_multi_episode.value)


@dataclass
class IdentifyInput:
    """Everything the identifier is allowed to look at."""

    filename: str
    parent_dirs: List[str] = field(default_factory=list)
    path: Optional[str] = None
    file_size: Optional[int] = None
    duration: Optional[float] = None
    embedded_metadata: Optional[Dict[str, Any]] = None
    user_hints: Optional[Dict[str, Any]] = None  # {'title','season','episode','year'}
    language: str = 'en'

    def basename(self) -> str:
        if self.path:
            basename = self.path.replace('\\', '/').rsplit('/', 1)[-1]
            if basename:
                return basename
        return self.filename or ''
