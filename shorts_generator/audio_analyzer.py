import os
import librosa
import numpy

def analyze_audio_energy(wav_path: str) -> list:
    try:
        if not os.path.exists(wav_path):
            return []

        y, sr = librosa.load(wav_path, sr=16000, mono=True)

        result = librosa.feature.rms(y=y, frame_length=16000, hop_length=8000)
        rms = result[0]

        frames = numpy.arange(len(rms))
        times = librosa.frames_to_time(frames, sr=16000, hop_length=8000)

        rms_norm = rms / (rms.max() + 1e-6)

        selected_indices = numpy.where(rms_norm > 0.55)[0]

        peaks = [{"time": float(times[i]), "energy": float(rms_norm[i])} for i in selected_indices]

        # Keep all peaks — no hard cap. For long videos the top-30 limit
        # meant only the loudest early-video moments were kept; clips beyond
        # ~15 min always got energy_score=0. Sort by time for fast range lookup.
        peaks.sort(key=lambda x: x["time"])

        return peaks

    except Exception as e:
        print(f"Error in analyze_audio_energy: {e}")
        return []
