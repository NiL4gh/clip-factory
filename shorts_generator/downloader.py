import subprocess
import os
import glob
import typing
from .logger import ui_logger

def download_video(url, work_dir, cookie_path=None):
    output_mp4 = f"{work_dir}/source.mp4"

    ui_logger.log(f"Starting download for: {url}")
    # Clean old source files to prevent conflicts
    for f in glob.glob(f"{work_dir}/source.*"):
        os.remove(f)

    # --remote-components ejs:github is MANDATORY: solves YouTube's n-challenge via Deno
    # Format strategy: force adaptive streams only (bestvideo+bestaudio — no combined/pre-muxed
    # fallback, which YouTube serves at 360p). Use --remux-video mp4 NOT --merge-output-format mp4:
    # the latter biases yt-dlp toward H264 streams that fit natively in mp4, skipping VP9 entirely.
    # --remux-video lets yt-dlp pick the best quality freely and re-wraps to mp4 afterward.
    cmd = [
        'yt-dlp',
        '-f', 'bestvideo[height<=1080]+bestaudio',
        '-S', 'res:1080,fps,codec:vp9',
        '--remux-video', 'mp4',
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
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
        # Log format selection so we can confirm which stream yt-dlp actually picked
        if result.stderr:
            for line in result.stderr.strip().splitlines():
                if any(k in line.lower() for k in ["warning", "fallback", "unavailable", "skipping",
                                                     "downloading 1 format", "merger", "[info]"]):
                    ui_logger.log(f"yt-dlp: {line.strip()}")
        if result.stdout:
            for line in result.stdout.strip().splitlines():
                if any(k in line.lower() for k in ["format", "merger", "destination", "downloading 1"]):
                    ui_logger.log(f"yt-dlp: {line.strip()}")
    except subprocess.CalledProcessError as e:
        stderr_str = e.stderr or ""
        ui_logger.log(f"yt-dlp failed: {stderr_str[-600:]}")
        if any(sig in stderr_str.lower() for sig in ["sign in", "confirm your age", "cookies", "login"]):
            ui_logger.error("⚠️ cookies.txt may be expired. Re-export from browser.")
        raise RuntimeError(f"yt-dlp failed: {stderr_str[-600:]}")

    ui_logger.log("Download complete.")

    # Diagnostic: log source format so we can diagnose quality issues
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,codec_name,bit_rate,r_frame_rate",
             "-of", "default=noprint_wrappers=1", output_mp4],
            capture_output=True, text=True, timeout=15
        )
        if probe.stdout.strip():
            ui_logger.log(f"📐 Source video: {probe.stdout.strip().replace(chr(10), ' | ')}")
            # Warn if source is below 720p — output clips will have visible quality issues
            for line in probe.stdout.strip().splitlines():
                if line.startswith("height="):
                    h = int(line.split("=")[1])
                    if h < 720:
                        ui_logger.error(f"⚠️ Source video is only {h}p — clips will look poor. Use a 1080p video for best results.")
                    break
    except Exception:
        pass

    return output_mp4

def get_video_title(url: str, cookie_path: str = None) -> str:
    """Return the video title from yt-dlp without downloading. Empty string on failure."""
    cmd = [
        'yt-dlp', '--print', 'title', '--skip-download', '--no-warnings',
        '--extractor-args', 'youtube:player_client=web',
        '--remote-components', 'ejs:github',
    ]
    if cookie_path and os.path.exists(cookie_path):
        cmd += ['--cookies', str(cookie_path)]
    cmd.append(url)
    env = os.environ.copy()
    env["PATH"] = f"/root/.deno/bin:{env.get('PATH', '')}"
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        title = result.stdout.strip()
        if not title:
            ui_logger.log("⚠️ Could not fetch video title from yt-dlp — log folder will be unnamed.")
        return title
    except Exception as e:
        ui_logger.log(f"⚠️ get_video_title failed: {e}")
        return ""


def download_srt(video_url: str, output_dir: str, video_id: str) -> typing.Optional[str]:
    try:
        from shorts_generator.config import BASE_DIR
        cookie_path = os.path.join(BASE_DIR, "cookies.txt")
        
        # Build yt-dlp command to download auto-generated English SRT subtitles
        cmd = [
            'yt-dlp',
            '--write-auto-sub',
            '--sub-lang', 'en',
            '--convert-subs', 'srt',
            '--skip-download',
            '--no-warnings',
            '--cookies', str(cookie_path),
            '-o', f"{output_dir}/{video_id}.%(ext)s",
            video_url
        ]
        
        # Run the command with a 30 second timeout
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
        
        # Search for first matching file matching the pattern output_dir/video_id*.srt
        pattern = os.path.join(output_dir, f"{video_id}*.srt")
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
            
        return None
    except Exception as e:
        ui_logger.log(f"Warning: download_srt failed: {e}")
        return None

