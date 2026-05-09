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

def _render_dynamic_crop(input_video, seg_st, seg_et, target_w, target_h, temp_out, is_peak=False):
    """
    Reads the video using OpenCV, runs dynamic MediaPipe face tracking with smoothing,
    and pipes high-quality Lanczos-scaled frames to an FFmpeg rawvideo encoder.
    Returns the path to a video file containing the perfectly tracked visual track (no audio).
    """
    cap = cv2.VideoCapture(input_video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0, seg_st * 1000))
    
    try:
        import mediapipe.python.solutions.face_detection as mp_face
        detector = mp_face.FaceDetection(model_selection=1, min_detection_confidence=0.4)
    except:
        detector = None

    cmd = [
        "ffmpeg", "-y", "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{target_w}x{target_h}", "-pix_fmt", "bgr24",
        "-r", str(fps), "-i", "-", 
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "17", "-pix_fmt", "yuv420p",
        temp_out
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    
    smooth_x = None
    frames_to_process = int((seg_et - seg_st) * fps) + 5
    
    frame_count = 0
    target_x = -1
    
    for _ in range(frames_to_process):
        ret, frame = cap.read()
        if not ret: break
        
        h, w = frame.shape[:2]
        crop_w = int(h * 9 / 16)
        crop_h = h
        
        if is_peak:
            # Zoom in by 1.2x
            crop_w = int(crop_w / 1.2)
            crop_h = int(crop_h / 1.2)
        
        if target_x == -1:
            target_x = w // 2 - crop_w // 2
            
        # Run detection every 3 frames to save CPU
        if detector and frame_count % 3 == 0:
            # Resize for speed
            small = cv2.resize(frame, (w//2, h//2))
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            res = detector.process(rgb)
            if res.detections:
                best = max(res.detections, key=lambda d: d.score[0])
                bbox = best.location_data.relative_bounding_box
                cx = int((bbox.xmin + bbox.width / 2) * w)
                target_x = max(0, min(w - crop_w, cx - (crop_w // 2)))
                
        if smooth_x is None:
            smooth_x = target_x
        else:
            # Exponential smoothing for buttery panning
            smooth_x = smooth_x * 0.90 + target_x * 0.10
            
        crop_x = int(smooth_x)
        # Center Y for peak zoom
        crop_y = (h - crop_h) // 2 if is_peak else 0
        
        cropped = frame[crop_y:crop_y+crop_h, crop_x:crop_x+crop_w]
        # Lanczos provides much better upscale sharpness than FFmpeg default
        resized = cv2.resize(cropped, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)
        
        try:
            proc.stdin.write(resized.tobytes())
        except:
            break
            
        frame_count += 1
        
    try:
        proc.stdin.close()
        proc.wait()
    except:
        pass
    cap.release()
    if detector: detector.close()
    return temp_out


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
        font_name = "Arial Black"
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
        font_name = "Arial Black"
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
        lines.append(f"Style: MagicHook,{font_name},110,&H0044FFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,8,6,8,10,10,150,1")

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
                 all_sentences=None, padding=3.0):

    ui_logger.log("Initializing render pipeline...")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)
    out_id = uuid.uuid4().hex[:8]
    import datetime
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    safe_title = "".join(c for c in clip_data.get("title", "Viral_Clip") if c.isalnum() or c in " _-").replace(" ", "_")
    final_output = os.path.join(output_dir, f"{date_str}_{safe_title}_{out_id}.mp4")

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

        # Apply user-requested padding for manual post-edit cropping
        base_st = max(0, base_st - padding)
        base_et = base_et + padding

        # ── Word-ID based exclusions (precise word-level cuts) ────────────
        # Sentence labels have format: "[WID:45-52] [12.3s] sentence text..."
        # We parse the WID range to get exact global word indices to exclude.
        import re as _re
        excluded_word_indices = set()
        if excluded_sentences:
            for ex_str in excluded_sentences:
                m = _re.match(r'\[WID:(\d+)-(\d+)\]', ex_str)
                if m:
                    wid_start = int(m.group(1))
                    wid_end = int(m.group(2))
                    excluded_word_indices.update(range(wid_start, wid_end + 1))

        block_words = []
        for wi, w in enumerate(word_timestamps):
            if w["start"] >= base_st - 0.5 and w["end"] <= base_et + 0.5:
                if wi not in excluded_word_indices:
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

        # ── Setup Video/Audio Inputs ──
        if face_center:
            ui_logger.log(f"Running OpenCV dynamic smooth tracking for segment...")
            dynamic_temp = os.path.join(work_dir, f"dyn_{out_id}_{idx}.mp4")
            _render_dynamic_crop(input_video, seg_st, seg_et, target_w, target_h, dynamic_temp, is_peak)
            
            inputs = ["-i", dynamic_temp]
            # Map audio from original video explicitly constrained to the clip duration to avoid infinite encoding
            inputs.extend(["-ss", str(seg_st), "-to", str(seg_et), "-i", input_video])
            audio_source = "1:a"
            
            # Subtle unsharp mask to recover detail without artificial grain
            filter_complex = "[0:v]unsharp=3:3:0.5[base];"
        else:
            inputs = ["-ss", str(seg_st), "-to", str(seg_et), "-i", input_video]
            audio_source = "0:a"
            
            crop_w, crop_h = "ih*9/16", "ih"
            crop_x, crop_y = "in_w/2-ih*9/32", "0"
            
            if is_peak:
                base_crop = f"crop=ih*9/16/1.2:ih/1.2:in_w/2-ih*9/32:0,scale={target_w}:{target_h}:flags=lanczos,unsharp=3:3:0.5"
            else:
                base_crop = f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={target_w}:{target_h}:flags=lanczos,unsharp=3:3:0.5"
                
            filter_complex = f"[0:v]{base_crop}[base];"

        current_v = "base"
        input_idx = 2 if face_center else 1
        sfx_delays = []
        for i_b, b in enumerate(broll_kws):
            if isinstance(b, str):
                b = {"keyword": b, "start_time": seg_st + i_b * 2.0}
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
        for i_e, e in enumerate(emoji_moms):
            if isinstance(e, str):
                e = {"emoji_unicode": e, "start_time": seg_st + i_e * 1.5}
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
            audio_filter = f"[{audio_source}]volume=1.0[a_base];"
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
            audio_map = audio_source

        seg_out = os.path.join(work_dir, f"seg_{out_id}_{idx}.mp4")

        cmd = ["ffmpeg", "-y"]
        if not face_center:
            cmd.extend(["-ss", str(seg_st), "-to", str(seg_et)])
            
        cmd.extend(inputs)
        
        # High quality encoding parameters, enforcing a hard end to prevent infinitely hanging processes
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", f"[{current_v}]", "-map", audio_map,
            "-c:v", "libx264", "-preset", "slow", "-crf", "14",
            "-profile:v", "high", "-pix_fmt", "yuv420p", "-x264opts", "keyint=30",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",  # Ensure encoding stops exactly when the video stream ends
            seg_out
        ])

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