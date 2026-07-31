"""Unit tests for the consensus voting engine."""

import pytest

import namer.voting as voting
from namer.voting import Feed, vote, update_scores, usable_values


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No QID lookups / no network in these tests."""
    monkeypatch.setattr(voting, 'QID_LOOKUP_ENABLED', False)
    monkeypatch.setattr(voting, 'get_entity_qid', lambda *a, **k: None)


def test_all_agree_season_episode_accepted():
    feeds = [
        Feed('filename', {'season': 1, 'episode': 5}),
        Feed('dirname', {'season': 1, 'episode': 5}),
    ]
    v = vote(feeds)
    assert v['season'].decision == 'accept'
    assert v['season'].value == 1
    assert v['episode'].decision == 'accept'
    assert v['season'].confidence == 1.0


def test_expensive_conflict_skips():
    """Explicit S01 filename vs explicit dirname S2 → refuse (skip)."""
    feeds = [
        Feed('filename', {'season': 1, 'episode': 5}),
        Feed('dirname', {'season': 2}),
    ]
    v = vote(feeds)
    assert v['season'].decision == 'skip'
    assert not v['season'].usable
    assert v['episode'].decision == 'accept'


def test_weak_assumed_yields_to_explicit():
    """Assumed filename season must not outvote an explicit dirname season."""
    feeds = [
        Feed('filename', {'season': 1, 'episode': 5, 'season_assumed': True}),
        Feed('dirname', {'season': 7}),
    ]
    v = vote(feeds)
    assert v['season'].decision == 'accept'
    assert v['season'].value == 7


def test_weak_assumed_alone_accepted():
    feeds = [Feed('filename', {'season': 1, 'episode': 5, 'season_assumed': True})]
    v = vote(feeds)
    assert v['season'].decision == 'accept'
    assert v['season'].value == 1


def test_placeholder_title_loses_tie():
    """A real title beats a numbered placeholder on an equal-score tie."""
    feeds = [
        Feed('wikipedia', {'ep_title': 'Mount Fuji and Curry Noodles'}),
        Feed('tvmaze', {'ep_title': 'Episode 1'}),
    ]
    v = vote(feeds)
    assert v['ep_title'].value == 'Mount Fuji and Curry Noodles'
    assert v['ep_title'].decision == 'accept'


def test_title_value_from_highest_priority_member():
    """Inside one agreeing cluster the wikipedia spelling wins."""
    feeds = [
        Feed('filename', {'title': 'Attack on Titan Final Season'}),
        Feed('wikipedia', {'title': 'Attack on Titan'}),
    ]
    v = vote(feeds)
    assert 'filename' in v['title'].providers  # same cluster (containment)
    assert v['title'].value == 'Attack on Titan'  # weight 5 > 1


def test_title_containment_agreement():
    """Directory title that is a subset of the filename title agrees,
    and the cleaner (shorter) value wins at equal weight."""
    feeds = [
        Feed('filename', {'title': 'Attack on Titan Final Season'}),
        Feed('dirname', {'title': 'Attack on Titan'}),
    ]
    v = vote(feeds)
    assert len(v['title'].providers) == 2
    assert v['title'].value == 'Attack on Titan'


def test_title_disagreement_filename_boost():
    """Filename title wins an exact-score tie (identity source)."""
    feeds = [
        Feed('filename', {'title': 'Show'}),
        Feed('dirname', {'title': 'work namer'}),
    ]
    v = vote(feeds)
    assert v['title'].value == 'Show'


def test_cheap_field_single_voter_accepted():
    """A lone cheap-field vote with no opposition is accepted (usable)."""
    feeds = [Feed('filename', {'quality': 'BDRip'})]
    v = vote(feeds)
    assert v['quality'].decision == 'accept'
    assert v['quality'].value == 'BDRip'
    assert v['quality'].usable


def test_cheap_field_threeway_tie_is_guess():
    """Three equal online camps on a cheap field → best-effort guess."""
    feeds = [
        Feed('wikipedia', {'ep_title': 'First Name'}),
        Feed('tvmaze', {'ep_title': 'Second Name'}),
        Feed('tmdb', {'ep_title': 'Third Name'}),
    ]
    v = vote(feeds)
    assert v['ep_title'].decision == 'guess'
    assert v['ep_title'].usable


def test_qid_synonyms_agree(monkeypatch):
    monkeypatch.setattr(voting, 'QID_LOOKUP_ENABLED', True)
    monkeypatch.setattr(voting, 'get_entity_qid',
                        lambda s: 'Q1' if 'camp' in s.lower() else None)
    feeds = [
        Feed('filename', {'title': 'Yuru Camp'}),
        Feed('wikipedia', {'title': 'Laid-Back Camp'}),
    ]
    v = vote(feeds)
    assert len(v['title'].providers) == 2
    assert v['title'].value == 'Laid-Back Camp'


def test_numbered_episodes_never_fuzzy_match(monkeypatch):
    monkeypatch.setattr(voting, 'QID_LOOKUP_ENABLED', True)
    monkeypatch.setattr(voting, 'get_entity_qid', lambda s: None)
    feeds = [
        Feed('tvmaze', {'ep_title': 'Episode 1'}),
        Feed('wikipedia', {'ep_title': 'Episode 10'}),
    ]
    v = vote(feeds)
    assert len(v['ep_title'].providers) == 1  # separate clusters, no prefix match


def test_update_scores_tracks_only_multi_voter_fields():
    feeds = [
        Feed('filename', {'season': 1, 'resolution': '1080p'}),
        Feed('dirname', {'season': 1}),
        Feed('file', {'resolution': '2160p'}),
    ]
    v = vote(feeds)
    scores = {}
    update_scores(scores, feeds, v)
    # season: filename + dirname agree → both +1
    assert scores['filename']['season'] == 1.0
    assert scores['dirname']['season'] == 1.0
    # resolution: file (2160p, weight 5) beats filename (1080p, weight 1)
    assert scores['file']['resolution'] == 1.0
    assert scores['filename']['resolution'] == 0.0
    # episode had only one voter (filename) → not tracked at all
    assert 'episode' not in scores['filename']


def test_abstain_feed_ignored():
    feeds = [
        Feed('filename', {'season': 1}),
        Feed('tvmaze', {}, abstain=True),
    ]
    v = vote(feeds)
    assert v['season'].providers == ['filename']


def test_season_assumed_meta_field_not_voted():
    feeds = [Feed('filename', {'season': 1, 'season_assumed': True})]
    v = vote(feeds)
    assert 'season_assumed' not in v


def test_empty_and_none_values_ignored():
    feeds = [
        Feed('filename', {'season': None, 'episode': '', 'title': ''}),
        Feed('dirname', {}),
    ]
    assert vote(feeds) == {}


def test_usable_values_filters():
    feeds = [
        Feed('filename', {'season': 1, 'episode': 5}),
        Feed('dirname', {'season': 2}),
        Feed('file', {'resolution': '1080p'}),
    ]
    v = vote(feeds)
    u = usable_values(v)
    assert 'season' not in u          # skipped
    assert u['episode'] == 5
    assert u['resolution'] == '1080p'
