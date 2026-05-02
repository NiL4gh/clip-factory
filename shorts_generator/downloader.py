import yt_dlp
import subprocess
import os
import glob

def download_video(url, work_dir, cookie_path=None):
    output_mp4 = f"{work_dir}/source.mp4"
    
    # Cascade: Best MP4 -> Best Video+Audio -> Best Single File
    ydl_opts = {
        'format': 'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b',
        'outtmpl': f'{work_dir}/source.%(ext)s',
        'cookiefile': cookie_path if cookie_path and os.path.exists(cookie_path) else None,
        'quiet': True,
        'merge_output_format': 'mp4',
        'postprocessors': [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # Nuclear Fallback: Fast Remuxing (no re-encoding)
    if not os.path.exists(output_mp4):
        files = glob.glob(f"{work_dir}/source.*")
        if files:
            raw_file = files[0]
            subprocess.run(['ffmpeg', '-y', '-i', raw_file, '-c', 'copy', output_mp4], check=True)
            if raw_file != output_mp4: os.remove(raw_file)
            
    return output_mp4
