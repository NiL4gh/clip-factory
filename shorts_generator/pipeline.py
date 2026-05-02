# shorts_generator/pipeline.py
import os
from .downloader import download_video
from .transcriber import transcribe_audio
from .highlights import get_highlights

# Alias so any legacy callers using get_viral_clips still work
get_viral_clips = get_highlights


class OpusPipeline:
    def __init__(self, work_dir):
        self.work_dir = work_dir
        os.makedirs(work_dir, exist_ok=True)
        self.current_video_url = None
        self.transcript = None
        self.clips = []

    def process_new_video(self, url, num_clips=3):
        """Returns (clips_list, status_message)."""
        source_path = os.path.join(self.work_dir, "source.mp4")

        # Skip re-download if same URL and file exists
        if url == self.current_video_url and os.path.exists(source_path):
            return self.clips, "✅ Using cached session data."

        self.current_video_url = url

        # 1. Download
        download_video(url, self.work_dir)

        # 2. Transcribe
        self.transcript = transcribe_audio(source_path)

        # 3. Analyse — get_highlights returns {"highlights": [...]}
        result = get_highlights(self.transcript, num_clips=num_clips)
        self.clips = result.get("highlights", [])

        return self.clips, f"✅ Found {len(self.clips)} viral clips."
