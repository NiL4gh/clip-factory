import os
from .downloader import download_video
from .transcriber import transcribe_audio
from .highlights import get_highlights
from . import cache


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
        num_clips: int = 5,
        llm_path: str = "",
        gpu_layers: int = 35,
        whisper_size: str = "medium",
        whisper_dir: str = "/tmp/whisper",
        cookie_path: str = None,
        language: str = None,
    ):
        """Returns (clips_list, word_timestamps, status_message)."""
        source_path = os.path.join(self.work_dir, "source.mp4")

        # 1. Check Drive cache for transcript
        cached_transcript = cache.load_transcript(url)
        cached_highlights = cache.load_highlights(url)

        if cached_transcript and cached_highlights:
            self.full_text, self.word_timestamps = cached_transcript
            self.clips = cached_highlights
            self.current_video_url = url
            return self.clips, self.word_timestamps, "✅ Loaded from cache (previously processed)."

        # 2. Download video (only if not cached)
        if url != self.current_video_url or not os.path.exists(source_path):
            self.current_video_url = url
            download_video(url, self.work_dir, cookie_path=cookie_path)

        # 3. Transcribe (or use cached transcript)
        if cached_transcript:
            self.full_text, self.word_timestamps = cached_transcript
        else:
            self.full_text, self.word_timestamps = transcribe_audio(
                source_path,
                model_size=whisper_size,
                whisper_dir=whisper_dir,
                language=language,
            )
            cache.save_transcript(url, self.full_text, self.word_timestamps)

        # 4. Highlight detection (always find up to 20)
        if cached_highlights:
            self.clips = cached_highlights
        else:
            result = get_highlights(
                self.full_text,
                num_clips=num_clips,
                llm_path=llm_path,
                gpu_layers=gpu_layers,
                max_clips=20,
                language=language or "",
            )
            self.clips = result.get("highlights", [])
            cache.save_highlights(url, self.clips)

        # 5. Save metadata
        cache.save_metadata(url)

        return self.clips, self.word_timestamps, f"✅ Found {len(self.clips)} viral clips."
