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

    # Verified working format string — 720p mp4 fallback chain
    # --remote-components ejs:github is MANDATORY: solves YouTube's n-challenge via Deno
    cmd = [
        'yt-dlp',
        '-f', 'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
        '--merge-output-format', 'mp4',
        '-o', output_mp4,
        '--cookies', str(cookie_path),
        '--extractor-args', 'youtube:player_client=web',
        '--remote-components', 'ejs:github',
        '--no-warnings',
        url
    ]

    ui_logger.log(f"Downloading with web client + Deno n-challenge solver (cookies: {cookie_path})...")
    # Get current environment and ensure Deno is in the PATH for this specific subprocess
    env = os.environ.copy()
    env["PATH"] = f"/root/.deno/bin:{env.get('PATH', '')}"
    
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
    except subprocess.CalledProcessError as e:
        ui_logger.log(f"yt-dlp failed: {e.stderr[-600:]}")
        raise RuntimeError(f"yt-dlp failed: {e.stderr[-600:]}")

    ui_logger.log("Download complete.")
    return output_mp4
