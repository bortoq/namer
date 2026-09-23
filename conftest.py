"""Shared pytest fixtures: hermetic cache + offline providers by default.

The default `pytest` run must not depend on live Wikipedia/TVmaze/TMDB or on
the developer's ~/.cache/namer.  Tests that genuinely exercise a network
provider opt in with @pytest.mark.live and are deselected by default
(addopts "-m 'not live'" in pyproject.toml); run them with `pytest -m live`.
"""

import os
import sys

import pytest

# Make the repo root importable regardless of the CWD / checkout location.
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
# Tests must not inherit a developer's personal repo configuration.  Set this
# before importing ``namer.settings``, which resolves CONFIG_PATH at import.
os.environ['NAMER_CONFIG'] = os.path.join(_ROOT, 'tests', 'default-config.ini')


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Every test gets a private XDG_CACHE_HOME — never the user's real cache.

    Keeps the suite deterministic: a stale ~/.cache/namer from a manual run
    can no longer change pass/fail of any test (F648-001).
    """
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache'))
    # OCR is an external side effect; provider tests replace it explicitly
    # where needed, while the default suite stays hermetic.
    monkeypatch.setenv('NAMER_DISABLE_OCR', '1')


def pytest_configure(config):
    config.addinivalue_line(
        'markers',
        'live: tests that require live network providers '
        '(Wikipedia/TVmaze/TMDB); deselected by default.',
    )
