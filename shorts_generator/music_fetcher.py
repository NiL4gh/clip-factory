"""
LLM-Driven Music Fetcher — Downloads no-copyright background music from YouTube
using yt-dlp based on LLM-generated search queries.

Uses the same Deno JS solver PATH fix as the video downloader.
"""
import subprocess
import os
from .logger import ui_logger


def fetch_music(music_query: str, output_path: str) -> str:
    """
    Downloads a no-copyright background music track from YouTube using yt-dlp.

    Args:
        music_query: A 3-4 word search term (e.g., "upbeat phonk", "calm lofi")
        output_path: Full path for the output mp3 file

    Returns:
        Path to the downloaded mp3 on success, empty string on failure.
        Never raises — graceful degradation so clip renders without music.
    """
    if not music_query or not music_query.strip():
        return ""

    # Clean any existing file to prevent conflicts
    if os.path.exists(output_path):
        os.remove(output_path)

    search_term = f"ytsearch1:{music_query.strip()} no copyright"

    cmd = [
        "yt-dlp",
        search_term,
        "-x",
        "--audio-format", "mp3",
        "--remote-components", "ejs:github",
        "--extractor-args", "youtube:player_client=web",
        "--no-warnings",
        "--max-downloads", "1",
        "-o", output_path,
    ]

    # Get current environment and ensure Deno is in the PATH
    env = os.environ.copy()
    env["PATH"] = f"/root/.deno/bin:{env.get('PATH', '')}"

    ui_logger.log(f"  Searching YouTube for BGM: '{music_query}'...")

    try:
        result = subprocess.run(
            cmd, check=True, capture_output=True, text=True,
            env=env, timeout=60  # 60s timeout to prevent hanging
        )
        # yt-dlp may append codec extensions, find the actual file
        if os.path.exists(output_path):
            ui_logger.log(f"  BGM downloaded: {os.path.basename(output_path)}")
            return output_path

        # Check for common yt-dlp output name variations
        base, _ = os.path.splitext(output_path)
        for ext in [".mp3", ".m4a", ".opus", ".webm"]:
            candidate = base + ext
            if os.path.exists(candidate):
                ui_logger.log(f"  BGM downloaded: {os.path.basename(candidate)}")
                return candidate

        ui_logger.log("  BGM search returned no downloadable audio.")
        return ""

    except subprocess.TimeoutExpired:
        ui_logger.log("  BGM download timed out (60s) — skipping music.")
        return ""
    except subprocess.CalledProcessError as e:
        ui_logger.log(f"  BGM download failed: {e.stderr[-300:] if e.stderr else 'unknown error'}")
        return ""
    except Exception as e:
        ui_logger.log(f"  BGM fetch error: {e}")
        return ""
