import os
import subprocess
import uuid
import shutil
import cv2

def _get_crop_params(video_path, time_offset, target_w=1080, target_h=1920):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return f"(in_w-{target_w})/2", f"(in_h-{target_h})/2" 
        
    cap.set(cv2.CAP_PROP_POS_MSEC, time_offset * 1000)
    ret, frame = cap.read()
    cap.release()
    
    if not ret:
        return f"(in_w-{target_w})/2", f"(in_h-{target_h})/2"

    h, w = frame.shape[:2]
    
    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        cascade_path = os.path.join(cv2.data.haarcascades, 'haarcascade_frontalface_default.xml')
        face_cascade = cv2.CascadeClassifier(cascade_path)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
        
        if len(faces) > 0:
            faces = sorted(faces, key=lambda x: x[2]*x[3], reverse=True)
            fx, fy, fw, fh = faces[0]
            face_center_x = fx + (fw // 2)
            
            crop_x = max(0, min(w - target_w, face_center_x - (target_w // 2)))
            return str(int(crop_x)), f"(in_h-{target_h})/2"
    except Exception as e:
        pass
        
    return f"(in_w-{target_w})/2", f"(in_h-{target_h})/2"


def _generate_ass(words, out_path, video_w, video_h, time_offset=0, theme="Storytime", style_mode="Hormozi", position="Center"):
    
    # Base color palettes based on theme
    palettes = {
        "Motivation": {"main": "&H00FFFFFF", "high": "&H0000FFFF"}, # Yellow
        "Educational": {"main": "&H00FFFFFF", "high": "&H00FFC000"}, # Blue
        "Comedy": {"main": "&H00FFFFFF", "high": "&H00FF00FF"}, # Magenta
        "Suspense": {"main": "&H00FFFFFF", "high": "&H000000FF"}, # Red
        "Storytime": {"main": "&H00FFFFFF", "high": "&H0000A5FF"}  # Orange
    }
    
    p = palettes.get(theme, palettes["Storytime"])
    
    # Styling logic (Font, Outline, Shadows)
    if style_mode == "Hormozi":
        font_name = "Arial Black"
        outline = 6
        shadow = 4
        bold = 1
        font_size = 85
    elif style_mode == "Minimalist":
        font_name = "Arial"
        outline = 1
        shadow = 0
        bold = 0
        font_size = 75
    else: # Standard
        font_name = "Arial"
        outline = 4
        shadow = 2
        bold = 1
        font_size = 80
        
    # Position logic (ASS Alignment: 8=Top, 5=Center, 2=Bottom)
    align_map = {"Top": 8, "Center": 5, "Bottom": 2}
    align = align_map.get(position, 5)

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {video_w}",
        f"PlayResY: {video_h}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Main,{font_name},{font_size},{p['main']},&H000000FF,&H00000000,&H80000000,{bold},0,0,0,100,100,0,0,1,{outline},{shadow},{align},10,10,250,1",
        f"Style: Highlight,{font_name},{font_size},{p['high']},&H000000FF,&H00000000,&H80000000,{bold},0,0,0,100,100,0,0,1,{outline},{shadow},{align},10,10,250,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    ]
    
    def fmt_time(secs):
        h = int(secs // 3600)
        m = int((secs % 3600) // 60)
        s = int(secs % 60)
        cs = int((secs - int(secs)) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    chunks = []
    curr = []
    for w in words:
        if len(curr) >= 3:
            chunks.append(curr)
            curr = []
        curr.append(w)
    if curr:
        chunks.append(curr)

    for chunk in chunks:
        chunk_st = max(0, chunk[0]['start'] - time_offset)
        chunk_et = max(0, chunk[-1]['end'] - time_offset)
        if chunk_et <= chunk_st:
            continue
            
        for w in chunk:
            w_st = max(0, w["start"] - time_offset)
            w_et = max(0, w["end"] - time_offset)
            if w_et <= w_st:
                continue
                
            styled = ""
            for x in chunk:
                txt = x['word'].strip()
                if style_mode == "Hormozi": txt = txt.upper()
                
                if x == w:
                    styled += f"{{\\rHighlight}}{txt}{{\\rMain}} "
                else:
                    styled += f"{txt} "
            
            lines.append(f"Dialogue: 0,{fmt_time(w_st)},{fmt_time(w_et)},Main,,0,0,0,,{styled.strip()}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def render_short(input_video, clip_data, word_timestamps, output_dir, work_dir, 
                 face_center=True, add_subs=True, theme="Storytime", 
                 caption_style="Hormozi", caption_pos="Center",
                 override_start=None, override_end=None):
                     
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)
    out_id = uuid.uuid4().hex[:8]
    final_output = os.path.join(output_dir, f"short_{out_id}.mp4")
    
    target_w, target_h = 1080, 1920
    
    # 1. Base boundaries (Use overrides if provided)
    base_st = float(override_start) if override_start is not None else float(clip_data.get("start_time", 0))
    base_et = float(override_end) if override_end is not None else float(clip_data.get("end_time", 0))
    
    # Filter words in this global block
    block_words = [w for w in word_timestamps if w["start"] >= base_st - 0.5 and w["end"] <= base_et + 0.5]
    
    # 2. Dynamic Pacing Edit (Silence Removal)
    # Instead of asking the LLM to guess micro-cuts, we algorithmically cut dead air > 0.8s
    segments = []
    if not block_words:
        segments.append({"start_time": base_st, "end_time": base_et})
    else:
        current_st = max(base_st, block_words[0]["start"] - 0.2)
        gap_threshold = 0.8
        
        for i in range(len(block_words) - 1):
            w_curr = block_words[i]
            w_next = block_words[i+1]
            if w_next['start'] - w_curr['end'] > gap_threshold:
                # Silence detected. Close current segment.
                segments.append({"start_time": current_st, "end_time": w_curr['end'] + 0.2})
                # Start new segment
                current_st = w_next['start'] - 0.2
                
        # Close final segment
        segments.append({"start_time": current_st, "end_time": min(base_et, block_words[-1]['end'] + 0.2)})

    rendered_segs = []
    for idx, seg in enumerate(segments):
        seg_st = float(seg["start_time"])
        seg_et = float(seg["end_time"])
        if seg_et - seg_st < 0.5: continue # Skip ultra-short artifacts
        
        if face_center:
            crop_x, crop_y = _get_crop_params(input_video, seg_st, target_w, target_h)
        else:
            crop_x, crop_y = f"(in_w-{target_w})/2", f"(in_h-{target_h})/2"
        
        seg_words = [w for w in block_words if w["start"] >= seg_st - 0.2 and w["end"] <= seg_et + 0.2]
        
        ass_path = os.path.join(work_dir, f"subs_{out_id}_{idx}.ass")
        _generate_ass(seg_words, ass_path, target_w, target_h, time_offset=seg_st, 
                      theme=theme, style_mode=caption_style, position=caption_pos)
        
        seg_out = os.path.join(work_dir, f"seg_{out_id}_{idx}.mp4")
        
        cmd = ["ffmpeg", "-y", "-ss", str(seg_st), "-to", str(seg_et), "-i", input_video]
        
        vf = [f"crop={target_w}:{target_h}:{crop_x}:{crop_y}"]
        if add_subs and seg_words:
            safe_ass = ass_path.replace("\\", "/").replace(":", "\\:")
            vf.append(f"ass='{safe_ass}'")
            
        cmd.extend(["-vf", ",".join(vf), "-c:v", "libx264", "-c:a", "aac", seg_out])
        subprocess.run(cmd, check=True)
        rendered_segs.append(seg_out)
        
    if not rendered_segs:
        raise ValueError("No valid segments could be rendered.")
        
    if len(rendered_segs) == 1:
        shutil.copy2(rendered_segs[0], final_output)
    else:
        concat_txt = os.path.join(work_dir, f"concat_{out_id}.txt")
        with open(concat_txt, "w", encoding="utf-8") as f:
            for s in rendered_segs:
                p = s.replace("\\", "/")
                f.write(f"file '{p}'\n")
        concat_cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt, "-c", "copy", final_output]
        subprocess.run(concat_cmd, check=True)
        
    return final_output
