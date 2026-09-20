"""Book domain model — isolated from video pipeline.

Contract (Architect):
- Local extractors produce only dirty BookQuery (hints for network search).
- Canonical display values live only in BookRecord (network provenance,
  or provisional local record explicitly marked 'local').
- Never raise on dirty input; empty query / unresolved identity instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ReadBudget:
    """Safety limits for archive/binary parsing (zip-bomb, XML-bomb)."""
    max_uncompressed: int = 16 * 1024 * 1024
    max_entries: int = 512
    max_xml_bytes: int = 2 * 1024 * 1024
    timeout_sec: float = 5.0


@dataclass(frozen=True)
class BookQuery:
    """Dirty hints for network search. NOT display values."""
    title_hint: str = ''
    authors_hint: tuple = ()
    series_hint: str = ''
    series_index_hint: Optional[int] = None
    isbn_hint: str = ''
    lang_hint: str = ''
    year_hint: Optional[int] = None
    fingerprint: str = ''
    source_format: str = ''

    def is_empty(self) -> bool:
        # AUDIT: explicit type guards — non-str hints count as missing.
        try:
            title = self.title_hint if isinstance(self.title_hint, str) else ''
            series = self.series_hint if isinstance(self.series_hint, str) else ''
            isbn = self.isbn_hint if isinstance(self.isbn_hint, str) else ''
            fp = self.fingerprint if isinstance(self.fingerprint, str) else ''
            authors = (self.authors_hint
                       if isinstance(self.authors_hint, (tuple, list)) else ())
            return not (title.strip() or tuple(authors)
                        or series.strip() or isbn.strip() or fp.strip())
        except Exception:
            return True

    def has_isbn(self) -> bool:
        return bool((self.isbn_hint or '').strip())


@dataclass(frozen=True)
class BookRecord:
    """Canonical values for template rendering."""
    title: str = ''
    authors: tuple = ()
    series: str = ''
    series_index: Optional[int] = None
    year: Optional[int] = None
    language: str = ''
    isbn13: str = ''
    publisher: str = ''
    provider: str = 'local'  # openlibrary | googlebooks | local
    provider_id: str = ''
    confidence: float = 0.6

    def __post_init__(self) -> None:
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError(f'confidence must be in [0,1], got {self.confidence!r}')

    @property
    def primary_author(self) -> str:
        return self.authors[0] if self.authors else ''

    @property
    def authors_display(self) -> str:
        return ', '.join(self.authors) if self.authors else ''


@dataclass(frozen=True)
class BookOpinion:
    """One catalogue answer for fusion."""
    provider: str
    record: BookRecord
    confidence: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError(f'confidence must be in [0,1], got {self.confidence!r}')


@dataclass
class BookIdentity:
    """Offline identification result + optional fused record."""
    status: str = 'unresolved'  # identified | ambiguous | unresolved
    title: str = ''
    authors: list = field(default_factory=list)
    series: str = ''
    series_index: Optional[int] = None
    year: Optional[int] = None
    language: str = ''
    isbn: str = ''
    ext: str = ''
    query: Optional[BookQuery] = None
    record: Optional[BookRecord] = None
    warnings: list = field(default_factory=list)
    evidence: list = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.status == 'identified' and bool(self.title and len(self.title) >= 2)
