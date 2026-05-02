import os
from .downloader import download_video
from .transcriber import transcribe_audio
from .highlights import get_viral_clips

class OpusPipeline:
    def __init__(self, work_dir):
        self.work_dir = work_dir
        self.current_video_url = None
        self.transcript = None
        self.clips = []

    def process_new_video(self, url, llm_path, gpu_layers, whisper_model):
        # 1. Intelligent Skip: Don't re-download if it's the same URL
        if url == self.current_video_url and os.path.exists(f"{self.work_dir}/source.mp4"):
            return self.clips, "✅ Using cached data from current session."

        self.current_video_url = url
        
        # 2. Download
        download_video(url, self.work_dir)
        
        # 3. Transcribe (Logic should be in your transcriber.py)
        self.transcript, _ = transcribe_audio(f"{self.work_dir}/source.mp4", whisper_model)
        
        # 4. Analyze
        self.clips = get_viral_clips(self.transcript, llm_path, gpu_layers)
        
        return self.clips, "✅ Analysis Complete."
