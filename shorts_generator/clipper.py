import os
import subprocess
import uuid
import shutil
import cv2
import urllib.request
import re as _re

from shorts_generator.config import FONT_PATH
from shorts_generator.media import get_broll_image, get_twemoji, get_sfx
from .logger import ui_logger

# Ensure we have our premium font
if os.path.exists("/usr/share/fonts/truetype") and not os.path.exists(FONT_PATH):
    try:
        urllib.request.urlretrieve("https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Black.ttf", FONT_PATH)
        subprocess.run(["fc-cache", "-fv"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ui_logger.log("Premium font (Montserrat-Black) installed.")
    except:
        pass


# ── Silence Detection & Removal ──────────────────────────────────────────────

def _remove_silence_ffmpeg(input_path: str, output_path: str, noise_db: int = -30, min_silence_dur: float = 0.5) -> str:
    """
    Run FFmpeg silencedetect on a rendered segment, then re-cut to remove
    silent gaps, creating fast-paced jump-cut style delivery.
    Returns the path to the processed file (output_path or input_path if no silence found).
    """
    # Step 1: Detect silence intervals
    detect_cmd = [
        "ffmpeg", "-i", input_path,
        "-af", f"silencedetect=noise={noise_db}dB:d={min_silence_dur}",
        "-f", "null", "-"
    ]
    try:
        result = subprocess.run(detect_cmd, capture_output=True, text=True)
        stderr = result.stderr
    except Exception:
        return input_path

    # Step 2: Parse silence intervals from stderr
    silence_starts = []
    silence_ends = []
    for line in stderr.split("\n"):
        m_start = _re.search(r"silence_start:\s*([\d.]+)", line)
        m_end = _re.search(r"silence_end:\s*([\d.]+)", line)
        if m_start:
            silence_starts.append(float(m_start.group(1)))
        if m_end:
            silence_ends.append(float(m_end.group(1)))

    # Pair up silence intervals
    silence_intervals = list(zip(silence_starts, silence_ends[:len(silence_starts)]))
    
    # Only process if meaningful silence found (>= 0.5s gaps)
    meaningful = [(s, e) for s, e in silence_intervals if e - s >= min_silence_dur]
    if not meaningful:
        return input_path

    ui_logger.log(f"  Removing {len(meaningful)} silent gaps ({sum(e-s for s,e in meaningful):.1f}s total dead air)...")

    # Step 3: Build non-silent segments
    # Get video duration
    probe_cmd = ["ffmpeg", "-i", input_path, "-f", "null", "-"]
    try:
        probe_res = subprocess.run(probe_cmd, capture_output=True, text=True)
        dur_match = _re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", probe_res.stderr)
        if dur_match:
            total_dur = int(dur_match.group(1)) * 3600 + int(dur_match.group(2)) * 60 + float(dur_match.group(3))
        else:
            total_dur = 999
    except Exception:
        total_dur = 999

    # Build list of non-silent time ranges
    non_silent = []
    cursor = 0.0
    for s_start, s_end in sorted(meaningful):
        if s_start > cursor + 0.1:
            non_silent.append((cursor, s_start))
        cursor = s_end
    if cursor < total_dur - 0.1:
        non_silent.append((cursor, total_dur))

    if not non_silent or len(non_silent) < 1:
        return input_path

    # Step 4: Use FFmpeg select filter to keep only non-silent parts
    select_parts = "+".join(
        f"between(t\\,{s:.3f}\\,{e:.3f})" for s, e in non_silent
    )
    
    trim_cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"select='{select_parts}',setpts=N/FRAME_RATE/TB",
        "-af", f"aselect='{select_parts}',asetpts=N/SR/TB",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "17",
        "-c:a", "aac", "-b:a", "192k",
        output_path
    ]
    try:
        subprocess.run(trim_cmd, check=True, capture_output=True, text=True)
        return output_path
    except subprocess.CalledProcessError:
        return input_path

def _generate_dynamic_crop(source_video, seg_st, seg_et):
    """
    Samples the video every 2 seconds using MediaPipe face detection,
    records face center X/Y at each sample point, then generates an FFmpeg
    crop filter expression with linear interpolation between keypoints.

    Returns an FFmpeg crop expression string like:
      crop=CW:CH:X_EXPR:Y_EXPR

    where X_EXPR smoothly interpolates between detected face positions.
    If no face is found in any sample, returns a Ken Burns fallback
    (5% rightward drift over the segment duration).
    """
    cap = cv2.VideoCapture(source_video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    ret, probe_frame = cap.read()
    if not ret:
        cap.release()
        return None  # Caller will use static crop fallback

    src_h, src_w = probe_frame.shape[:2]
    # 9:16 crop dimensions from source height
    crop_w = int(src_h * 9 / 16)
    crop_h = src_h

    # Clamp crop_w to source width
    if crop_w > src_w:
        crop_w = src_w

    # ── Phase 1: Sample faces every 2 seconds using MediaPipe ──
    detector = None
    try:
        import mediapipe.python.solutions.face_detection as mp_face
        detector = mp_face.FaceDetection(model_selection=1, min_detection_confidence=0.4)
    except Exception:
        pass

    duration = seg_et - seg_st
    sample_interval = 2.0
    keypoints = []  # list of (relative_time, crop_x)

    if detector:
        t = 0.0
        while t <= duration:
            abs_t = seg_st + t
            cap.set(cv2.CAP_PROP_POS_MSEC, abs_t * 1000)
            ret, frame = cap.read()
            if not ret:
                break

            h, w = frame.shape[:2]
            # Resize for speed
            small = cv2.resize(frame, (w // 2, h // 2))
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            res = detector.process(rgb)

            if res.detections:
                best = max(res.detections, key=lambda d: d.score[0])
                bbox = best.location_data.relative_bounding_box
                face_cx = int((bbox.xmin + bbox.width / 2) * w)
                # Convert face center to crop X (top-left of crop window)
                cx = max(0, min(w - crop_w, face_cx - crop_w // 2))
                keypoints.append((t, cx))

            t += sample_interval

        detector.close()

    cap.release()

    # ── Phase 2: Build FFmpeg crop expression ──
    center_x = max(0, (src_w - crop_w) // 2)

    if not keypoints:
        # Ken Burns fallback: slow 5% rightward drift, never static
        ui_logger.log("  No face detected — applying subtle Ken Burns pan.")
        max_drift = int(src_w * 0.05)
        start_x = max(0, center_x - max_drift // 2)
        end_x = min(src_w - crop_w, start_x + max_drift)
        if duration > 0:
            x_expr = f"{start_x}+({end_x}-{start_x})*t/{duration:.2f}"
        else:
            x_expr = str(center_x)
        return f"crop={crop_w}:{crop_h}:{x_expr}:0"

    # Sort keypoints by time
    keypoints.sort(key=lambda k: k[0])

    # If only one keypoint, hold that position
    if len(keypoints) == 1:
        x_expr = str(keypoints[0][1])
        return f"crop={crop_w}:{crop_h}:{x_expr}:0"

    # Build piecewise linear interpolation using nested if(between(...))
    # Each segment: if between(t, t0, t1) then lerp(x0, x1, (t-t0)/(t1-t0))
    parts = []
    for i in range(len(keypoints) - 1):
        t0, x0 = keypoints[i]
        t1, x1 = keypoints[i + 1]
        dt = t1 - t0
        if dt <= 0:
            continue
        # Linear interpolation: x0 + (x1 - x0) * (t - t0) / dt
        lerp_expr = f"{x0}+({x1}-{x0})*(t-{t0:.2f})/{dt:.2f}"
        parts.append(f"between(t\\,{t0:.2f}\\,{t1:.2f})*({lerp_expr})")

    # Before first keypoint: hold first position
    first_t, first_x = keypoints[0]
    parts.insert(0, f"lt(t\\,{first_t:.2f})*{first_x}")

    # After last keypoint: hold last position
    last_t, last_x = keypoints[-1]
    parts.append(f"gte(t\\,{last_t:.2f})*{last_x}")

    x_expr = "+".join(parts)

    ui_logger.log(f"  Dynamic face tracking: {len(keypoints)} keypoints across {duration:.1f}s")
    return f"crop={crop_w}:{crop_h}:{x_expr}:0"


def _generate_ass(words, out_path, video_w, video_h, time_offset=0, theme="Storytime", style_mode="Hormozi", position="Center", **kwargs):
    # Hardcoded CapCut Style
    font_name = FONT_PATH.replace("\\", "/").replace(":", "\\:") if FONT_PATH else "Montserrat-Bold"
    font_size = 55
    p = {"main": "&H00FFFFFF", "high": "&H0000FFFF"} # Yellow highlight
    bold = 1
    outline = 3
    shadow = 0

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

        for i, w in enumerate(chunk):
            w_st = max(0, w["start"] - time_offset)
            w_et = max(0, w["end"] - time_offset)
            if w_et <= w_st: continue

            fade_in = 150 if i == 0 else 0
            fade_out = 150 if i == len(chunk) - 1 else 0
            fade_tag = f"{{\\fad({fade_in},{fade_out})}}"

            styled = fade_tag
            for x in chunk:
                txt = x['word'].strip()
                txt = txt.upper()
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

    # ── Guarantee Montserrat-Bold font exists on Colab ──
    global FONT_PATH
    _font_url = "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Bold.ttf"
    _colab_font = "/content/work/Montserrat-Bold.ttf"
    if not os.path.exists(FONT_PATH):
        os.makedirs(os.path.dirname(_colab_font), exist_ok=True)
        try:
            urllib.request.urlretrieve(_font_url, _colab_font)
            FONT_PATH = _colab_font
            ui_logger.log(f"Downloaded Montserrat-Bold to {_colab_font}")
        except Exception as _fe:
            ui_logger.log(f"Font download failed ({_fe}), using system fallback.")
    if os.path.exists(_colab_font):
        FONT_PATH = _colab_font
    out_id = uuid.uuid4().hex[:8]
    import datetime
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    safe_title = "".join(c for c in clip_data.get("title", "Viral_Clip") if c.isalnum() or c in " _-").replace(" ", "_")
    final_output = os.path.join(output_dir, f"{date_str}_{safe_title}_{out_id}.mp4")

    target_w, target_h = 1080, 1920

    # ── Build segments from clip_data ────────────────────────────────────────
    # New schema: all clips have a "segments" array. Legacy clips fall back to start_time/end_time.
    raw_segments = clip_data.get("segments", [])
    if raw_segments and len(raw_segments) > 0:
        # Multi-segment clip (from Opus-style LLM output)
        ui_logger.log(f"Multi-segment clip: rendering {len(raw_segments)} segments...")
        block_words = []
        for seg in raw_segments:
            seg_st = float(seg["start_time"])
            seg_et = float(seg["end_time"])
            block_words.extend([w for w in word_timestamps if seg_st - 0.5 <= w["start"] <= seg_et + 0.5])
        segments = [{"start_time": float(s["start_time"]), "end_time": float(s["end_time"])}
                    for s in raw_segments]
    else:
        # ── Legacy single-range clip ──────────────────────────────────────────
        base_st = float(override_start) if override_start is not None else float(clip_data.get("start_time", 0))
        base_et = float(override_end) if override_end is not None else float(clip_data.get("end_time", 0))

        # Apply user-requested padding for manual post-edit cropping
        base_st = max(0, base_st - padding)
        base_et = base_et + padding

        # ── Word-ID based exclusions (precise word-level cuts) ────────────
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
        inputs = ["-ss", str(seg_st), "-to", str(seg_et), "-i", input_video]
        audio_source = "0:a"
        
        # ── Dynamic Face-Tracking Crop (MediaPipe interpolation) ──
        if face_center:
            dynamic_crop = _generate_dynamic_crop(input_video, seg_st, seg_et)
            if dynamic_crop:
                # Dynamic crop produces native-res crop, then scale to 1080x1920
                base_crop = f"{dynamic_crop},scale={target_w}:{target_h}:force_original_aspect_ratio=increase,crop={target_w}:{target_h},setsar=1"
            else:
                base_crop = f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,crop={target_w}:{target_h},setsar=1"
        else:
            # Static center crop fallback
            base_crop = f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,crop={target_w}:{target_h},setsar=1"
        
        filter_complex = f"[0:v]{base_crop},unsharp=3:3:0.5[base];"

        current_v = "base"
        input_idx = 1
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
            mh_text = clip_data.get("hook_sentence") if (magic_hook and idx == 0) else None
            safe_font = FONT_PATH.replace("\\", "/").replace(":", "\\:")
            
            if mh_text:
                safe_hook = mh_text.upper().replace("'", "\u2019").replace(":", "\\:").replace("\\", "/")
                next_v = f"v{input_idx}_hook"
                hook_y = "h*0.15"
                filter_complex += (
                    f"[{current_v}]drawtext=fontfile='{safe_font}'"
                    f":text='{safe_hook}'"
                    f":fontsize=80"
                    f":fontcolor=0xFFFF00"
                    f":box=1:boxcolor=black@0.8:boxborderw=20:borderw=0"
                    f":x=(w-text_w)/2:y={hook_y}"
                    f":enable='between(t,0,2.5)'"
                    f"[{next_v}];"
                )
                current_v = next_v
                input_idx += 1

            ass_path = os.path.join(work_dir, f"subs_{out_id}_{idx}.ass")
            _generate_ass(seg_words, ass_path, target_w, target_h, time_offset=seg_st, theme=theme, style_mode=caption_style, position=caption_pos)
            safe_ass = ass_path.replace("\\", "/").replace(":", "\\:")
            next_v = f"v{input_idx}_ass"
            filter_complex += f"[{current_v}]ass='{safe_ass}'[{next_v}];"
            current_v = next_v
            input_idx += 1
            
        if idx > 0:
            next_v = f"v{input_idx}_flash"
            filter_complex += f"[{current_v}]drawbox=w=iw:h=ih:color=white:t=fill:enable='between(t,0,0.10)'[{next_v}];"
            current_v = next_v
            input_idx += 1

        filter_complex += f";[{current_v}]setpts=PTS-STARTPTS[v_out]"
        current_v = "v_out"
        filter_complex = filter_complex.replace(";;", ";").rstrip(';')

        audio_filter = ""
        if sfx_delays:
            audio_filter = f"[{audio_source}]volume=1.0[a_base];"
            amix_inputs = "[a_base]"
            for i, delay_sec in enumerate(sfx_delays):
                sfx_idx = input_idx + i
                delay_ms = max(0, int(delay_sec * 1000))
                audio_filter += f"[{sfx_idx}:a]adelay={delay_ms}|{delay_ms},volume=0.6[sfx_{i}];"
                amix_inputs += f"[sfx_{i}]"
            audio_filter += f"{amix_inputs}amix=inputs={len(sfx_delays)+1}:duration=first,asetpts=PTS-STARTPTS[a_out]"
            audio_map = "[a_out]"
            filter_complex += f";{audio_filter}"
        else:
            filter_complex += f";[{audio_source}]asetpts=PTS-STARTPTS[a_out]"
            audio_map = "[a_out]"

        seg_out = os.path.join(work_dir, f"seg_{out_id}_{idx}.mp4")

        cmd = ["ffmpeg", "-y"]
        if not face_center:
            cmd.extend(["-ss", str(seg_st), "-to", str(seg_et)])
            
        cmd.extend(inputs)
        
        # High quality encoding parameters, enforcing a hard end to prevent infinitely hanging processes
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", f"[{current_v}]", "-map", audio_map,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-profile:v", "high", "-pix_fmt", "yuv420p", "-x264opts", "keyint=30",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",  # Ensure encoding stops exactly when the video stream ends
            seg_out
        ])

        ui_logger.log(f"PROGRESS|0|Rendering segment {idx+1}...")
        try:
            proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True)
            import re as _re_ffmpeg
            total_time_secs = seg_et - seg_st
            for line in proc.stderr:
                m = _re_ffmpeg.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
                if m and total_time_secs > 0:
                    h, m_m, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
                    cur_secs = h*3600 + m_m*60 + s
                    pct = min(99, int((cur_secs / total_time_secs) * 100))
                    ui_logger.log(f"PROGRESS|{pct}|Rendering {pct}%...")
            proc.wait()
            if proc.returncode != 0:
                raise subprocess.CalledProcessError(proc.returncode, cmd, stderr="FFmpeg failed")
            ui_logger.log(f"PROGRESS|100|Rendering 100%...")
        except subprocess.CalledProcessError as e:
            ui_logger.log(f"FFmpeg error: {e.stderr[-500:] if hasattr(e, 'stderr') and e.stderr else 'unknown'}")
            raise

        # ── Post-render silence removal pass ──
        if remove_silence:
            desilenced = os.path.join(work_dir, f"desil_{out_id}_{idx}.mp4")
            seg_out = _remove_silence_ffmpeg(seg_out, desilenced)
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

    # ── LLM-Driven BGM Mixing (music_query from highlights) ──
    music_query = clip_data.get("music_query", "")
    if music_query:
        try:
            from shorts_generator.music_fetcher import fetch_music
            bgm_path = os.path.join(work_dir, f"bgm_{out_id}.mp3")
            bgm_path = fetch_music(music_query, bgm_path)
            if bgm_path and os.path.exists(bgm_path):
                ui_logger.log(f"Mixing LLM-selected BGM (query: '{music_query}')...")
                bgm_output = final_output.replace(".mp4", "_bgm.mp4")
                bgm_cmd = [
                    "ffmpeg", "-y",
                    "-i", final_output,
                    "-stream_loop", "-1",
                    "-i", bgm_path,
                    "-filter_complex",
                    "[0:a]volume=0.5[speech];[1:a]volume=0.1[bgm];[speech][bgm]amix=inputs=2:duration=first:dropout_transition=2[a]",
                    "-map", "0:v", "-map", "[a]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-shortest",
                    bgm_output
                ]
                subprocess.run(bgm_cmd, check=True, capture_output=True, text=True)
                shutil.move(bgm_output, final_output)
                ui_logger.log("BGM mixed successfully.")
        except Exception as bgm_err:
            ui_logger.log(f"LLM BGM mixing failed ({bgm_err}) — clip saved without AI music.")

    ui_logger.log(f"Render complete: {os.path.basename(final_output)}")
    return final_output
