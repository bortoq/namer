"""Tests for namer.enricher and namer.tmdb."""

import sys
sys.path.insert(0, '/home/user/work/namer')

import pytest

from namer.enricher import enrich_meta
from namer.tmdb import (
    _resolve_key,
    get_tv_show_id,
    get_season_episode_titles,
    search_movie,
    enrich_year,
)


class TestResolveKey:
    def test_no_key(self):
        assert _resolve_key('') == ''  # no env, no config

    def test_direct_key(self):
        assert _resolve_key('abc123') == 'abc123'

    def test_env_key(self):
        import os
        os.environ['TMDB_API_KEY'] = 'env_key_test'
        assert _resolve_key('') == 'env_key_test'
        del os.environ['TMDB_API_KEY']


class TestEnrichMeta:
    def test_no_key_noop(self):
        meta = {'title': 'Test', 'season': 1, 'episode': 2, 'is_series': True}
        enrich_meta(meta, tmdb_key='')
        assert meta.get('ep_title', '') == ''

    @pytest.mark.live
    def test_series_enrich(self):
        """With a key, enrichment should work (network)."""
        import os
        key = os.environ.get('TMDB_API_KEY', '')
        if not key:
            pytest.skip('TMDB_API_KEY not set')
        meta = {
            'title': 'Breaking Bad',
            'season': 1,
            'episode': 1,
            'is_series': True,
            'year': 0,
        }
        enrich_meta(meta, tmdb_key=key)
        # Should find episode title and year
        assert meta.get('ep_title') == 'Pilot'
        assert meta['year'] == 2008

    @pytest.mark.live
    def test_movie_year(self):
        import os
        key = os.environ.get('TMDB_API_KEY', '')
        if not key:
            pytest.skip('TMDB_API_KEY not set')
        meta = {'title': 'The Matrix', 'is_series': False, 'year': 0}
        enrich_meta(meta, tmdb_key=key)
        assert meta['year'] == 1999
