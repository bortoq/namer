"""Common provider-evidence schema.

Every metadata provider (filename, dirname, file, wikipedia, tvmaze, tmdb)
reports its reading of a file as a :class:`ProviderOpinion` — a single,
flexible unit the *arbitration* layer consumes.  It carries:

  * ``provider``  — which source produced this opinion;
  * ``fields``    — typed per-field candidates (value + confidence), aligned
                    with :class:`namer.identify.FieldCandidate`;
  * ``abstain``   — a non-committal opinion (network failure) ignored by
                    arbitration;

and projects to the legacy flat ``{field: value}`` dict via
:func:`ProviderOpinion.values` so existing consumers (voting, core) keep
working unchanged.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from namer.identify.models import FieldCandidate


class ProviderOpinion:
    """A single provider's reading of one file.

    Backward compatible with the former ``Feed`` constructor
    ``Feed(provider, values, abstain)``.
    """

    def __init__(self, provider: str, values: Optional[Dict[str, Any]] = None,
                 abstain: bool = False):
        self.provider: str = provider
        self.fields: Dict[str, FieldCandidate] = {}
        self.abstain: bool = abstain
        self.meta: Dict[str, Any] = {}
        for k, v in (values or {}).items():
            self.set(k, v)

    def set(self, field_name: str, value: Any, confidence: float = 0.9) -> None:
        """Record one field with its confidence (non-None value)."""
        if value in (None, ''):
            return
        self.fields[field_name] = FieldCandidate(value, confidence, [self.provider])

    def flat(self) -> Dict[str, Any]:
        """Legacy flat dict of values for template/voting compatibility."""
        out: Dict[str, Any] = {f: c.value for f, c in self.fields.items()}
        out.update(self.meta)
        return out

    # ── Legacy accessors (Feed duck-typing) ─────────────────────────────────
    @property
    def values(self) -> Dict[str, Any]:
        return self.flat()

    def __repr__(self) -> str:
        return f"ProviderOpinion({self.provider!r}, {self.flat()!r})"


# Backward-compatible alias for code importing ``Feed``.
Feed = ProviderOpinion
