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
    return current_relative_time / 2.0 # Fallback to middle if peak is outside segments

def add_smart_background_music(video_path: str, music_path: str, output_path: str, clip_data: dict):
    """Mixes background music, swelling volume dynamically at the peak moment."""
    rel_peak = get_relative_peak(clip_data)
    peak_start = max(0, rel_peak - 1.5) # start swelling 1.5s before peak
    
    # Base volume 0.03. At peak_start, ramp up to 0.20 over 1.5s
    vol_expr = f"0.03 + 0.17*clip((t-{peak_start})/1.5, 0, 1)"
    
    cmd = [
        "ffmpeg", "-y", 
        "-i", video_path, 
        "-stream_loop", "-1", 
        "-i", music_path, 
        "-filter_complex", f"[0:a]volume=1.0[a0];[1:a]volume='{vol_expr}':eval=frame[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[a]",
        "-map", "0:v", 
        "-map", "[a]", 
        "-c:v", "copy", 
        "-c:a", "aac", 
        "-shortest", 
        output_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Music mixing failed:\n{res.stderr[-1000:]}")
    return output_path

def enhance_clip(video_path: str, clip_data: dict, music_path: str = None) -> str:
    if not music_path:
        return video_path
        
    tmp1 = video_path.replace(".mp4", "_e1.mp4")
    
    if music_path:
        add_smart_background_music(video_path, music_path, tmp1, clip_data)
        shutil.move(tmp1, video_path)
            
    return video_path
