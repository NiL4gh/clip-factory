import subprocess
import os
import shutil

def add_background_music(video_path: str, music_path: str, output_path: str, music_volume: float = 0.1):
    """Mixes background music into a video, looping the music to fit the video duration."""
    cmd = [
        "ffmpeg", "-y", 
        "-i", video_path, 
        "-stream_loop", "-1", 
        "-i", music_path, 
        "-filter_complex", f"[0:a]volume=1.0[a0];[1:a]volume={music_volume}[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[a]",
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

def add_watermark(video_path: str, text: str, output_path: str):
    """Adds a semi-transparent watermark text to the top-right."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", f"drawtext=text='{text}':fontcolor=white@0.4:fontsize=36:x=w-tw-20:y=20:box=1:boxcolor=black@0.2:boxborderw=5",
        "-c:a", "copy",
        output_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Watermark failed:\n{res.stderr[-1000:]}")
    return output_path

def enhance_clip(video_path: str, music_path: str = None, watermark: str = None) -> str:
    if not music_path and not watermark:
        return video_path
        
    current = video_path
    tmp1 = video_path.replace(".mp4", "_e1.mp4")
    tmp2 = video_path.replace(".mp4", "_e2.mp4")
    
    if music_path:
        current = add_background_music(current, music_path, tmp1)
        
    if watermark:
        target = tmp2 if current == tmp1 else tmp1
        current = add_watermark(current, watermark, target)
        
    # Replace original
    shutil.move(current, video_path)
    
    # Clean up
    for t in [tmp1, tmp2]:
        if os.path.exists(t):
            os.remove(t)
            
    return video_path
