# namer — developer guide

## Quick start

```bash
# run all tests
python3 -m pytest -q

# compile-check all modules
python3 -m compileall -q namer

# run the tool locally (no install)
python3 -m namer -n -d /path/to/videos
```

## Layout

| Module | Responsibility |
|---|---|
| `namer/parser.py` | mechanical filename parsing: season, episode, year, quality, ext, title. |
| `namer/identify/` | L1 typed identification: `identify_filename()` -> `Identity` (offline, confidence-aware). |
| `namer/language.py` | Wikipedia language codes + script-based detection (pure, offline). |
| `namer/quality.py` | parse/format quality tokens (`QualityInfo`, `parse_quality`). |
| `namer/provider_opinion.py` | common provider schema (`ProviderOpinion`), legacy-`Feed` compatible. |
| `namer/providers.py` | build provider opinions (filename, dirname, file, wikipedia, tvmaze, tmdb). |
| `namer/fusion.py` | Bayesian fusion of opinions -> `Verdict` (`Decision L3`). |
| `namer/voting.py` | the original weighted-cluster vote; `fuse()` is drop-in equivalent. |
| `namer/core.py` | full pipeline + policy + template rendering + atomic rename. |
| `namer/scanner.py` | recursive video-file discovery. |
| `namer/cli.py` | argument parsing / entry point. |

Higher-level architecture: see `doc/architecture-identify.md`.

## Key invariants

1. **`parse_file` is a thin adapter.** Identifying fields come from
   `identify_filename(IdentifyInput)`; the legacy flat dict is a projection.
   Guarded by `tests/test_parse_adapter.py` (byte- identical vs legacy).
2. **`fuse()` ≡ `vote()`** in winner and accept/guess/skip decision, by
   reuse of the same clustering and rules. Only `confidence` is a posterior.
   Guarded by `tests/test_fusion.py`.
3. **Never guess an expensive field** (season/episode). On ambiguity the file
   is refused (left in place).
4. **No-clobber.** Rename is atomic and never overwrites an existing entry.

## Tests

| File | Covers |
|---|---|
| `tests/test_parser.py` | parser primitives |
| `tests/test_identify.py` | L1 typed layer |
| `tests/test_parse_adapter.py` | differential: parse_file ↔ legacy |
| `tests/test_language.py` | language codes + detection |
| `tests/test_providers.py` | provider opinions |
| `tests/test_voting.py` | consensus engine |
| `tests/test_fusion.py` | schema + fusion + drop-in equivalents |
| `tests/test_core.py` | end-to-end pipeline + policy |
| `tests/test_enricher.py`, `tests/test_tvmaze.py`, `tests/test_wikipedia_episodes.py` | online providers (mocked) |

Run the whole suite: `python3 -m pytest` (342 passed / 10 deselected).

## Putting a change in

1. Add a failing test that names the required behaviour.
2. Implement against the tests; keep invariants 1–4 above.
3. Run `python3 -m pytest -q`; ensure 0 regressions.
4. If touching `fuse()` decisions, re-run the equivalence corpus so the
   drop-in guarantee still holds.
