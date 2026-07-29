"""Recursive file scanner for video files."""

import os
from typing import List

from namer.settings import VIDEO_EXTENSIONS


def _skip_dir(name: str) -> bool:
    """Skip hidden directories, __pycache__, etc."""
    return name.startswith('.') or name == '__pycache__'


def find_video_files(directory: str, recursive: bool = True) -> List[str]:
    """Walk *directory* and return paths to all video files.

    Args:
        directory: Root directory to scan.
        recursive: If True, descend into subdirectories.

    Returns:
        List of relative (if subdir) file paths.
    """
    files: List[str] = []
    if not os.path.isdir(directory):
        return files

    if recursive:
        for root, dirs, names in os.walk(directory):
            # Filter hidden dirs in-place
            dirs[:] = [d for d in dirs if not _skip_dir(d)]
            for name in names:
                ext = os.path.splitext(name)[1].lower()
                if ext in VIDEO_EXTENSIONS:
                    files.append(os.path.join(root, name))
    else:
        for name in os.listdir(directory):
            fpath = os.path.join(directory, name)
            if os.path.isfile(fpath):
                ext = os.path.splitext(name)[1].lower()
                if ext in VIDEO_EXTENSIONS:
                    files.append(fpath)

    return sorted(files)
