from .pipeline import OpusPipeline


def generate_shorts(youtube_url, num_clips=3, aspect_ratio="9:16",
                    download_format="720", language=None):
    """Convenience wrapper for CLI usage via main.py."""
    import os
    from .config import WORK_DIR, LLM_DIR, LLM_CATALOG, WHISPER_DIR, WHISPER_CATALOG, COOKIE_PATH
    from .clipper import render_short
    from . import cache

    llm_entry = LLM_CATALOG[0]
    llm_path = os.path.join(LLM_DIR, llm_entry["filename"])

    pipe = OpusPipeline(WORK_DIR)
    clips, words, status = pipe.process_new_video(
        url=youtube_url,
        num_clips=num_clips,
        llm_path=llm_path,
        gpu_layers=llm_entry["gpu_layers"],
        whisper_size=WHISPER_CATALOG[3]["size"],
        whisper_dir=WHISPER_DIR,
        cookie_path=COOKIE_PATH,
        language=language,
    )

    shorts = []
    for c in clips[:num_clips]:
        try:
            out = render_short(
                input_video=os.path.join(WORK_DIR, "source.mp4"),
                clip_data=c,
                word_timestamps=words,
                output_dir=cache.get_clips_dir(youtube_url),
                work_dir=WORK_DIR,
            )
            c["clip_url"] = out
        except Exception as e:
            c["error"] = str(e)
        shorts.append(c)

    return {
        "source_video_url": youtube_url,
        "highlights": clips,
        "shorts": shorts,
    }
