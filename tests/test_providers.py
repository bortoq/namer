"""Tests for provider feed construction (offline, no network)."""

import os

import pytest

from namer.parser import parse_file
from namer.providers import (
    Feed, filename_feed, dirname_feed, file_feed, local_feeds, online_feeds,
    wikipedia_feed, tvmaze_feed, tmdb_feed, _validated_match,
)


# ── filename feed ────────────────────────────────────────────────────────────

def test_filename_feed_explicit_series():
    feed = filename_feed('Show.S01E05.1080p.mkv')
    assert feed.provider == 'filename'
    assert feed.values['season'] == 1
    assert feed.values['episode'] == 5
    # The title is only a hint for the online lookup, never a local vote.
    assert 'title' not in feed.values
    assert not feed.values.get('season_assumed')


def test_filename_feed_assumed_season_flag():
    feed = filename_feed('Show - 05.mkv')
    assert feed.values['season'] == 1
    assert feed.values['episode'] == 5
    assert feed.values['season_assumed'] is True


def test_filename_feed_special_maps_season_0():
    feed = filename_feed('Show [Special] [01].mkv')
    assert feed.values['season'] == 0
    assert feed.values['episode'] == 1
    assert not feed.values.get('season_assumed')


def test_filename_feed_no_season_signal():
    """A movie-like file votes no season/episode (0 = not found)."""
    feed = filename_feed('Some Movie 2020.mkv')
    assert 'season' not in feed.values
    assert 'episode' not in feed.values


def test_filename_feed_known_title_not_voted():
    """-t is applied to meta by core; the filename feed must not re-vote it."""
    feed = filename_feed('Show.S01E01.mkv', known_title='My Known Title')
    assert 'title' not in feed.values


def test_filename_feed_quality_fields():
    feed = filename_feed('Show.S01E01.1080p.BluRay.x264.mkv')
    assert feed.values['resolution'] == '1080p'
    assert feed.values['codec'] == 'x264'


# ── dirname feed ─────────────────────────────────────────────────────────────

def test_dirname_feed_season_only(tmp_path):
    """The dir title is a hint (applied by core), not a vote."""
    show = tmp_path / 'Natsume Yuujinchou S7'
    show.mkdir(parents=True)
    fpath = show / 'Show 01.mkv'
    feed = dirname_feed(str(fpath))
    assert feed.values['season'] == 7
    assert 'title' not in feed.values


def test_dirname_feed_season_2_from_season_folder(tmp_path):
    show = tmp_path / 'Show' / 'Season 2'
    show.mkdir(parents=True)
    feed = dirname_feed(str(show / 'Show.S02E01.mkv'))
    assert feed.values['season'] == 2


def test_dirname_feed_generic_path_no_values():
    """A real generic temp dir (in /tmp) yields no title/season vote."""
    import tempfile
    tmp = tempfile.mkdtemp()
    feed = dirname_feed(os.path.join(tmp, 'Show.S01E01.mkv'))
    assert feed.values == {}


# ── file feed (ffprobe) ──────────────────────────────────────────────────────

def test_file_feed_dummy_file_no_metadata(tmp_path):
    fpath = tmp_path / 'x.mkv'
    fpath.write_bytes(b'dummy')
    feed = file_feed(str(fpath))
    assert feed.values == {}


# ── orchestration ────────────────────────────────────────────────────────────

def test_local_feeds_order(tmp_path):
    fpath = tmp_path / 'Show.S01E01.mkv'
    fpath.write_bytes(b'dummy')
    feeds = local_feeds(str(fpath))
    assert [f.provider for f in feeds] == ['filename', 'dirname', 'file']


def test_online_feeds_require_title(monkeypatch):
    """Without a title there is nothing to look up online."""
    monkeypatch.setattr('namer.providers.wikipedia_feed',
                        lambda meta, lang: Feed('wikipedia', {}))
    monkeypatch.setattr('namer.providers.tvmaze_feed',
                        lambda meta, lang: Feed('tvmaze', {}))
    meta = {'title': '', 'is_series': True}
    assert online_feeds(meta) == []


def test_online_feeds_structure(monkeypatch):
    monkeypatch.setattr('namer.providers.wikipedia_feed',
                        lambda meta, lang: Feed('wikipedia', {'title': 'X'}))
    monkeypatch.setattr('namer.providers.tvmaze_feed',
                        lambda meta, lang: Feed('tvmaze', {'title': 'X'}))
    monkeypatch.setattr('namer.providers.tmdb_feed',
                        lambda meta, key, lang: Feed('tmdb', {'title': 'X'}))
    meta = {'title': 'Show', 'is_series': True}
    feeds = online_feeds(meta, tmdb_key='k')
    assert [f.provider for f in feeds] == ['wikipedia', 'tvmaze', 'tmdb']
    feeds = online_feeds(meta)
    assert [f.provider for f in feeds] == ['wikipedia', 'tvmaze']


def test_parse_file_keeps_season_assumed_key():
    """parse_file exposes the assumption flag for the filename feed."""
    meta = parse_file('Show - 05.mkv')
    assert meta['season_assumed'] is True
    meta = parse_file('Show.S01E05.mkv')
    assert meta['season_assumed'] is False


# ── title validation (hint vs. canonical lookup result) ──────────────────────

def test_validated_match_accepts_junked_hint():
    """Release junk in the hint must not block a real canonical match."""
    assert _validated_match('Justice League Dark DDP', 'Justice League Dark',
                            2017, 2017)
    assert _validated_match('Show Pilot HE', 'Show Pilot', None, None)
    assert _validated_match('The Matrix', 'The Matrix', 1999, 1999)


def test_validated_match_year_confirmed_synonym():
    """Translated/alternate names pass when the year confirms them."""
    assert _validated_match('Yuru Camp', 'Laid-Back Camp', 2018, 2018)


def test_validated_match_rejects_conflicts():
    assert not _validated_match('Justice League Dark', 'Justice League Dark',
                                2017, 2012)          # year conflict
    assert not _validated_match('Justice League Dark', 'Totally Different',
                                None, None)          # no overlap
    assert not _validated_match('Show', 'Show Pilot', None, None)  # too thin


# ── wikipedia feed: canonicalize, never echo the hint ────────────────────────

def test_wikipedia_feed_canonicalizes(monkeypatch):
    monkeypatch.setattr('namer.wikipedia.search_canonical_title',
                        lambda hint, lang='en': 'Justice League Dark')
    monkeypatch.setattr('namer.wikipedia.fetch_show_year',
                        lambda title, lang='en': 2017)
    op = wikipedia_feed({'title': 'Justice League Dark DDP', 'year': 2017,
                         'is_series': False}, 'en')
    assert op.values['title'] == 'Justice League Dark'
    assert op.values['year'] == 2017


def test_wikipedia_feed_abstains_when_no_page(monkeypatch):
    monkeypatch.setattr('namer.wikipedia.search_canonical_title',
                        lambda hint, lang='en': None)
    op = wikipedia_feed({'title': 'Some Junk HE', 'is_series': False}, 'en')
    assert op.abstain
    assert op.values == {}


def test_wikipedia_feed_abstains_on_year_conflict(monkeypatch):
    """Hint year vs. page year mismatch → the page is the wrong work."""
    monkeypatch.setattr('namer.wikipedia.search_canonical_title',
                        lambda hint, lang='en': 'Justice League Dark')
    monkeypatch.setattr('namer.wikipedia.fetch_show_year',
                        lambda title, lang='en': 2012)
    op = wikipedia_feed({'title': 'Justice League Dark DDP', 'year': 2017,
                         'is_series': False}, 'en')
    assert op.abstain
    assert 'title' not in op.values


def test_wikipedia_feed_abstains_on_word_mismatch(monkeypatch):
    monkeypatch.setattr('namer.wikipedia.search_canonical_title',
                        lambda hint, lang='en': 'Totally Different Movie')
    monkeypatch.setattr('namer.wikipedia.fetch_show_year',
                        lambda title, lang='en': None)
    op = wikipedia_feed({'title': 'Justice League Dark DDP', 'year': 2017,
                         'is_series': False}, 'en')
    assert op.abstain
    assert 'title' not in op.values


def test_wikipedia_feed_episode_title_requires_resolution(monkeypatch):
    monkeypatch.setattr('namer.wikipedia.search_canonical_title',
                        lambda hint, lang='en': 'Laid-Back Camp')
    monkeypatch.setattr('namer.wikipedia.fetch_show_year',
                        lambda title, lang='en': 2018)
    monkeypatch.setattr('namer.wikipedia.fetch_episode_titles',
                        lambda title, lang='en': {(1, 1): 'Mount Fuji'})
    op = wikipedia_feed({'title': 'Yuru Camp', 'year': 2018, 'is_series': True,
                         'season': 1, 'episode': 1, 'season_assumed': False}, 'en')
    assert op.values['title'] == 'Laid-Back Camp'
    assert op.values['ep_title'] == 'Mount Fuji'


# ── tvmaze feed: vote only when the show was resolved ────────────────────────

def test_tvmaze_feed_does_not_echo_hint_when_not_resolved(monkeypatch):
    monkeypatch.setattr('namer.tvmaze.enrich_episode_titles',
                        lambda meta, language='en': meta)
    op = tvmaze_feed({'title': 'Show Pilot HE', 'is_series': True,
                      'season': 1, 'episode': 1}, 'en')
    assert op.abstain
    assert op.values == {}


def test_tvmaze_feed_votes_canonical_when_resolved(monkeypatch):
    def fake_enrich(meta, language='en'):
        meta['_tvmaze_resolved'] = True
        meta['title'] = 'Laid-Back Camp'
        meta['year'] = 2018
        meta['ep_title'] = 'Mount Fuji'
        return meta
    monkeypatch.setattr('namer.tvmaze.enrich_episode_titles', fake_enrich)
    op = tvmaze_feed({'title': 'Yuru Camp', 'is_series': True, 'year': 2018,
                      'season': 1, 'episode': 1, 'season_assumed': False}, 'en')
    assert op.values['title'] == 'Laid-Back Camp'
    assert op.values['year'] == 2018
    assert op.values['ep_title'] == 'Mount Fuji'


def test_tvmaze_feed_abstains_on_year_conflict(monkeypatch):
    def fake_enrich(meta, language='en'):
        meta['_tvmaze_resolved'] = True
        meta['title'] = 'Laid-Back Camp'
        meta['year'] = 2010  # wrong show: hint year is 2018
        return meta
    monkeypatch.setattr('namer.tvmaze.enrich_episode_titles', fake_enrich)
    op = tvmaze_feed({'title': 'Yuru Camp', 'is_series': True, 'year': 2018,
                      'season': 1, 'episode': 1}, 'en')
    assert op.abstain


# ── tmdb feed: vote only when the lookup resolved something ─────────────────

def test_tmdb_feed_abstains_without_key():
    op = tmdb_feed({'title': 'Show', 'is_series': False}, '', 'en')
    assert op.abstain


def test_tmdb_feed_does_not_echo_hint_when_not_resolved(monkeypatch):
    monkeypatch.setattr('namer.enricher.enrich_meta',
                        lambda meta, key, language='en': meta)
    op = tmdb_feed({'title': 'Junk Movie DDP', 'is_series': False}, 'k', 'en')
    assert op.abstain
    assert op.values == {}


def test_tmdb_feed_does_not_echo_hint_when_only_year_resolved(monkeypatch):
    """Finding a year is not title resolution; dirty hints must abstain."""
    def fake_enrich(meta, key, language='en'):
        meta['year'] = 2020
        return meta
    monkeypatch.setattr('namer.enricher.enrich_meta', fake_enrich)
    op = tmdb_feed({'title': 'Movie Name DDP', 'is_series': False}, 'k', 'en')
    assert op.abstain
    assert op.values == {}


def test_tmdb_feed_votes_canonical_when_resolved(monkeypatch):
    def fake_enrich(meta, key, language='en'):
        meta['_tmdb_resolved'] = True
        meta['title'] = 'Iron Man'
        meta['year'] = 2008
        return meta
    monkeypatch.setattr('namer.enricher.enrich_meta', fake_enrich)
    op = tmdb_feed({'title': 'Zheleznyi chelovek', 'year': 2008,
                    'is_series': False}, 'k', 'en')
    assert op.values['title'] == 'Iron Man'
    assert op.values['year'] == 2008


def test_tmdb_feed_abstains_on_year_conflict(monkeypatch):
    def fake_enrich(meta, key, language='en'):
        meta['_tmdb_resolved'] = True
        meta['title'] = 'Some Other Movie'
        meta['year'] = 1999
        return meta
    monkeypatch.setattr('namer.enricher.enrich_meta', fake_enrich)
    op = tmdb_feed({'title': 'Movie Name', 'year': 2020, 'is_series': False},
                   'k', 'en')
    assert op.abstain
