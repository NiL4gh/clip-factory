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

def parse_srt_to_word_timestamps(srt_path: str) -> list:
    try:
        import re
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Normalize line endings to LF
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        
        # Split into blocks separated by double newlines
        blocks = re.split(r'\n\s*\n', content.strip())
        
        results = []
        time_pattern = re.compile(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})')
        html_pattern = re.compile(r'<[^>]+>')

        for block in blocks:
            lines = block.strip().split('\n')
            if len(lines) < 2:
                continue
            
            # Find the timestamp line
            time_match = None
            time_line_idx = -1
            for idx, line in enumerate(lines):
                m = time_pattern.search(line)
                if m:
                    time_match = m
                    time_line_idx = idx
                    break
            
            if not time_match or time_line_idx == -1:
                continue
            
            # Parse start time
            h1, m1, s1, ms1 = map(int, time_match.groups()[0:4])
            seg_start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000.0
            
            # Parse end time
            h2, m2, s2, ms2 = map(int, time_match.groups()[4:8])
            seg_end = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000.0
            
            # Text lines are everything after the timestamp line
            text_lines = lines[time_line_idx + 1:]
            raw_text = " ".join(text_lines)
            
            # Clean HTML tags using a regex that removes anything inside angle brackets
            cleaned_text = html_pattern.sub("", raw_text).strip()
            
            # Split into individual words
            words = [w for w in cleaned_text.split() if w]
            N = len(words)
            if N == 0:
                continue
                
            seg_duration = seg_end - seg_start
            for i, word_text in enumerate(words):
                w_start = seg_start + (i / N) * seg_duration
                w_end = seg_start + ((i + 1) / N) * seg_duration
                results.append({
                    "word": word_text,
                    "start": w_start,
                    "end": w_end
                })
                
        return results
    except Exception as e:
        ui_logger.log(f"Warning: parse_srt_to_word_timestamps failed: {e}")
        return []

