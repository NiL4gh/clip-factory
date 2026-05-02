import os
from .downloader import download_video
from .transcriber import transcribe_audio
from .highlights import get_highlights


class OpusPipeline:
    def __init__(self, work_dir: str):
        self.work_dir = work_dir
        os.makedirs(work_dir, exist_ok=True)
        self.current_video_url = None
        self.full_text = ""
        self.word_timestamps = []
        self.clips = []

    def process_new_video(
        self,
        url: str,
        num_clips: int = 3,
        llm_path: str = "",
        gpu_layers: int = 35,
        whisper_size: str = "medium",
        whisper_dir: str = "/tmp/whisper",
        cookie_path: str = None,
    ):
        """Returns (clips_list, status_message)."""
        source_path = os.path.join(self.work_dir, "source.mp4")

        # Skip re-download if same URL and file already exists
        if url == self.current_video_url and os.path.exists(source_path):
            return self.clips, self.word_timestamps, "✅ Using cached session data."

        self.current_video_url = url

        # 1. Download
        download_video(url, self.work_dir, cookie_path=cookie_path)

        # 2. Transcribe — returns (full_text, word_timestamps)
        self.full_text, self.word_timestamps = transcribe_audio(
            source_path,
            model_size=whisper_size,
            whisper_dir=whisper_dir,
        )

        # 3. Highlight detection
        result = get_highlights(
            self.full_text,
            num_clips=num_clips,
            llm_path=llm_path,
            gpu_layers=gpu_layers,
        )
        self.clips = result.get("highlights", [])

        return self.clips, self.word_timestamps, f"✅ Found {len(self.clips)} viral clips."
