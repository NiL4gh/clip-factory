"""
Drive-backed project cache.
Each processed video gets a folder: projects/{video_id}/
Contains metadata, transcript, highlights, and rendered clips.
"""
import json
import os
import re
import hashlib
from datetime import datetime

from .config import PROJECTS_DIR


def _video_id(url: str) -> str:
    """Extract YouTube video ID or hash arbitrary URLs."""
    m = re.search(r'(?:v=|youtu\.be/|/shorts/)([\w-]{11})', url)
    if m:
        return m.group(1)
    return hashlib.md5(url.encode()).hexdigest()[:12]


def project_dir(url: str) -> str:
    vid = _video_id(url)
    d = os.path.join(PROJECTS_DIR, vid)
    os.makedirs(d, exist_ok=True)
    os.makedirs(os.path.join(d, "clips"), exist_ok=True)
    return d


def save_metadata(url: str, title: str = "", duration: float = 0, language: str = ""):
    d = project_dir(url)
    data = {
        "url": url,
        "video_id": _video_id(url),
        "title": title,
        "duration": duration,
        "language": language,
        "processed_at": datetime.now().isoformat(),
    }
    with open(os.path.join(d, "metadata.json"), "w") as f:
        json.dump(data, f, indent=2)
    return data


def save_transcript(url: str, full_text: str, word_timestamps: list):
    d = project_dir(url)
    with open(os.path.join(d, "transcript.json"), "w") as f:
        json.dump({"text": full_text, "words": word_timestamps}, f)


def load_transcript(url: str):
    p = os.path.join(project_dir(url), "transcript.json")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        data = json.load(f)
    return data["text"], data["words"]


def save_highlights(url: str, highlights: list):
    d = project_dir(url)
    with open(os.path.join(d, "highlights.json"), "w") as f:
        json.dump({"highlights": highlights, "saved_at": datetime.now().isoformat()}, f, indent=2)


def load_highlights(url: str):
    p = os.path.join(project_dir(url), "highlights.json")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f).get("highlights", [])


def list_projects() -> list:
    """Return list of previously processed projects with metadata."""
    if not os.path.exists(PROJECTS_DIR):
        return []
    projects = []
    for vid in sorted(os.listdir(PROJECTS_DIR), reverse=True):
        meta_path = os.path.join(PROJECTS_DIR, vid, "metadata.json")
        if os.path.exists(meta_path):
            with open(meta_path) as f:
                projects.append(json.load(f))
    return projects


def get_clips_dir(url: str) -> str:
    return os.path.join(project_dir(url), "clips")
