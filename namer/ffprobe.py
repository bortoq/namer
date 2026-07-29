"""Extract video/audio/subtitle stream metadata via ffprobe.

Uses ``ffprobe -v quiet -print_format json -show_streams <file>``.

All functions gracefully return empty/zero values if ffprobe is not
installed or the file cannot be probed.
"""

import json
import subprocess
import sys
from typing import Dict, List, Optional


def probe_file(file_path: str) -> Optional[Dict]:
    """Run ffprobe on *file_path* and return the parsed JSON output.

    Returns None if ffprobe is unavailable or the call fails.
    """
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json',
             '-show_streams', '-show_format', file_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return None



def get_format_metadata(file_path: str) -> Dict:
    """Extract format-level metadata tags from the media file.

    MKV/MP4 files often carry tags like ``title``, ``show_name``,
    ``season_number``, ``episode_sort``, etc.  Returns a dict with
    recognised keys, all values are empty strings by default::

        {
            'show_name': '',       # MKV "show_name" or "WM/ShowName"
            'ep_title': '',        # MKV "title" or "WM/Title"
            'season': 0,           # "season_number", "WM/SeasonNumber"
            'episode': 0,          # "episode_sort", "episode_number",
                                   #   "WM/EpisodeNumber"
        }
    """
    result = {'show_name': '', 'ep_title': '', 'season': 0, 'episode': 0}
    probe = probe_file(file_path)
    if not probe:
        return result

    tags = probe.get('format', {}).get('tags', {})
    if not tags:
        return result

    # Normalised tag map: common tag names → result key
    tag_map = {
        'show_name': 'show_name',
        'series_name': 'show_name',
        'WM/ShowName': 'show_name',
        'title': 'ep_title',
        'WM/Title': 'ep_title',
        'season_number': 'season',
        'season': 'season',
        'WM/SeasonNumber': 'season',
        'episode_sort': 'episode',
        'episode_number': 'episode',
        'episode': 'episode',
        'WM/EpisodeNumber': 'episode',
    }

    for tag_key, tag_val in tags.items():
        if not isinstance(tag_val, str):
            continue
        tag_val = tag_val.strip()
        if not tag_val:
            continue
        target = tag_map.get(tag_key)
        if target == 'show_name' and not result['show_name']:
            result['show_name'] = tag_val
        elif target == 'ep_title' and not result['ep_title']:
            result['ep_title'] = tag_val
        elif target == 'season' and not result['season']:
            try:
                result['season'] = int(tag_val)
            except ValueError:
                pass
        elif target == 'episode' and not result['episode']:
            try:
                result['episode'] = int(tag_val)
            except ValueError:
                pass

    return result

def _streams_by_type(probe: Dict, codec_type: str) -> List[Dict]:
    """Return all streams of *codec_type* (video/audio/subtitle)."""
    return [s for s in probe.get('streams', []) if s.get('codec_type') == codec_type]


def get_video_info(file_path: str) -> Dict:
    """Extract video-stream metadata.

    Returns::
        {
            'codec': 'h264' | 'hevc' | 'av1' | ...,
            'resolution': 1080 | 2160 | ...,
            'hdr': 'HDR10' | 'Dolby Vision' | '' ,
            'bitrate': 0,          # kb/s, 0 if unknown
        }
    """
    info = {'codec': '', 'resolution': 0, 'hdr': '', 'bitrate': 0}
    probe = probe_file(file_path)
    if not probe:
        return info

    streams = _streams_by_type(probe, 'video')
    if not streams:
        return info

    s = streams[0]  # primary video stream
    codec = (s.get('codec_name') or '').lower()
    # Normalise codec names
    CODEC_MAP = {
        'h264': 'x264', 'h.264': 'x264', 'avc': 'x264',
        'h265': 'HEVC', 'h.265': 'HEVC', 'hevc': 'HEVC',
        'av1': 'AV1', 'vp9': 'VP9',
        'mpeg4': 'XviD', 'mpeg2video': 'MPEG-2',
        'vc1': 'VC-1',
    }
    info['codec'] = CODEC_MAP.get(codec, codec.upper())

    # Resolution — use height (closest to convention: 1080, 720, ...)
    height = s.get('height', 0) or s.get('coded_height', 0)
    if height:
        # Round to nearest standard resolution
        for std in (2160, 1080, 720, 576, 480, 360):
            if abs(height - std) <= 144:  # tolerance for e.g. 1072→1080, 792→720
                info['resolution'] = std
                break
        else:
            info['resolution'] = height

    # HDR — check side_data or pix_fmt
    pix_fmt = (s.get('pix_fmt') or '').lower()
    side_data = [sd.get('type', '') for sd in s.get('side_data_list', [])]
    if 'Dolby Vision' in side_data or ('dovi' in pix_fmt or 'dolbyvision' in pix_fmt):
        info['hdr'] = 'Dolby Vision'
    elif 'HDR10+' in side_data:
        info['hdr'] = 'HDR10+'
    elif 'HDR10' in side_data or 'smpte2084' in s.get('color_transfer', ''):
        info['hdr'] = 'HDR10'
    elif 'HLG' in side_data or arib_hlg(s.get('color_transfer', '')):
        info['hdr'] = 'HLG'

    # Bitrate
    bitrate = s.get('bit_rate', '') or ''
    if bitrate.isdigit():
        info['bitrate'] = int(bitrate) // 1000

    return info


def arib_hlg(transfer: str) -> bool:
    """Check if colour-transfer characteristic indicates HLG."""
    return transfer in ('arib-std-b67', 'bt2020-10', 'bt2020-12')


def get_audio_info(file_path: str) -> List[Dict]:
    """Extract audio-stream metadata.

    Returns a list (one entry per stream)::
        [
            {'codec': 'aac', 'language': 'jpn', 'channels': 2},
            ...
        ]
    """
    probe = probe_file(file_path)
    if not probe:
        return []

    streams = _streams_by_type(probe, 'audio')
    result = []
    for s in streams:
        codec = (s.get('codec_name') or '').lower()
        lang = s.get('tags', {}).get('language', 'und')
        ch = s.get('channels', 0) or 0
        result.append({'codec': codec, 'language': lang, 'channels': ch})
    return result


def get_subtitle_info(file_path: str) -> List[Dict]:
    """Extract subtitle-stream metadata.

    Returns a list (one entry per stream)::
        [
            {'language': 'eng', 'codec': 'subrip'},
            ...
        ]
    """
    probe = probe_file(file_path)
    if not probe:
        return []

    streams = _streams_by_type(probe, 'subtitle')
    result = []
    for s in streams:
        codec = (s.get('codec_name') or '').lower()
        lang = s.get('tags', {}).get('language', 'und')
        result.append({'language': lang, 'codec': codec})
    return result


def enrich_from_file(file_path: str) -> Dict:
    """Run all ffprobe probes and return a flat dict for merging into meta.

    Returns::
        {
            'codec': 'x264',
            'resolution': 1080,
            'hdr': '',
            'source': '',           # ffprobe cannot determine source type
            'audio': 'aac',         # primary audio codec
            'audio_lang': 'jpn',    # comma-separated unique audio languages
            'sub_lang': 'eng',      # comma-separated unique subtitle languages
            'channels': 6,          # max channels across audio streams
        }
    """
    result = {
        'codec': '',
        'resolution': 0,
        'hdr': '',
        'source': '',
        'audio': '',
        'audio_lang': '',
        'sub_lang': '',
        'channels': 0,
    }

    # Video
    vinfo = get_video_info(file_path)
    result['codec'] = vinfo.get('codec', '')
    result['resolution'] = vinfo.get('resolution', 0)
    result['hdr'] = vinfo.get('hdr', '')

    # Audio
    ainfo = get_audio_info(file_path)
    if ainfo:
        # Use the first audio stream as the primary codec label
        primary_codec = ainfo[0].get('codec', '')
        CODEC_LABEL = {
            'aac': 'AAC', 'ac3': 'AC3', 'eac3': 'E-AC3',
            'dts': 'DTS', 'truehd': 'TrueHD', 'flac': 'FLAC',
            'mp3': 'MP3', 'opus': 'Opus', 'pcm_s16le': 'PCM',
            'vorbis': 'Vorbis',
        }
        result['audio'] = CODEC_LABEL.get(primary_codec, primary_codec.upper())

        # Languages (unique, comma-separated)
        langs = sorted(set(s['language'] for s in ainfo if s['language'] != 'und'))
        if langs:
            result['audio_lang'] = ','.join(langs)

        # Max channels
        result['channels'] = max(s['channels'] for s in ainfo) if ainfo else 0

    # Subtitles
    sinfo = get_subtitle_info(file_path)
    if sinfo:
        langs = sorted(set(s['language'] for s in sinfo if s['language'] != 'und'))
        if langs:
            result['sub_lang'] = ','.join(langs)

    return result
