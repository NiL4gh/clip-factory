from faster_whisper import WhisperModel
import os

def transcribe_audio(video_path, model_size="medium", device="cuda", compute_type="float16"):
    """
    Transcribes video audio and returns both full text and word-level timestamps.
    """
    # Extract audio for faster processing if needed, though faster-whisper handles video files
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    
    # beam_size=5 is a good balance between speed and accuracy
    segments, info = model.transcribe(video_path, beam_size=5, word_timestamps=True)
    
    full_text = ""
    word_timestamps = []
    
    for segment in segments:
        full_text += segment.text + " "
        if segment.words:
            for word in segment.words:
                word_timestamps.append({
                    "word": word.word.strip(),
                    "start": word.start,
                    "end": word.end
                })
                
    return full_text.strip(), word_timestamps
