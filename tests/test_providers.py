"""Tests for provider feed construction (offline, no network)."""

import os

import pytest

from namer.parser import parse_file
from namer.providers import (
    Feed, filename_feed, dirname_feed, file_feed, local_feeds, online_feeds,
)


# ── filename feed ────────────────────────────────────────────────────────────

def test_filename_feed_explicit_series():
    feed = filename_feed('Show.S01E05.1080p.mkv')
    assert feed.provider == 'filename'
    assert feed.values['season'] == 1
    assert feed.values['episode'] == 5
    assert feed.values['title'] == 'Show'
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


def test_filename_feed_known_title_override():
    feed = filename_feed('Show.S01E01.mkv', known_title='My Known Title')
    assert feed.values['title'] == 'My Known Title'


def test_filename_feed_quality_fields():
    feed = filename_feed('Show.S01E01.1080p.BluRay.x264.mkv')
    assert feed.values['resolution'] == '1080p'
    assert feed.values['codec'] == 'x264'


# ── dirname feed ─────────────────────────────────────────────────────────────

def test_dirname_feed_title_and_season(tmp_path):
    show = tmp_path / 'Natsume Yuujinchou S7'
    show.mkdir(parents=True)
    fpath = show / 'Show 01.mkv'
    feed = dirname_feed(str(fpath))
    assert feed.values['season'] == 7
    # The walked title may carry junk above tmp_path; the meaningful part
    # (the show folder) must be present as the tail of the candidate.
    assert feed.values['title'].endswith('Natsume Yuujinchou')


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
