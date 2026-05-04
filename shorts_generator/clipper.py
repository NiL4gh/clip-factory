import os
import subprocess
import uuid
import shutil
import cv2
import urllib.request

from shorts_generator.media import get_broll_image, get_twemoji, get_sfx
from .logger import ui_logger

# Ensure we have our premium font
FONT_PATH = "/usr/share/fonts/truetype/Montserrat-Black.ttf"
if os.path.exists("/usr/share/fonts/truetype") and not os.path.exists(FONT_PATH):
    try:
        urllib.request.urlretrieve("https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Black.ttf", FONT_PATH)
        subprocess.run(["fc-cache", "-fv"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ui_logger.log("Premium font (Montserrat-Black) installed.")
    except:
        pass

def _get_crop_params(video_path, time_offset, target_w=1080, target_h=1920):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return "in_w/2-ih*9/32", "0", "ih*9/16", "ih"

    cap.set(cv2.CAP_PROP_POS_MSEC, time_offset * 1000)
    ret, frame = cap.read()
    cap.release()

    if not ret:
        return "in_w/2-ih*9/32", "0", "ih*9/16", "ih"

    h, w = frame.shape[:2]
    crop_w = int(h * 9 / 16)
    crop_h = h

    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        cascade_path = os.path.join(cv2.data.haarcascades, 'haarcascade_frontalface_default.xml')
        face_cascade = cv2.CascadeClassifier(cascade_path)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))

        if len(faces) > 0:
            faces = sorted(faces, key=lambda x: x[2]*x[3], reverse=True)
            fx, fy, fw, fh = faces[0]
            face_center_x = fx + (fw // 2)

            crop_x = max(0, min(w - crop_w, face_center_x - (crop_w // 2)))
            return str(int(crop_x)), "0", str(crop_w), str(crop_h)
    except Exception as e:
        pass

    return "in_w/2-ih*9/32", "0", "ih*9/16", "ih"


def _generate_ass(words, out_path, video_w, video_h, time_offset=0, theme="Storytime", style_mode="Hormozi", position="Center", **kwargs):
    palettes = {
        "Motivation": {"main": "&H00FFFFFF", "high": "&H0000FFFF"}, 
        "Educational": {"main": "&H00FFFFFF", "high": "&H00FFC000"}, 
        "Comedy": {"main": "&H00FFFFFF", "high": "&H00FF00FF"}, 
        "Suspense": {"main": "&H00FFFFFF", "high": "&H000000FF"}, 
        "Storytime": {"main": "&H00FFFFFF", "high": "&H0000A5FF"}  
    }

    p = palettes.get(theme, palettes["Storytime"])

    if style_mode == "Hormozi":
        font_name = "Montserrat Black"
        outline = 6; shadow = 4; bold = 1; font_size = 90
    elif style_mode == "Ali Abdaal":
        font_name = "Georgia"
        outline = 2; shadow = 1; bold = 0; font_size = 70
    elif style_mode == "MrBeast":
        font_name = "Impact"
        outline = 8; shadow = 5; bold = 1; font_size = 100
    elif style_mode == "Minimalist":
        font_name = "Arial"
        outline = 1; shadow = 0; bold = 0; font_size = 75
    else: 
        font_name = "Arial"
        outline = 4; shadow = 2; bold = 1; font_size = 80

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
        f"Style: Highlight,{font_name},{font_size},{p['high']},&H000000FF,&H00000000,&H80000000,{bold},0,0,0,100,100,0,0,1,{outline},{shadow},{align},10,10,250,1"
    ]
    
    if kwargs.get("magic_hook_text"):
        lines.append(f"Style: MagicHook,{font_name},110,&H0044FFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,8,6,5,10,10,150,1")

    lines.extend([
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    ])
    
    if kwargs.get("magic_hook_text"):
        lines.append(f"Dialogue: 0,0:00:00.00,0:00:02.50,MagicHook,,0,0,0,,{kwargs['magic_hook_text'].upper()}")

    def fmt_time(secs):
        h = int(secs // 3600); m = int((secs % 3600) // 60); s = int(secs % 60); cs = int((secs - int(secs)) * 100)
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
        if chunk_et <= chunk_st: continue

        for w in chunk:
            w_st = max(0, w["start"] - time_offset)
            w_et = max(0, w["end"] - time_offset)
            if w_et <= w_st: continue

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
                 override_start=None, override_end=None, excluded_sentences=None,
                 magic_hook=False, remove_silence=True, broll_intensity="Medium",
                 all_sentences=None):

    ui_logger.log("Initializing render pipeline...")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)
    out_id = uuid.uuid4().hex[:8]
    final_output = os.path.join(output_dir, f"short_{out_id}.mp4")

    target_w, target_h = 1080, 1920

    # ── Stitched multi-segment clips (Q&A / Setup-Payoff) ────────────────────
    # If clip_data has a 'segments' array (from get_stitched_clips), render each
    # segment independently and concatenate — overrides start/end override logic.
    is_stitched = bool(clip_data.get("is_stitched") and clip_data.get("segments"))
    if is_stitched:
        raw_segments = clip_data["segments"]
        ui_logger.log(f"Stitched clip: rendering {len(raw_segments)} segments across different timestamps...")
        # For stitched clips, collect all words across all segments for subtitles/broll
        block_words = []
        for seg in raw_segments:
            seg_st = float(seg["start_time"])
            seg_et = float(seg["end_time"])
            block_words.extend([w for w in word_timestamps if seg_st - 0.5 <= w["start"] <= seg_et + 0.5])
        segments = [{"start_time": float(s["start_time"]), "end_time": float(s["end_time"])}
                    for s in raw_segments]
    else:
        # ── Standard single-range clip ────────────────────────────────────────
        base_st = float(override_start) if override_start is not None else float(clip_data.get("start_time", 0))
        base_et = float(override_end) if override_end is not None else float(clip_data.get("end_time", 0))

        excluded_ranges = []
        if excluded_sentences and all_sentences:
            for ex_str in excluded_sentences:
                try:
                    idx = all_sentences.index(ex_str)
                    st_str = ex_str.split("s]")[0].replace("[", "").strip()
                    st_val = float(st_str)
                    
                    if idx + 1 < len(all_sentences):
                        next_st_str = all_sentences[idx+1].split("s]")[0].replace("[", "").strip()
                        et_val = float(next_st_str)
                    else:
                        et_val = base_et
                        
                    excluded_ranges.append({"start": st_val - 0.1, "end": et_val - 0.1})
                except: pass
        elif excluded_sentences:
            for ex_str in excluded_sentences:
                try:
                    st_str = ex_str.split("s]")[0].replace("[", "").strip()
                    st_val = float(st_str)
                    excluded_ranges.append({"start": st_val - 0.1, "end": st_val + 5.0})
                except: pass

        block_words = []
        for w in word_timestamps:
            if w["start"] >= base_st - 0.5 and w["end"] <= base_et + 0.5:
                excluded = False
                for r in excluded_ranges:
                    if r["start"] <= w["start"] <= r["end"]:
                        excluded = True
                        break
                if not excluded:
                    block_words.append(w)

        segments = []
        if not block_words:
            segments.append({"start_time": base_st, "end_time": base_et})
        else:
            current_st = max(base_st, block_words[0]["start"] - 0.2)
            if remove_silence:
                gap_threshold = 0.8
                for i in range(len(block_words) - 1):
                    w_curr = block_words[i]
                    w_next = block_words[i+1]
                    if w_next['start'] - w_curr['end'] > gap_threshold:
                        segments.append({"start_time": current_st, "end_time": w_curr['end'] + 0.2})
                        current_st = w_next['start'] - 0.2
                segments.append({"start_time": current_st, "end_time": min(base_et, block_words[-1]['end'] + 0.2)})
            else:
                segments.append({"start_time": current_st, "end_time": min(base_et, block_words[-1]['end'] + 0.2)})

    broll_kws = clip_data.get("broll_keywords", [])
    emoji_moms = clip_data.get("emoji_moments", [])
    if broll_intensity == "None":
        broll_kws = []
        emoji_moms = []
    elif broll_intensity == "Low":
        broll_kws = broll_kws[:1]
        emoji_moms = emoji_moms[:1]
    elif broll_intensity == "Medium":
        broll_kws = broll_kws[:2]
        emoji_moms = emoji_moms[:2]

    rendered_segs = []
    for idx, seg in enumerate(segments):
        seg_st = float(seg["start_time"])
        seg_et = float(seg["end_time"])
        if seg_et - seg_st < 0.5: continue 
        
        ui_logger.log(f"Rendering segment {idx+1}/{len(segments)} (Time: {seg_st:.1f}s - {seg_et:.1f}s)...")

        is_peak = (seg_st <= float(clip_data.get("peak_moment", 0)) <= seg_et)

        crop_x, crop_y, crop_w, crop_h = "in_w/2-ih*9/32", "0", "ih*9/16", "ih"
        if face_center:
            crop_params = _get_crop_params(input_video, seg_st, target_w, target_h)
            if len(crop_params) == 4:
                crop_x, crop_y, crop_w, crop_h = crop_params
            else:
                crop_x, crop_y = crop_params
        else:
            crop_x, crop_y = "in_w/2-ih*9/32", "0"

        if is_peak and face_center:
            try:
                z_f = 1.2
                cw = int(float(crop_w) / z_f) if crop_w.isdigit() else "ih*9/16/1.2"
                ch = int(float(crop_h) / z_f) if crop_h.isdigit() else "ih/1.2"
                
                if crop_x.isdigit() and crop_w.isdigit():
                    cx = int(float(crop_x) + (float(crop_w) - float(cw))/2)
                else:
                    cx = crop_x
                    
                cy = "0"
                base_crop = f"crop={cw}:{ch}:{cx}:{cy},scale={target_w}:{target_h}"
            except:
                base_crop = f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={target_w}:{target_h}"
        else:
            base_crop = f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={target_w}:{target_h}"

        seg_out = os.path.join(work_dir, f"seg_{out_id}_{idx}.mp4")

        inputs = ["-i", input_video]
        filter_complex = f"[0:v]{base_crop}[base];"
        current_v = "base"

        input_idx = 1
        sfx_delays = []
        for b in broll_kws:
            b_st = float(b.get("start_time", 0))
            if b_st >= seg_st and b_st <= seg_et:
                b_img_path = os.path.join(work_dir, f"broll_{out_id}_{input_idx}.jpg")
                if get_broll_image(b.get("keyword", ""), b_img_path):
                    inputs.extend(["-loop", "1", "-t", "2.0", "-i", b_img_path])
                    sfx_delays.append(b_st - seg_st)

                    filter_complex += f"[{input_idx}:v]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,crop={target_w}:{target_h}[broll{input_idx}];"

                    rel_st = b_st - seg_st
                    rel_et = rel_st + 2.0
                    next_v = f"v{input_idx}"

                    filter_complex += f"[{current_v}][broll{input_idx}]overlay=0:0:enable='between(t,{rel_st},{rel_et})'[{next_v}];"
                    current_v = next_v
                    input_idx += 1
        for e in emoji_moms:
            e_st = float(e.get("start_time", 0))
            if e_st >= seg_st and e_st <= seg_et:
                e_img_path = os.path.join(work_dir, f"emoji_{out_id}_{input_idx}.png")
                if get_twemoji(e.get("emoji_unicode", ""), e_img_path):
                    inputs.extend(["-loop", "1", "-t", "1.5", "-i", e_img_path])
                    sfx_delays.append(e_st - seg_st)

                    filter_complex += f"[{input_idx}:v]scale=250:250[emoji{input_idx}];"

                    rel_st = e_st - seg_st
                    rel_et = rel_st + 1.5
                    next_v = f"v{input_idx}"
                    filter_complex += f"[{current_v}][emoji{input_idx}]overlay=x='W-w-50':y='H-h-300 + 100*max(0, 0.2-(t-{rel_st}))/0.2':enable='between(t,{rel_st},{rel_et})'[{next_v}];"
                    current_v = next_v
                    input_idx += 1

        sfx_path = os.path.join(work_dir, "pop.mp3")
        sfx_ok = get_sfx(sfx_path) and os.path.exists(sfx_path)
        if not sfx_ok:
            ui_logger.log("SFX download failed — skipping pop sounds (clip will still render).")
            sfx_delays = []  # clear so audio filter is skipped safely
        for delay in sfx_delays:
            inputs.extend(["-i", sfx_path])

        seg_words = [w for w in block_words if w["start"] >= seg_st - 0.2 and w["end"] <= seg_et + 0.2]
        if add_subs and seg_words:
            ass_path = os.path.join(work_dir, f"subs_{out_id}_{idx}.ass")
            mh_text = clip_data.get("hook_sentence") if (magic_hook and idx == 0) else None
            _generate_ass(seg_words, ass_path, target_w, target_h, time_offset=seg_st,
                          theme=theme, style_mode=caption_style, position=caption_pos, magic_hook_text=mh_text)
            safe_ass = ass_path.replace("\\", "/").replace(":", "\\:")
            next_v = f"v{input_idx}_ass"
            filter_complex += f"[{current_v}]ass='{safe_ass}'[{next_v}];"
            current_v = next_v

        filter_complex = filter_complex.rstrip(';')

        audio_filter = ""
        if sfx_delays:
            audio_filter = "[0:a]volume=1.0[a_base];"
            amix_inputs = "[a_base]"
            for i, delay_sec in enumerate(sfx_delays):
                sfx_idx = input_idx + i
                delay_ms = max(0, int(delay_sec * 1000))
                audio_filter += f"[{sfx_idx}:a]adelay={delay_ms}|{delay_ms},volume=0.6[sfx_{i}];"
                amix_inputs += f"[sfx_{i}]"
            audio_filter += f"{amix_inputs}amix=inputs={len(sfx_delays)+1}:duration=first[a_out]"
            audio_map = "[a_out]"
            filter_complex += f";{audio_filter}"
        else:
            audio_map = "0:a"

        cmd = ["ffmpeg", "-y", "-ss", str(seg_st), "-to", str(seg_et)]
        cmd.extend(inputs)
        cmd.extend(["-filter_complex", filter_complex, "-map", f"[{current_v}]", "-map", audio_map, "-c:v", "libx264", "-c:a", "aac", seg_out])

        ui_logger.log(f"Executing FFmpeg for segment {idx+1}...")
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            ui_logger.log(f"FFmpeg error: {e.stderr}")
            raise
        rendered_segs.append(seg_out)

    if not rendered_segs:
        raise ValueError("No valid segments could be rendered. (Check your transcript exclusions)")

    ui_logger.log("Combining segments into final short...")
    if len(rendered_segs) == 1:
        shutil.copy2(rendered_segs[0], final_output)
    else:
        concat_txt = os.path.join(work_dir, f"concat_{out_id}.txt")
        with open(concat_txt, "w", encoding="utf-8") as f:
            for s in rendered_segs:
                p = s.replace("\\", "/")
                f.write(f"file '{p}'\n")
        concat_cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt, "-c", "copy", final_output]
        try:
            subprocess.run(concat_cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            ui_logger.log(f"FFmpeg concat error: {e.stderr}")
            raise

    ui_logger.log(f"Render complete: {os.path.basename(final_output)}")
    return final_output