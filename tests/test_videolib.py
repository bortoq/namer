"""Unit tests for the standalone videolib.

identify_video must work fully offline and be language-neutral;
get_video_info adds localization.  Offline asserts must not hit the network.
"""
import os
import tempfile

import pytest

from videolib import identify_video, get_video_info


def test_identify_video_offline_clean_name(tmp_path):
    p = os.path.join(tmp_path, "Show", "S01E01.mkv")
    os.makedirs(os.path.dirname(p))
    open(p, 'w').close()
    info = identify_video(p, allow_online=False)
    assert info['is_series'] is True
    assert info['season'] == 1
    assert info['episode'] == 1
    assert info['ext'] == 'mkv'


def test_identify_video_uses_dir_title_when_filename_has_no_show():
    with tempfile.TemporaryDirectory() as d:
        show_dir = os.path.join(d, "Breaking Bad")
        os.makedirs(show_dir)
        f = os.path.join(show_dir, "S01E01.avi")
        open(f, 'w').close()
        info = identify_video(f, allow_online=False)
        assert info["title"] == "Breaking Bad"


def test_identify_video_explicit_title_wins():
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "somefile.mkv")
        open(f, 'w').close()
        info = identify_video(f, title="Explicit Title", allow_online=False)
        assert info["title"] == "Explicit Title"


def test_identify_video_ep_title_from_filename():
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "01.01. Pilot.mkv")
        open(f, 'w').close()
        info = identify_video(f, allow_online=False)
        assert info["ep_title"] == "Pilot"


def test_get_video_info_returns_same_shape():
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "Some.Show.S01E01.mkv")
        open(f, 'w').close()
        info = get_video_info(f, language="en")
        assert "title" in info
        assert "dot_title" in info
        assert "season" in info
        assert "episode" in info
