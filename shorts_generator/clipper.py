import os
import subprocess
import uuid
import shutil
import cv2

def _get_crop_params(video_path, time_offset, target_w=1080, target_h=1920, sample_fps=1):
    # Fallback default crop
    return (0, 0)

def _generate_ass(words, out_path, video_w, video_h, time_offset=0):
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {video_w}",
        f"PlayResY: {video_h}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Main,Arial,80,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,5,10,10,250,1",
        "Style: Highlight,Arial,80,&H0000FFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,5,10,10,250,1",
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

    # Group words into chunks of 3-4
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
        # Subtract time_offset because the ffmpeg filter starts this segment at t=0
        chunk_st = max(0, chunk[0]['start'] - time_offset)
        chunk_et = max(0, chunk[-1]['end'] - time_offset)
        if chunk_et <= chunk_st:
            continue
            
        full_text = " ".join(w["word"].strip() for w in chunk)
        
        for w in chunk:
            w_st = max(0, w["start"] - time_offset)
            w_et = max(0, w["end"] - time_offset)
            if w_et <= w_st:
                continue
                
            styled = ""
            for x in chunk:
                if x == w:
                    styled += f"{{\\rHighlight}}{x['word'].strip()}{{\\rMain}} "
                else:
                    styled += f"{x['word'].strip()} "
            
            lines.append(f"Dialogue: 0,{fmt_time(w_st)},{fmt_time(w_et)},Main,,0,0,0,,{styled.strip()}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

def render_short(input_video, clip_data, word_timestamps, output_dir, work_dir, face_center=True, add_subs=True):
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)
    out_id = uuid.uuid4().hex[:8]
    final_output = os.path.join(output_dir, f"short_{out_id}.mp4")
    
    segments = clip_data.get("segments", [{"start_time": clip_data["start_time"], "end_time": clip_data["end_time"]}])
    target_w, target_h = 1080, 1920
    
    rendered_segs = []
    for idx, seg in enumerate(segments):
        seg_st = float(seg["start_time"])
        seg_et = float(seg["end_time"])
        
        # Simple center crop for now
        crop_x = f"(in_w-{target_w})/2"
        crop_y = f"(in_h-{target_h})/2"
        
        seg_words = [w for w in word_timestamps if w["start"] >= seg_st - 0.5 and w["end"] <= seg_et + 0.5]
        
        ass_path = os.path.join(work_dir, f"subs_{out_id}_{idx}.ass")
        _generate_ass(seg_words, ass_path, target_w, target_h, time_offset=seg_st)
        
        seg_out = os.path.join(work_dir, f"seg_{out_id}_{idx}.mp4")
        
        cmd = ["ffmpeg", "-y", "-ss", str(seg_st), "-to", str(seg_et), "-i", input_video]
        
        vf = [f"crop={target_w}:{target_h}:{crop_x}:{crop_y}"]
        if add_subs and seg_words:
            safe_ass = ass_path.replace("\\", "/").replace(":", "\\:")
            vf.append(f"ass='{safe_ass}'")
            
        cmd.extend(["-vf", ",".join(vf), "-c:v", "libx264", "-c:a", "aac", seg_out])
        subprocess.run(cmd, check=True)
        rendered_segs.append(seg_out)
        
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
