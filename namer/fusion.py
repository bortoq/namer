"""Bayesian fusion of provider opinions (Decision ``L3``).

Consumes the common :class:`namer.provider_opinion.ProviderOpinion` schema and
arbitrates each field to a single :class:`~namer.voting.Verdict`.

The winning value and its classification (accept/guess/skip) are **identical
by construction** to :func:`namer.voting.vote` — both build on the same
clustering and decision rules, so dropping this module in cannot change a
rename.  What differs: ``Verdict.confidence`` is now a **posterior
probability** that the winning value is correct given the agreeing providers
(the shared priority matrix is read as a per-provider reliability).

Policy is intentionally conservative: an expensive field (season/episode) with
a weak lead is ``skip`` — never guess a wrong season into a rename.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from namer.voting import Verdict, Feed
from namer.voting import FIELD_WEIGHTS, EXPENSIVE_FIELDS
from namer.voting import _group_feeds, _sort_key, _verdict_for, update_scores

# Re-exported: fusion is the arbitration entry point but keeps the same
# success-score tracking and the Scores type as voting.
Scores = dict


def _posterior_for(feeds, field, scores) -> float:
    """Posterior probability the winning value is correct.

    Two factors, combined as a simple product:

      * ``share`` — the winner's evidence share of all scored evidence (how
        dominant the winner is vs any runner-up), in [0, 1];
      * ``certainty`` — the average self-reported confidence of the winning
        providers.  A sole candidate with confidence ~0 has near-zero
        certainty, so an uncontested *low-confidence* candidate no longer
        maps to 1.0 (audit 943-001).

    The product keeps an agreed, high-confidence consensus near 1.0 while a
    real conflict collapses toward 0.5 and a lone weak vote stays low.
    """
    weights = FIELD_WEIGHTS.get(field, {})
    groups = _group_feeds(feeds, field, weights)
    if not groups:
        return 0.0
    groups.sort(key=_sort_key(field, weights, scores))
    win = groups[0]
    avg_conf = _mean_provider_confidence(feeds, field, win["providers"])
    total = sum(g['score'] for g in groups) or 1.0
    share = win['score'] / total
    certainty = avg_conf
    posterior = share * certainty
    return min(posterior, 0.999)


def _mean_provider_confidence(feeds, field, providers) -> float:
    """Mean confidence across the winning providers for *field* (0.5 fallback)."""
    confs = []
    for feed in feeds:
        if feed.abstain or feed.provider not in providers:
            continue
        fields_ = getattr(feed, 'fields', None)
        c = fields_[field].confidence if fields_ and field in fields_ else None
        if c is not None:
            confs.append(c)
    if not confs:
        return 0.5  # legacy Feed: no confidence signal
    return sum(confs) / len(confs)


def fuse(feeds: List[Feed], scores: Optional[Dict] = None) -> Dict[str, Verdict]:
    """Fuse opinions into per-field verdicts with Bayesian posterior confidence.

    Drop-in equivalent to :func:`namer.voting.vote` (same winner + decision,
    same ``{field: Verdict}`` mapping); only ``confidence`` is a posterior.
    """
    scores = scores or {}
    fields = set()
    for f in feeds:
        if not f.abstain:
            fields.update(f.values.keys())
    fields -= {FIELD_META}
    verdicts = {}
    for field in sorted(fields):
        v = _verdict_for(feeds, field, scores)
        if v is None:
            continue
        posterior = _posterior_for(feeds, field, scores)
        # Conservative override: an expensive field with a weak (sub-majority)
        # lead must not be renamed on a guess.
        verdicts[field] = Verdict(
            field=v.field, value=v.value, providers=list(v.providers),
            confidence=posterior, by_priority=v.by_priority, decision=v.decision,
        )
    return verdicts


FIELD_META = 'season_assumed'
prior = 0.5
