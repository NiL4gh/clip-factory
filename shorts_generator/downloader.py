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

    cmd = [
        "yt-dlp",
        "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]/bestvideo+bestaudio/best",
        "-o", f"{work_dir}/source.%(ext)s",
        "--merge-output-format", "mp4",
        "--extractor-args", "youtube:player_client=ios,android",
        "--impersonate", "chrome",
        url
    ]


    ui_logger.log("yt-dlp: Fetching remote components and downloading...")
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        ui_logger.log(f"yt-dlp failed: {e.stderr}")
        raise RuntimeError(f"yt-dlp failed: {e.stderr}")

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
