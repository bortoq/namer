"""Single-source weight: matrix base x provider confidence.

Effective name is FIELD_WEIGHT[field][base] * conf.confidence.  Legacy Feed
objects (no confidence) are unaffected (factor 1.0), so the merge cannot
change voting behaviour for confidence-less feeds.
"""

import pytest

from namer.provider_opinion import ProviderOpinion
from namer.voting import _effective_weight, FIELD_WEIGHTS, Feed, vote, MIN_EXPENSIVE_SINGLE_EFFECTIVE
from namer.fusion import fuse


def weight_of(field, provider, confidence):
    op = ProviderOpinion(provider)
    op.set(field, 1, confidence)
    return _effective_weight(op, field, FIELD_WEIGHTS[field])


class TestMergeSemantics:
    def test_base_times_confidence(self):
        # filename season base 4.0 * 0.5 -> 2.0
        assert weight_of('season', 'filename', 0.5) == pytest.approx(2.0)

    def test_higher_confidence_raises_weight(self):
        assert weight_of('season', 'filename', 0.9) > weight_of('season', 'filename', 0.5)

    def test_confidence_decides_base_tie(self):
        # title: filename & dirname both base 1.0 -> confidence is the lever
        assert weight_of('title', 'filename', 0.9) > weight_of('title', 'dirname', 0.4)

    def test_legacy_feed_unaffected(self):
        f = Feed('filename', {'season': 1})
        assert _effective_weight(f, 'season', FIELD_WEIGHTS['season']) == \
            FIELD_WEIGHTS['season']['filename']


class TestMergeNoRegression:
    def test_confidenceless_feeds_vote_as_before(self):
        feeds = [
            Feed('filename', {'season': 1, 'episode': 5}),
            Feed('dirname', {'season': 2}),
        ]
        v = vote(feeds)
        assert v['season'].decision == 'skip'     # real conflict

    def test_confident_consensus_accepted(self):
        a = ProviderOpinion('filename'); a.set('season', 1, 0.95); a.set('episode', 5, 0.95)
        b = ProviderOpinion('dirname');  b.set('season', 1, 0.95); b.set('episode', 5, 0.95)
        v = vote([a, b])
        assert v['season'].decision == 'accept'
        assert v['season'].value == 1


class TestLowConfidenceExpensiveField:
    """Regression for audit 943-001.

    A lone low/zero-confidence vote on an expensive field (season/episode)
    must not be accepted as a safe rename input, and fuse() must not report a
    posterior of 1.0 for such a candidate.
    """

    @pytest.mark.parametrize('conf', [0.0, 0.01, 0.1])
    def test_low_confidence_expensive_field_is_not_accepted(self, conf):
        op = ProviderOpinion('filename')
        op.set('season', 1, conf)
        v = vote([op])['season']
        assert v.decision == 'skip'
        assert not v.usable

    @pytest.mark.parametrize('conf', [0.0, 0.01, 0.1])
    def test_low_confidence_episode_not_accepted(self, conf):
        op = ProviderOpinion('filename')
        op.set('episode', 1, conf)
        v = vote([op])['episode']
        assert v.decision == 'skip'
        assert not v.usable

    def test_high_confidence_expensive_accepted(self):
        op = ProviderOpinion('filename')
        op.set('season', 1, 0.9)
        v = vote([op])['season']
        assert v.decision == 'accept'
        assert v.usable

    def test_fuse_single_low_confidence_not_posterior_one(self):
        op = ProviderOpinion('filename')
        op.set('season', 1, 0.01)
        v = fuse([op])['season']
        assert v.confidence < 0.5
        assert not v.usable

    def test_fuse_confident_consensus_high_posterior(self):
        a = ProviderOpinion('filename'); a.set('season', 1, 0.95); a.set('episode', 5, 0.95)
        b = ProviderOpinion('dirname');  b.set('season', 1, 0.95); b.set('episode', 5, 0.95)
        v = fuse([a, b])
        assert v['season'].decision == 'accept'
        assert v['season'].confidence > 0.7


class TestExpensiveEffectiveFloor:
    """Regression for audit 157-001: the lone expensive-field gate must be
    the *effective* weight (base x confidence), never confidence alone, so a
    base-1.0 provider cannot single-handedly accept a season/episode."""

    @pytest.mark.parametrize('provider', ['file', 'unknown'])
    def test_lone_low_base_expensive_below_floor_skipped(self, provider):
        op = ProviderOpinion(provider)
        op.set('season', 7, 0.95)
        assert _effective_weight(op, 'season', FIELD_WEIGHTS['season']) \
            < MIN_EXPENSIVE_SINGLE_EFFECTIVE
        v = vote([op])['season']
        assert v.decision == 'skip'
        assert not v.usable

    def test_lone_confident_filename_still_accepted(self):
        op = ProviderOpinion('filename')
        op.set('season', 7, 0.95)
        v = vote([op])['season']
        assert v.decision == 'accept'
        assert v.usable

    def test_lone_explicit_dirname_accepted(self):
        # dirname base 2.0 x 0.8 -> 1.6 >= floor
        op = ProviderOpinion('dirname')
        op.set('season', 7, 0.8)
        v = vote([op])['season']
        assert v.decision == 'accept'


class TestConfidenceValidation:
    """Regression for audit 157-002: confidence is a probability in [0, 1]."""

    @pytest.mark.parametrize('conf', [-0.1, 1.1, 2.0, 99])
    def test_provider_confidence_must_be_0_to_1(self, conf):
        op = ProviderOpinion('filename')
        with pytest.raises(ValueError):
            op.set('season', 1, conf)

    def test_fuse_confidence_stays_in_unit_interval(self):
        a = ProviderOpinion('filename'); a.set('season', 1, 0.9)
        b = ProviderOpinion('dirname');  b.set('season', 1, 0.8)
        v = fuse([a, b])['season']
        assert 0.0 <= v.confidence <= 1.0
