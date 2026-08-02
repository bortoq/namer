"""namer — deterministic media-file renaming.

Pipeline: parse filename -> typed identity (L1) -> provider evidence (L2)
-> Bayesian fusion (L2) -> policy/rename decision (L3).

See ``doc/architecture-identify.md`` for the layer contracts.
"""
