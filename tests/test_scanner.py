"""Tests for namer.scanner."""

import os
import tempfile

from namer.scanner import find_video_files


def test_find_video_files():
    with tempfile.TemporaryDirectory() as tmp:
        # Create test files
        for f in ["movie.mkv", "show.mp4", "clip.avi", "readme.txt"]:
            open(os.path.join(tmp, f), 'w').close()
        os.makedirs(os.path.join(tmp, "sub"), exist_ok=True)
        for f in ["sub/movie.mkv", "sub/series.mp4"]:
            open(os.path.join(tmp, f), 'w').close()

        files = find_video_files(tmp, recursive=True)
        assert len(files) == 5  # .mkv x2, .mp4 x2, .avi x1
        assert all(f.endswith(('.mkv', '.mp4', '.avi')) for f in files)
        assert any('sub' in f for f in files)


def test_non_recursive():
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "movie.mkv"), 'w').close()
        os.makedirs(os.path.join(tmp, "sub"), exist_ok=True)
        open(os.path.join(tmp, "sub", "series.mkv"), 'w').close()

        files = find_video_files(tmp, recursive=False)
        assert len(files) == 1
        assert "sub" not in files[0]


def test_skip_hidden():
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, ".hidden"), exist_ok=True)
        open(os.path.join(tmp, ".hidden", "movie.mkv"), 'w').close()
        open(os.path.join(tmp, "visible.mkv"), 'w').close()

        files = find_video_files(tmp, recursive=True)
        assert len(files) == 1
        assert ".hidden" not in files[0]
