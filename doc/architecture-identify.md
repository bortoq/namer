# Architecture: identification & fusion pipeline

*Applied as part of the L0–L3 groundwork. This document describes the
current, implemented behaviour — it is owned by the implementation, not the
product roadmap (that lives in `roadmap.md`, owned by the Architect).*

## Layers

| Layer | Module | Answer |
|---|---|---|
| L0 raw input | `namer/parser.py` | mechanical parsing: season/episode/year/quality/ext/title |
| L1 typed identify | `namer/identify/` | *what is this file & how confident are we* — offline, deterministic, no network |
| L2 provider evidence | `namer/provider_opinion.py`, `namer/providers.py` | per-source typed opinions with confidence |
| L2 arbitration | `namer/fusion.py` (was `voting.py`) | fused verdict + posterior confidence, `Decision L3` |
| L3 policy | `namer/core.py` | decide rename / refuse (ambiguous -> leave in place) |

## Data flow

```
filename ──> parse_file ──> Identity (identify_filename)
                     │
                     └──> providers.(filename|dirname|file|wiki|tvmaze|tmdb)
                              └──> [ProviderOpinion] ──> fuse() ──> Verdict
                                                                  └──> core decides -> template -> rename
```

## Contracts

- `parse_file(path) -> dict` is a **thin adapter** over `identify_filename(IdentifyInput)`:
  the identifying fields come from the typed layer; the legacy flat dict is a
  projection. Byte-identical output is guarded by `tests/test_parse_adapter.py`.
- `ProviderOpinion` is duck-type compatible with the legacy `Feed`
  (`provider`, `values`, `abstain`), so `vote()` and template rendering run unchanged.
- `fuse()` ≡ `vote()` in winner + decision by construction; only `confidence`
  becomes a posterior probability. The equivalence harness lives in
  `tests/test_fusion.py`.
- **Single source for provider weight:** effective weight =
  `FIELD_WEIGHTS[field][provider] × candidate.confidence`
  (`voting._effective_weight`). The priority matrix is the cross-provider base
  and each provider's own confidence is the per-field lever; legacy
  confidence-less feeds are unaffected (factor 1.0). See
  `tests/test_weight_merge.py`.
- Language codes + script detection: `namer/language.py` (pure, offline).
  `wikipedia.py` re-exports for backward compat.

## Decision L3 policy

An expensive field (season/episode) that cannot reach a confident lead is
refused (`skip`) rather than guessed into a rename. A real conflict
(resolution skew) collapses the posterior toward 0.5 → no rename.

## Test surface

- `tests/test_identify.py` — L1 typed layer (17)
- `tests/test_parse_adapter.py` — parse_file ↔ legacy differential (31)
- `tests/test_language.py` — language codes + script detect (24)
- `tests/test_fusion.py` — schema + fusion + drop-in equivalence (5)
- `tests/test_providers.py`, `tests/test_voting.py` — providers + arbitration

Total: 342 passed / 10 deselected.
