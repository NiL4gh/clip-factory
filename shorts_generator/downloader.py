import yt_dlp
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

    ydl_opts = {
        # Select best video up to 720p (saves bandwidth/time) + best audio, or best available
        "format": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "outtmpl": f"{work_dir}/source.%(ext)s",
        "cookiefile": cookie_path if cookie_path and os.path.exists(cookie_path) else None,
        "quiet": False,
        "ignoreerrors": False,
        "socket_timeout": 60,
        "merge_output_format": "mp4",
        "postprocessors": [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}],
        "extractor_args": {"youtube": ["player_client=ios,android"]},
    }

    ui_logger.log("yt-dlp: Fetching remote components and downloading...")
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        ui_logger.log(f"yt-dlp failed: {e}")
        raise

    # Fast remux fallback — no re-encoding
    if not os.path.exists(output_mp4):
        files = glob.glob(f"{work_dir}/source.*")
        if files:
            raw = files[0]
            ui_logger.log("Fast remuxing raw file to mp4 format...")
            subprocess.run(["ffmpeg", "-y", "-i", raw, "-c", "copy", output_mp4], check=True)
            if raw != output_mp4:
                os.remove(raw)

    ui_logger.log("Download complete.")
    return output_mp4
