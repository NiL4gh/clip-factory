"""
Drive-backed project cache.
Each processed video gets a folder: projects/{readable_name}/
Contains metadata, transcript, highlights, and rendered clips.
"""
import json
import os
import re
import hashlib
from datetime import datetime

from .config import PROJECTS_DIR


def video_id(url: str) -> str:
    """The single, readable storage key for a video, used by projects/, output/,
    and sessions/ alike. Returns the YouTube id (e.g. ru44DngJYoA); for non-YouTube
    URLs, a short hash. Keeping one scheme everywhere is what makes Drive navigable."""
    m = re.search(r'(?:v=|youtu\.be/|/shorts/)([\w-]{11})', url)
    if m:
        return m.group(1)
    return hashlib.md5(url.encode()).hexdigest()[:12]


# Backwards-compatible alias (older internal callers used the underscore name).
_video_id = video_id


def _index_path() -> str:
    return os.path.join(PROJECTS_DIR, "_index.json")


def _read_index() -> dict:
    p = _index_path()
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _write_index(data: dict):
    os.makedirs(PROJECTS_DIR, exist_ok=True)
    with open(_index_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _make_readable_name(title: str, vid: str) -> str:
    """Build a human-readable folder name: sanitized title + video id."""
    safe = re.sub(r'[^\w\s\-]', '', title, flags=re.UNICODE)
    safe = re.sub(r'\s+', ' ', safe).strip()[:40]
    return f"{safe} ({vid})" if safe else vid


def project_dir(url: str, title: str = "") -> str:
    """Return (creating if needed) the project folder for this video.
    Uses a human-readable name when title is known, with an index for lookups."""
    vid = _video_id(url)
    index = _read_index()

    if vid in index:
        folder_name = index[vid]
    elif title:
        folder_name = _make_readable_name(title, vid)
        index[vid] = folder_name
        _write_index(index)
    else:
        # No title yet — check if any existing folder has a video_id.txt match
        # or just fall back to the bare video_id (backwards-compatible)
        folder_name = vid

    d = os.path.join(PROJECTS_DIR, folder_name)
    os.makedirs(d, exist_ok=True)
    os.makedirs(os.path.join(d, "clips"), exist_ok=True)
    return d


def save_metadata(url: str, title: str = "", duration: float = 0, language: str = ""):
    # Register the readable folder name on first call with a real title
    d = project_dir(url, title=title)
    data = {
        "url": url,
        "video_id": _video_id(url),
        "title": title,
        "duration": duration,
        "language": language,
        "processed_at": datetime.now().isoformat(),
    }
    with open(os.path.join(d, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return data


def save_transcript(url: str, full_text: str, word_timestamps: list):
    d = project_dir(url)
    with open(os.path.join(d, "transcript.json"), "w", encoding="utf-8") as f:
        json.dump({"text": full_text, "words": word_timestamps}, f)


def load_transcript(url: str):
    p = os.path.join(project_dir(url), "transcript.json")
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["text"], data["words"]


def save_highlights(url: str, highlights: list):
    d = project_dir(url)
    with open(os.path.join(d, "highlights.json"), "w", encoding="utf-8") as f:
        json.dump({"highlights": highlights, "saved_at": datetime.now().isoformat()}, f, indent=2)


def load_highlights(url: str):
    p = os.path.join(project_dir(url), "highlights.json")
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f).get("highlights", [])


def list_projects() -> list:
    """Return list of previously processed projects with metadata."""
    if not os.path.exists(PROJECTS_DIR):
        return []
    projects = []
    for vid in sorted(os.listdir(PROJECTS_DIR), reverse=True):
        meta_path = os.path.join(PROJECTS_DIR, vid, "metadata.json")
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                projects.append(json.load(f))
    return projects


def get_clips_dir(url: str) -> str:
    return os.path.join(project_dir(url), "clips")
