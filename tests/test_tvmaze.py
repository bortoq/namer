"""Tests for namer.tvmaze against the LIVE TVmaze API.

These hit api.tvmaze.com directly, so they are excluded from the default
run (addopts "-m 'not live'") and only executed with `pytest -m live`.
"""

import sys
sys.path.insert(0, '/home/user/work/namer')

import pytest

pytestmark = pytest.mark.live

from namer.tvmaze import enrich_episode_titles, search_show


class TestEnrichEpisodeTitles:
    def test_known_show(self):
        """TVmaze enriches with real episode title for 'The Summer Hikaru Died'."""
        meta = {
            'title': 'The Summer Hikaru Died',
            'is_series': True,
            'season': 1,
            'episode': 1,
        }
        enrich_episode_titles(meta)
        assert meta['ep_title'] == 'Replacement'

    def test_unknown_show(self):
        """No match leaves ep_title empty (fallback in core.py handles it)."""
        meta = {
            'title': 'XyzzyNoMatch',
            'is_series': True,
            'season': 1,
            'episode': 1,
        }
        enrich_episode_titles(meta)
        assert meta.get('ep_title', '') == ''

    def test_non_series(self):
        """Movies are skipped."""
        meta = {'title': 'Movie', 'is_series': False, 'season': 0, 'episode': 0}
        enrich_episode_titles(meta)
        assert 'ep_title' not in meta or meta['ep_title'] == ''

    def test_cache_hit(self):
        """Second call for same show uses cache."""
        meta = {
            'title': 'The Summer Hikaru Died',
            'is_series': True,
            'season': 1,
            'episode': 5,
        }
        enrich_episode_titles(meta)
        assert meta['ep_title'] == 'Wig Ghost'
