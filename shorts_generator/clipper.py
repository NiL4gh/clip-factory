import subprocess
import os
import cv2
import uuid

def render_short(input_video, clip_data, word_timestamps, output_dir, work_dir, face_center=True):
    """
    Cuts, crops, and burn subtitles into a single viral short.
    """
    start, end = clip_data['start'], clip_data['end']
    out_path = os.path.join(output_dir, f"short_{uuid.uuid4().hex[:6]}.mp4")
    
    # 1. AI Face Detection for Centering
    x_offset = "(w-ih*9/16)/2" # Default to center crop
    if face_center:
        cap = cv2.VideoCapture(input_video)
        cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
        ret, frame = cap.read()
        if ret:
            face_cc = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
            faces = face_cc.detectMultiScale(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 1.3, 5)
            if len(faces):
                fx, fy, fw, fh = faces[0]
                face_x = fx + (fw / 2)
                crop_width = frame.shape[0] * 9 / 16
                ideal_x = face_x - (crop_width / 2)
                x_offset = max(0, min(int(frame.shape[1] - crop_width), int(ideal_x)))
        cap.release()

    # 2. Subtitle Generation (Simplified ASS format)
    ass_path = os.path.join(work_dir, "subs.ass")
    generate_ass_file(word_timestamps, start, end, ass_path)
    
    # 3. FFmpeg Command
    # We use -c:v libx264 for compatibility and -c:a aac for audio
    vf_filters = [
        f"crop=ih*9/16:ih:{x_offset}:0",
        "scale=1080:1920",
        f"ass='{ass_path.replace(':', r'\:')}'"
    ]
    
    cmd = [
        'ffmpeg', '-y', '-ss', str(start), '-to', str(end),
        '-i', input_video, '-vf', ",".join(vf_filters),
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22',
        '-c:a', 'aac', '-b:a', '192k', out_path
    ]
    
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path

def generate_ass_file(words, start_time, end_time, out_path):
    # Filters words belonging to this clip
    clip_words = [w for w in words if w['start'] >= start_time and w['end'] <= end_time]
    
    header = "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
    styles = "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    styles += "Style: Default,Arial,80,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,5,10,10,200,1\n\n"
    events = "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    
    def to_ass_time(s):
        s = max(0, s - start_time)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{int(h)}:{int(m):02d}:{s:05.2f}"

    lines = [header, styles, events]
    for w in clip_words:
        start_ass = to_ass_time(w['start'])
        end_ass = to_ass_time(w['end'])
        # Highlights the active word in Yellow
        text = f"{{\\c&H00FFFF&}}{w['word']}{{\\r}}"
        lines.append(f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{text}\n")
        
    with open(out_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
