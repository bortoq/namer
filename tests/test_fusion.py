"""Tests for Bayesian fusion (namer/fusion).

Two contracts:
  1. fuse() is a drop-in replacement for vote() — same {field: Verdict} keys,
     same winner value and decision, on a broad corpus (equivalence harness).
  2. fuse() reports a posterior confidence that moves sensibly with consensus
     vs conflict.
"""

import pytest

from namer.provider_opinion import ProviderOpinion
from namer.voting import vote
from namer.fusion import fuse


def op(provider, **fields):
    o = ProviderOpinion(provider)
    for k, v in fields.items():
        if isinstance(v, bool):
            o.meta[k] = v
        else:
            o.set(k, v)
    return o


CORPUS = [
    # explicit series — all agree
    [op('filename', season=1, episode=5),
     op('dirname', season=1, episode=5)],
    # expensive conflict → skip
    [op('filename', season=1, episode=5), op('dirname', season=2)],
    # assumed yields to explicit
    [op('filename', season=1, episode=5, season_assumed=True),
     op('dirname', season=7)],
    # assumed alone accepted
    [op('filename', season=1, episode=5, season_assumed=True)],
    # cheap field + lone vote
    [op('filename', quality='BDRip')],
    # real title beats placeholder
    [op('wikipedia', ep_title='Mount Fuji and Curry Noodles'),
     op('tvmaze', ep_title='Episode 1')],
    # containment: dir inside filename title
    [op('filename', title='Attack on Titan Final Season'),
     op('dirname', title='Attack on Titan')],
    # quality field 3-way cheap guess
    [op('wikipedia', ep_title='First'),
     op('tvmaze', ep_title='Second'),
     op('tmdb', ep_title='Third')],
    # resolution: file (high weight) beats filename
    [op('filename', resolution='1080p'),
     op('file', resolution='2160p')],
    # abstain ignored
    [op('filename', season=1), ProviderOpinion('tvmaze', {}, abstain=True)],
]


def test_dropin_equivalence():
    """fuse() and vote() must agree on winner value + decision per field."""
    for feeds in CORPUS:
        v_vote = vote(list(feeds))
        v_fuse = fuse(list(feeds))
        assert set(v_vote.keys()) == set(v_fuse.keys()), feeds
        for field in v_vote:
            assert v_fuse[field].value == v_vote[field].value, (feeds, field)
            assert v_fuse[field].decision == v_vote[field].decision, (feeds, field)
            assert list(v_fuse[field].providers) == list(v_vote[field].providers), (feeds, field)


def test_consensus_posterior_near_one():
    feeds = [op('filename', season=1, episode=5),
             op('dirname', season=1, episode=5)]
    v = fuse(feeds)
    assert v['season'].confidence > 0.7
    assert v['season'].decision == 'accept'


def test_conflict_posterior_drops():
    strong = [op('filename', season=1), op('dirname', season=1), op('file', season='other')]
    noisy = [op('filename', season=1), op('dirname', season=2)]
    c_strong = fuse(strong)['season'].confidence
    c_noisy = fuse(noisy)['season'].confidence
    assert c_strong > c_noisy


def test_conflict_is_skip_not_accept():
    feeds = [op('filename', season=1, episode=5), op('dirname', season=2)]
    v = fuse(feeds)
    assert v['season'].decision == 'skip'
    assert not v['season'].usable


def test_lone_expensive_strong_source_accepted():
    feeds = [op('filename', season=1, episode=5)]
    v = fuse(feeds)
    assert v['season'].decision == 'accept'
    assert v['episode'].decision == 'accept'
