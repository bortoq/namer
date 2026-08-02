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

    The winner's cluster score is the evidence mass *for* its value and the
    runner-up is evidence *against*.  The posterior is the winning share of
    the total score, so an uncontested single/agreeing cluster maps to ~1.0
    and an even split collapses toward 0.5.
    """
    weights = FIELD_WEIGHTS.get(field, {})
    groups = _group_feeds(feeds, field, weights)
    if not groups:
        return 0.0
    groups.sort(key=_sort_key(field, weights, scores))
    total = sum(g['score'] for g in groups) or 1.0
    share = groups[0]['score'] / total
    return share if share <= 1.0 else 0.999


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
