import subprocess
import os
import glob
from .logger import ui_logger

def download_video(url, work_dir, cookie_path=None):
    output_mp4 = f"{work_dir}/source.mp4"

    ui_logger.log(f"Starting download for: {url}")
    # Clean old source files to prevent conflicts
    for f in glob.glob(f"{work_dir}/source.*"):
        os.remove(f)

    # Robust format selector — prefers 1080p mp4, falls back progressively
    # bestvideo[ext=mp4]+bestaudio[ext=m4a] is broadly compatible
    FORMAT = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/bestvideo+bestaudio/best[ext=mp4]/best"

    cookie_args = ["--cookies", str(cookie_path)] if cookie_path and os.path.exists(str(cookie_path)) else []

    # Attempt order: android client → ios client → web client (no-cookie fallback)
    attempts = [
        {
            "label": "android client",
            "extra": ["--extractor-args", "youtube:player_client=android", "--extractor-args", "youtube:skip=dash"],
        },
        {
            "label": "ios client",
            "extra": ["--extractor-args", "youtube:player_client=ios"],
        },
        {
            "label": "web client (mweb)",
            "extra": ["--extractor-args", "youtube:player_client=mweb"],
        },
        {
            "label": "best available (no client hint)",
            "extra": [],
        },
    ]

    last_error = ""
    for attempt in attempts:
        ui_logger.log(f"Attempting download with {attempt['label']}...")
        cmd = [
            "yt-dlp",
            "-f", FORMAT,
            "--merge-output-format", "mp4",
            "-o", output_mp4,
            "--no-warnings",
            "--retries", "3",
        ] + cookie_args + attempt["extra"] + [url]

        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            if os.path.exists(output_mp4):
                ui_logger.log(f"Download complete via {attempt['label']}.")
                return output_mp4
        except subprocess.CalledProcessError as e:
            last_error = e.stderr[-600:] if e.stderr else "unknown error"
            ui_logger.log(f"Attempt failed ({attempt['label']}): {last_error[-200:]}")

    ui_logger.log(f"yt-dlp failed all attempts: {last_error}")
    raise RuntimeError(f"yt-dlp failed: {last_error}")
