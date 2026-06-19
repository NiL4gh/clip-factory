import subprocess
import os
import shutil

def get_relative_peak(clip_data):
    """Calculates where the peak moment occurs relative to the final concatenated clip."""
    peak = float(clip_data.get("peak_moment", clip_data.get("start_time", 0)))
    segments = clip_data.get("segments", [{"start_time": clip_data.get("start_time"), "end_time": clip_data.get("end_time")}])

    current_relative_time = 0.0
    for seg in segments:
        st = float(seg.get("start_time", 0))
        et = float(seg.get("end_time", 0))
        if st <= peak <= et:
            return current_relative_time + (peak - st)
        if peak > et:
            current_relative_time += (et - st)
    return current_relative_time / 2.0


def normalize_audio(video_path: str, output_path: str):
    """Apply EBU R128 loudness normalization (-14 LUFS, YouTube standard)."""
    # Two-pass loudnorm: first pass measures, second pass applies
    measure_cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ]
    res = subprocess.run(measure_cmd, capture_output=True, text=True)
    # loudnorm prints its JSON to stderr
    stderr = res.stderr
    import json, re
    m = re.search(r'\{[^}]*"input_i"[^}]*\}', stderr, re.DOTALL)
    if m:
        try:
            stats = json.loads(m.group())
            il = stats.get("input_i", "-23")
            lra = stats.get("input_lra", "7")
            tp = stats.get("input_tp", "-2")
            offset = stats.get("target_offset", "0")
            af = (
                f"loudnorm=I=-14:TP=-1.5:LRA=11"
                f":measured_I={il}:measured_LRA={lra}"
                f":measured_TP={tp}:offset={offset}:linear=true"
            )
        except Exception:
            af = "loudnorm=I=-14:TP=-1.5:LRA=11"
    else:
        af = "loudnorm=I=-14:TP=-1.5:LRA=11"

    apply_cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-af", af,
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        output_path,
    ]
    res2 = subprocess.run(apply_cmd, capture_output=True, text=True)
    if res2.returncode != 0:
        raise RuntimeError(f"Audio normalization failed:\n{res2.stderr[-800:]}")
    return output_path


def add_smart_background_music(video_path: str, music_path: str, output_path: str, clip_data: dict):
    """Mixes background music, swelling volume dynamically at the peak moment."""
    rel_peak = get_relative_peak(clip_data)
    peak_start = max(0, rel_peak - 1.5)

    vol_expr = f"0.03 + 0.17*clip((t-{peak_start})/1.5, 0, 1)"

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-stream_loop", "-1",
        "-i", music_path,
        "-filter_complex", (
            f"[0:a]loudnorm=I=-14:TP=-1.5:LRA=11[a0_norm];"
            f"[1:a]volume='{vol_expr}':eval=frame[a1];"
            f"[a1][a0_norm]sidechaincompress=threshold=0.15:ratio=4:attack=50:release=300[a1d];"
            f"[a0_norm][a1d]amix=inputs=2:duration=first:dropout_transition=2,asetpts=PTS-STARTPTS[a]"
        ),
        "-map", "0:v",
        "-map", "[a]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Music mixing failed:\n{res.stderr[-1000:]}")
    return output_path


def enhance_clip(video_path: str, clip_data: dict, music_path: str = None) -> str:
    tmp1 = video_path.replace(".mp4", "_e1.mp4")

    if music_path:
        add_smart_background_music(video_path, music_path, tmp1, clip_data)
    else:
        normalize_audio(video_path, tmp1)

    shutil.move(tmp1, video_path)
    return video_path
