"""videolib — standalone video identification library.

Public API:

    identify_video(path, *, title="", allow_online=True) -> dict
        Determine what a file is with as much information as available
        (filename, directories, embedded tags, and online databases when
        allow_online is True).  Language-neutral: returns the title and
        episode title as-is, not localized.

    get_video_info(path, *, language="en") -> dict
        identify_video(path) then localize the title / episode title to
        the requested language via Wikipedia and online metadata providers.
"""

from videolib.identify import identify_video, get_video_info

__all__ = ["identify_video", "get_video_info"]
__version__ = "0.1.0"
