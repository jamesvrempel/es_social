# Copyright (c) 2026, Enterprise Systems Australia and contributors
# For license information, please see license.txt
"""Parse and validate external video links.

Strict provider allowlist (YouTube, Vimeo). We only ever emit an embed URL we
constructed ourselves from a validated video id, so a post/album can never be
used to inject an arbitrary iframe.
"""

import re

_YOUTUBE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|embed/|shorts/|v/)|youtu\.be/)([A-Za-z0-9_-]{6,})"
)
_VIMEO = re.compile(r"vimeo\.com/(?:video/)?(\d+)")


def parse_video_url(url):
    """Return dict(provider, video_id, embed_url, thumbnail) or None if unsupported."""
    if not url:
        return None
    url = url.strip()

    m = _YOUTUBE.search(url)
    if m:
        vid = m.group(1)
        return {
            "provider": "youtube",
            "video_id": vid,
            "embed_url": "https://www.youtube.com/embed/" + vid,
            "thumbnail": "https://img.youtube.com/vi/" + vid + "/hqdefault.jpg",
        }

    m = _VIMEO.search(url)
    if m:
        vid = m.group(1)
        return {
            "provider": "vimeo",
            "video_id": vid,
            "embed_url": "https://player.vimeo.com/video/" + vid,
            "thumbnail": None,
        }

    return None


def embed_for(url):
    """Just the safe embed URL (or None)."""
    info = parse_video_url(url)
    return info["embed_url"] if info else None
