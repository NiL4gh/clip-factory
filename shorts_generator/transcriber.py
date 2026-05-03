import subprocess
import os
import torch
from faster_whisper import WhisperModel
from .logger import ui_logger

_model_cache = {}

def _get_model(model_size: str, whisper_dir: str):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    key = (model_size, device)
    if key not in _model_cache:
        ui_logger.log(f"Loading Whisper {model_size} model on {device.upper()}...")
        _model_cache[key] = WhisperModel(
            model_size, device=device, compute_type=compute_type,
            download_root=whisper_dir
        )
        ui_logger.log("Whisper model ready.")
    return _model_cache[key]

def transcribe_audio(
    video_path: str,
    model_size: str = "medium",
    whisper_dir: str = "/tmp/whisper",
    language: str = None,
):
    """
    Returns (full_text: str, word_timestamps: list[dict])
    """
    ui_logger.log("Extracting audio from video for transcription...")
    wav_path = video_path.replace(".mp4", "_audio.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-i", video_path, "-ar", "16000", "-ac", "1", wav_path],
        check=True, capture_output=True
    )

    model = _get_model(model_size, whisper_dir)

    transcribe_kwargs = {"beam_size": 5, "word_timestamps": True}
    if language:
        transcribe_kwargs["language"] = language

    ui_logger.log("Transcribing audio... (this may take a few minutes)")
    segments, info = model.transcribe(wav_path, **transcribe_kwargs)

    detected_lang = getattr(info, "language", language or "unknown")
    ui_logger.log(f"Detected language: {detected_lang}")

    full_text = ""
    word_timestamps = []

    for i, seg in enumerate(segments):
        if i % 20 == 0 and i > 0:
            ui_logger.log(f"Transcribed {i} segments...")
        full_text += seg.text + " "
        if seg.words:
            for w in seg.words:
                word_timestamps.append({
                    "word": w.word.strip(),
                    "start": w.start,
                    "end": w.end,
                })

    ui_logger.log(f"Transcription complete. Total words: {len(word_timestamps)}")

    try:
        os.remove(wav_path)
    except OSError:
        pass

    return full_text.strip(), word_timestamps
