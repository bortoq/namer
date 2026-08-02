"""Consensus voting across metadata providers.

Every provider casts a *feed*: a dict of named {} fields (title, season,
episode, ep_title, year, resolution, ...).  For each field the providers
that supplied a value are clustered by agreement; the strongest cluster
wins.  Cluster strength is the sum of per-field provider weights (the
field→provider priority matrix) with the running success score as a final
tie-break.  Each verdict is then classified:

  - 'accept' — confident, use the value;
  - 'guess'  — cheap field, acceptable risk;
  - 'skip'   — expensive field without a clear winner → refuse to act
               (better than a wrong rename).

Winner providers score +1 for the field, losers +0.  Only fields that at
least two providers weighed in on are tracked in the running scores.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from .wikipedia import get_entity_qid

# ── Priority (weight) matrix: field → provider → weight ─────────────────────
# Weights are deliberately NOT equal: ffprobe ≫ filename for codec/resolution,
# wikipedia/tvmaze/tmdb ≫ filename for title and episode identity.
FIELD_WEIGHTS: Dict[str, Dict[str, float]] = {
    'season':      {'wikipedia': 5.0, 'tvmaze': 5.0, 'tmdb': 5.0,
                    'filename': 4.0, 'dirname': 2.0, 'file': 1.0},
    'episode':     {'wikipedia': 5.0, 'tvmaze': 5.0, 'tmdb': 5.0,
                    'filename': 4.0, 'dirname': 2.0, 'file': 1.0},
    'ep_title':    {'wikipedia': 5.0, 'tvmaze': 5.0, 'tmdb': 5.0},
    'title':       {'wikipedia': 5.0, 'tvmaze': 5.0, 'tmdb': 5.0,
                    'filename': 1.0, 'dirname': 1.0},
    'year':        {'tmdb': 5.0, 'wikipedia': 4.0, 'tvmaze': 4.0,
                    'dirname': 1.0, 'filename': 1.0},
    'resolution':  {'file': 5.0, 'dirname': 1.0, 'filename': 1.0},
    'codec':       {'file': 5.0, 'dirname': 1.0, 'filename': 1.0},
    'audio_codec': {'file': 5.0, 'dirname': 1.0, 'filename': 1.0},
    'channels':    {'file': 5.0, 'dirname': 1.0, 'filename': 1.0},
    'quality':     {'file': 5.0, 'dirname': 1.0, 'filename': 1.0},
}

# Fields where a wrong guess is expensive → refuse unless the winner is solid.
EXPENSIVE_FIELDS = frozenset({'season', 'episode'})

# A lone vote on an expensive field (season/episode) needs BOTH a strong
# *effective* weight (base x confidence, x 0.5 when weak/assumed) AND a
# minimum self-reported confidence.  filename explicit base 4.0 x 0.9 = 3.6
# and explicit dirname (base 2.0 x 0.8 = 1.6) pass; assumed filename
# (4.0 x 0.6 x 0.5 = 1.2) passes as the only signal.  The strict effective
# floor 1.1 refuses base-1.0 providers (file / unknown: max possible weight
# 1.0) however confident (ACE-001), and any low-confidence candidate (e.g.
# filename 4.0 x 0.25 = 1.0, wikipedia 5.0 x 0.2 = 1.0) also fails the strict
# boundary (ACE-002).  Legacy Feed objects (no confidence) keep the raw matrix
# weight and skip the confidence gate.
MIN_EXPENSIVE_SINGLE_EFFECTIVE = 1.1

# A lone expensive vote also requires the winning providers to *themselves*
# be confident (>= 0.6), not just have a favourable base x conf product.
MIN_EXPENSIVE_SINGLE_CONFIDENCE = 0.6

# Title similarity threshold for cross-provider agreement.
TITLE_MATCH_RATIO = 0.85
# A provider whose value came from a weak fallback (assumed season) votes
# with a discounted weight so it cannot manufacture a false consensus.
WEAK_WEIGHT_FACTOR = 0.5

# Master switch for QID lookups (off in tests / offline environments).
QID_LOOKUP_ENABLED = True

# Placeholder episode titles like "Episode 1" / "Ep.10": never fuzzy-match
# these across providers (prefix collision: "Episode 1" ≈ "Episode 10").
_NUMBERED_EPISODE_RE = re.compile(r'^(?:episode|ep|ep\.)\s*\d{1,3}$', re.IGNORECASE)

Scores = Dict[str, Dict[str, float]]  # provider → field → success count


@dataclass
class Feed:
    """A single provider's opinion about a file."""
    provider: str
    values: Dict[str, Any] = field(default_factory=dict)
    # Non-committal feed (e.g. a network provider that failed); ignored by voting.
    abstain: bool = False


@dataclass
class Verdict:
    field: str
    value: Any
    providers: List[str]      # providers in the winning cluster
    confidence: float         # winner_score / total_score (0..1)
    by_priority: bool         # winner resolved via the priority matrix
    decision: str             # 'accept' | 'guess' | 'skip'

    @property
    def usable(self) -> bool:
        return self.decision in ('accept', 'guess')


# ── Agreement ────────────────────────────────────────────────────────────────

def _normalize_title(s: str) -> str:
    return re.sub(r'\s+', ' ', s.strip().lower())


def _qid(value: str) -> Optional[str]:
    if not QID_LOOKUP_ENABLED:
        return None
    try:
        return get_entity_qid(value)
    except Exception:
        return None


def _titles_agree(a: str, b: str) -> bool:
    """True when two title strings refer to the same thing.

    Exact match → QID equality (synonyms like 'Yuru Camp' vs 'Laid-Back
    Camp') → fuzzy similarity.  Placeholder episode titles never fuzzy-match.
    """
    na, nb = _normalize_title(a), _normalize_title(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if _NUMBERED_EPISODE_RE.match(na) or _NUMBERED_EPISODE_RE.match(nb):
        return False
    # Clean containment: one name is a word-for-word subset of the other
    # (e.g. directory "Attack on Titan" inside "Attack on Titan Final
    # Season" filename).  Same-show, cleaner spelling wins later.
    if min(len(na), len(nb)) >= 4 and (na in nb or nb in na):
        return True
    qa, qb = _qid(na), _qid(nb)
    if qa and qb and qa == qb:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= TITLE_MATCH_RATIO


def _values_agree(field: str, a: Any, b: Any) -> bool:
    if a is None or b is None:
        return False
    if field in ('title', 'ep_title'):
        return _titles_agree(str(a), str(b))
    return a == b


# ── Single source of truth for provider weight ────────────────────────────────
#
# A provider's effective weight is the product of its priority in the matrix
# (FIELD_WEIGHTS, cross-provider ranking) and its own confidence for the field
# (ProviderOpinion.fields[field].confidence).  Legacy Feed objects carry no
# confidence, so their weight stays equal to the matrix value — behaviour is
# therefore unchanged for them.  This is the one place the two inputs meet.

def _effective_weight(feed, field: str, weights: Dict[str, float]) -> float:
    base = weights.get(feed.provider, 1.0)
    fields = getattr(feed, 'fields', None)
    conf = fields[field].confidence if fields and field in fields else None
    return base * conf if conf is not None else base


def _max_provider_confidence(feeds, field: str, providers: List[str]) -> float:
    """Highest self-reported confidence among the winning providers.

    Legacy Feed objects carry no confidence → return 1.0 so they pass the
    gate unchanged (their trust lives in the base matrix weight).
    """
    best = None
    for feed in feeds:
        if feed.abstain or feed.provider not in providers:
            continue
        fields = getattr(feed, 'fields', None)
        c = fields[field].confidence if fields and field in fields else None
        if c is not None and (best is None or c > best):
            best = c
    return best if best is not None else 1.0


# ── Clustering ───────────────────────────────────────────────────────────────

def _group_feeds(feeds: List[Feed], field: str,
                 weights: Dict[str, float]) -> List[Dict[str, Any]]:
    """Cluster feeds by agreement on *field*.

    Each cluster: {'value', 'providers', 'weak', 'score', 'value_weight'}.
    The cluster score is the sum of provider weights; values marked as weak
    (assumed season) contribute with a discounted weight.

    For expensive fields, a weak (assumed) value never competes with an
    explicit one: if any explicit value exists, weak votes are dropped.
    """
    explicit_exists = False
    weak_feeds = []
    if field in EXPENSIVE_FIELDS:
        for feed in feeds:
            if feed.abstain or field not in feed.values:
                continue
            val = feed.values[field]
            if val is None or val == '':
                continue
            if bool(feed.values.get('season_assumed')):
                weak_feeds.append(feed)
            else:
                explicit_exists = True

    groups: List[Dict[str, Any]] = []
    for feed in feeds:
        if feed.abstain or field not in feed.values:
            continue
        val = feed.values[field]
        if val is None or val == '':
            continue
        weak = bool(feed.values.get('season_assumed')) and field in ('season', 'episode')
        if weak and field in EXPENSIVE_FIELDS and explicit_exists:
            continue  # an assumed value must not outvote an explicit one
        weight = weights.get(feed.provider, 1.0)
        eff_weight = _effective_weight(feed, field, weights) \
            * (WEAK_WEIGHT_FACTOR if weak else 1.0)
        target = None
        for g in groups:
            if _values_agree(field, g['value'], val):
                target = g
                break
        if target is None:
            target = {'value': val, 'providers': [], 'weak': [], 'score': 0.0,
                      'value_weight': 0.0}
            groups.append(target)
        target['providers'].append(feed.provider)
        if weak:
            target['weak'].append(feed.provider)
        target['score'] += eff_weight
        # The displayed value comes from the highest-priority member (the
        # wikipedia title wins over the filename spelling inside an agreeing
        # cluster); on equal priority the cleaner (shorter) value wins.
        if weight > target['value_weight'] or (
            weight == target['value_weight']
            and len(str(val)) < len(str(target['value']))
        ):
            target['value'] = val
            target['value_weight'] = weight
    return groups


def _sort_key(field: str, weights: Dict[str, float], scores: Scores):
    """Sort clusters: score desc → max member weight desc → success score
    desc → real titles before placeholder titles ('Episode N')."""
    def key(g: Dict[str, Any]) -> tuple:
        max_w = max(weights.get(p, 0.0) for p in g['providers'])
        succ = sum(scores.get(p, {}).get(field, 0.0) for p in g['providers'])
        placeholder = (1.0 if isinstance(g['value'], str)
                       and _NUMBERED_EPISODE_RE.match(g['value']) else 0.0)
        # The filename is the identity source: on exact ties its value wins.
        filename_boost = 1.0 if 'filename' in g['providers'] else 0.0
        return (-g['score'], -max_w, -succ, placeholder, -filename_boost)
    return key


def _verdict_for(feeds: List[Feed], field: str, scores: Scores) -> Optional[Verdict]:
    weights = FIELD_WEIGHTS.get(field, {})
    groups = _group_feeds(feeds, field, weights)
    if not groups:
        return None
    groups.sort(key=_sort_key(field, weights, scores))
    win = groups[0]
    runner = groups[1] if len(groups) > 1 else None
    total = sum(g['score'] for g in groups)
    win_score = win['score']
    run_score = runner['score'] if runner else 0.0
    ratio = win_score / total if total > 0 else 0.0
    win_n = len(win['providers'])
    by_priority = runner is not None and abs(win_score - run_score) < 1e-9
    expensive = field in EXPENSIVE_FIELDS

    if expensive:
        # A clear majority of agreeing providers beats the runner-up.
        if win_n >= 2 and win_score > run_score:
            decision = 'accept'
        # Equal-strength camps → a real conflict; even the priority matrix
        # winner is not trustworthy enough for expensive fields → refuse.
        elif by_priority:
            decision = 'skip'
        # One provider, no opposition, and the winning signal clears both
        # gates: effective weight strictly above the floor (base-1.0 providers
        # never reach 1.1) AND a decent self-confidence (ACE-002).  A low
        # confidence guess (filename 4.0 x 0.25 = 1.0) and a perfectly
        # confident base-1 provider (file x 1.0 = 1.0) both fail the strict
        # boundary.  Legacy Feeds keep their raw matrix weight and pass the
        # confidence gate (no confidence → 1.0).
        elif (win_n == 1 and total == win_score
              and win_score > MIN_EXPENSIVE_SINGLE_EFFECTIVE
              and _max_provider_confidence(feeds, field, win['providers'])
              >= MIN_EXPENSIVE_SINGLE_CONFIDENCE):
            decision = 'accept'
        else:
            decision = 'skip'
    else:
        if win_n >= 2 or ratio >= 0.5:
            decision = 'accept'
        else:
            decision = 'guess'

    return Verdict(field=field, value=win['value'], providers=list(win['providers']),
                   confidence=ratio, by_priority=by_priority, decision=decision)


# ── Public API ───────────────────────────────────────────────────────────────

# Fields that describe the vote itself, not the file — never voted on.
_META_FIELDS = frozenset({'season_assumed'})


def vote(feeds: List[Feed], scores: Optional[Scores] = None) -> Dict[str, Verdict]:
    """Run consensus voting; return {field: Verdict} for every supplied field."""
    scores = scores or {}
    fields = set()
    for f in feeds:
        if not f.abstain:
            fields.update(f.values.keys())
    fields -= _META_FIELDS
    verdicts: Dict[str, Verdict] = {}
    for field in sorted(fields):
        v = _verdict_for(feeds, field, scores)
        if v is not None:
            verdicts[field] = v
    return verdicts


def update_scores(scores: Scores, feeds: List[Feed],
                  verdicts: Dict[str, Verdict]) -> Scores:
    """Winner +1 / losers +0 per field.

    Only fields that at least two providers weighed in on are tracked
    ('store only what several providers agree on').
    """
    for field, verdict in verdicts.items():
        voters = [f.provider for f in feeds
                  if not f.abstain and f.values.get(field) not in (None, '')]
        if len(voters) < 2:
            continue
        win_set = set(verdict.providers)
        for p in voters:
            entry = scores.setdefault(p, {})
            entry[field] = entry.get(field, 0.0) + (1.0 if p in win_set else 0.0)
    return scores


def usable_values(verdicts: Dict[str, Verdict]) -> Dict[str, Any]:
    """Values of usable (accept/guess) verdicts, for template rendering."""
    return {f: v.value for f, v in verdicts.items() if v.usable}
