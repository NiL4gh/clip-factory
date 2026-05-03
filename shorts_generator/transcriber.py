import subprocess
import os
from faster_whisper import WhisperModel

_model_cache = {}


def _get_model(model_size: str, whisper_dir: str, device: str = "cuda", compute_type: str = "float16"):
    key = (model_size, device)
    if key not in _model_cache:
        print(f"  [whisper] Loading {model_size} (cache: {whisper_dir})")
        _model_cache[key] = WhisperModel(
            model_size, device=device, compute_type=compute_type,
            download_root=whisper_dir
        )
        print("  [whisper] Ready.")
    return _model_cache[key]


def transcribe_audio(
    video_path: str,
    model_size: str = "medium",
    whisper_dir: str = "/tmp/whisper",
    device: str = "cuda",
    compute_type: str = "float16",
    language: str = None,
):
    """
    Returns (full_text: str, word_timestamps: list[dict])
    word_timestamps entries: {"word": str, "start": float, "end": float}

    language: ISO 639-1 code (e.g. "en", "bn" for Bangla). None = auto-detect.
    """
    # Extract 16kHz mono wav for faster processing
    wav_path = video_path.replace(".mp4", "_audio.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-i", video_path, "-ar", "16000", "-ac", "1", wav_path],
        check=True, capture_output=True
    )

    model = _get_model(model_size, whisper_dir, device, compute_type)

    transcribe_kwargs = {"beam_size": 5, "word_timestamps": True}
    if language:
        transcribe_kwargs["language"] = language

    segments, info = model.transcribe(wav_path, **transcribe_kwargs)

    detected_lang = getattr(info, "language", language or "unknown")
    print(f"  [whisper] Detected language: {detected_lang}")

    full_text = ""
    word_timestamps = []

    for seg in segments:
        full_text += seg.text + " "
        if seg.words:
            for w in seg.words:
                word_timestamps.append({
                    "word": w.word.strip(),
                    "start": w.start,
                    "end": w.end,
                })

    # Clean up temp wav
    try:
        os.remove(wav_path)
    except OSError:
        pass

    return full_text.strip(), word_timestamps
