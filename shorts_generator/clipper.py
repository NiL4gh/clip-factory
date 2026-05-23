import os
import subprocess
import uuid
import shutil
import cv2
import urllib.request
import re as _re
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

from shorts_generator.config import FONT_PATH
from shorts_generator.media import get_broll_image, get_twemoji, get_sfx
from .logger import ui_logger

_DETECTED_ENCODER = None

def _get_best_encoder():
    global _DETECTED_ENCODER
    if _DETECTED_ENCODER is not None:
        return _DETECTED_ENCODER

    _DETECTED_ENCODER = "libx264"
    try:
        res = subprocess.run(["ffmpeg", "-encoders"], capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and "h264_nvenc" in res.stdout:
            test_cmd = [
                "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.1",
                "-c:v", "h264_nvenc", "-f", "null", "-"
            ]
            test_res = subprocess.run(test_cmd, capture_output=True, timeout=5)
            if test_res.returncode == 0:
                _DETECTED_ENCODER = "h264_nvenc"
                ui_logger.log("⚡ Nvidia NVENC GPU hardware acceleration detected and enabled!")
    except Exception:
        pass

    return _DETECTED_ENCODER

# Ensure we have our premium font (Montserrat-Bold) available on Colab
_FONT_DIR  = "/content/work"
_FONT_FILE = "Montserrat-Bold.ttf"
_FONT_URL  = "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Bold.ttf"
os.makedirs(_FONT_DIR, exist_ok=True)
if not os.path.exists(os.path.join(_FONT_DIR, _FONT_FILE)):
    try:
        urllib.request.urlretrieve(_FONT_URL, os.path.join(_FONT_DIR, _FONT_FILE))
        subprocess.run(["fc-cache", "-fv"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        pass


# ── Silence Detection & Removal ──────────────────────────────────────────────

def _remove_silence_ffmpeg(input_path: str, output_path: str, noise_db: int = -30, min_silence_dur: float = 0.5) -> str:
    """
    Run FFmpeg silencedetect on a rendered segment, then re-cut to remove
    silent gaps, creating fast-paced jump-cut style delivery.
    Returns the path to the processed file (output_path or input_path if no silence found).
    """
    # Dynamically calculate FFmpeg silencedetect parameters by evaluating relative sound levels
    try:
        import librosa
        import numpy as np
        temp_wav = input_path.replace(".mp4", "_rms.wav")
        try:
            subprocess.run([
                "ffmpeg", "-y", "-i", input_path, "-vn",
                "-ar", "16000", "-ac", "1", temp_wav
            ], capture_output=True, check=True)
            y, sr = librosa.load(temp_wav, sr=16000)
            rms = librosa.feature.rms(y=y)[0]
            rms_db = librosa.power_to_db(rms, ref=np.max)
            mean_db = np.mean(rms_db)
            dynamic_db = float(mean_db - 12.0)
            noise_db = int(max(-45.0, min(-20.0, dynamic_db)))
            ui_logger.log(f"  Dynamic silence threshold calculated: {noise_db} dB (mean RMS db: {mean_db:.1f})")
        except Exception as e:
            ui_logger.log(f"  Dynamic silence calculation failed ({e}), using fallback {noise_db} dB")
        finally:
            if os.path.exists(temp_wav):
                try:
                    os.remove(temp_wav)
                except OSError:
                    pass
    except ImportError:
        ui_logger.log(f"  librosa or numpy missing, using default silence threshold {noise_db} dB")

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
    
    encoder = _get_best_encoder()
    enc_args = ["-c:v", encoder]
    if encoder == "h264_nvenc":
        enc_args.extend(["-preset", "fast"])
    else:
        enc_args.extend(["-preset", "fast", "-crf", "16"])

    trim_cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"select='{select_parts}',setpts=N/FRAME_RATE/TB",
        "-af", f"aselect='{select_parts}',asetpts=N/SR/TB",
    ] + enc_args + [
        "-profile:v", "high", "-pix_fmt", "yuv420p",
    ]
    if encoder == "libx264":
        trim_cmd.extend(["-x264opts", "keyint=30"])

    trim_cmd.extend([
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        output_path
    ])
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
        detector = mp_face.FaceDetection(model_selection=0, min_detection_confidence=0.3)
    except Exception:
        pass

    duration = seg_et - seg_st
    sample_interval = 2.0
    keypoints = []  # list of (relative_time, crop_x)

    if detector:
        t = 0.0
        frame_idx = 0
        while t <= duration:
            abs_t = seg_st + t
            cap.set(cv2.CAP_PROP_POS_MSEC, abs_t * 1000)
            ret, frame = cap.read()
            if not ret:
                break

            h, w = frame.shape[:2]
            # Resize aggressively smaller (max width 320) for 10x faster CPU processing in MediaPipe
            target_scale_w = 320
            scale_factor = target_scale_w / w
            target_scale_h = int(h * scale_factor)
            small = cv2.resize(frame, (target_scale_w, target_scale_h))
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            res = detector.process(rgb)

            if res.detections:
                best = max(res.detections, key=lambda d: d.score[0])
                bbox = best.location_data.relative_bounding_box
                face_cx = int((bbox.xmin + bbox.width / 2) * w)
                # Convert face center to crop X (top-left of crop window)
                cx = max(0, min(w - crop_w, face_cx - crop_w // 2))
                keypoints.append((t, cx))

            frame_idx += 1
            if frame_idx >= 3 and not keypoints:
                # If no face is found after checking the first 3 frames, force static crop
                keypoints.append((0.0, center_x))
                break

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
        # Half-open interval [t0, t1) — exactly one segment active at any t
        lerp_expr = f"{x0}+({x1}-{x0})*min((t-{t0:.2f})/0.20,1)"
        parts.append(f"gte(t\\,{t0:.2f})*lt(t\\,{t1:.2f})*({lerp_expr})")

    # Before first keypoint: hold first detected position
    first_t, first_x = keypoints[0]
    parts.insert(0, f"lt(t\\,{first_t:.2f})*{first_x}")

    # At and after last keypoint: hold last detected position (half-open end)
    last_t, last_x = keypoints[-1]
    parts.append(f"gte(t\\,{last_t:.2f})*{last_x}")

    x_expr = "+".join(parts)

    ui_logger.log(f"  Dynamic face tracking: {len(keypoints)} keypoints across {duration:.1f}s")
    return f"crop={crop_w}:{crop_h}:{x_expr}:0"


# ── CapCut-Style Presets ─────────────────────────────────────────────────────
_CAPTION_STYLES = {
    "Classic": {"font_size": 88,  "primary": "&H00FFFFFF&", "highlight": "&H0000FFFF&", "outline": 4, "shadow": 2, "bold": 1},
    "Pop":     {"font_size": 95,  "primary": "&H00FFFFFF&", "highlight": "&H00FF00FF&", "outline": 4, "shadow": 2, "bold": 1},
    "Glow":    {"font_size": 88,  "primary": "&H00FFFFFF&", "highlight": "&H00FF00FF&", "outline": 2, "shadow": 8, "bold": 1},
    "Outline": {"font_size": 92,  "primary": "&H00FFFFFF&", "highlight": "&H0000FF00&", "outline": 5, "shadow": 0, "bold": 1},
    "Minimal": {"font_size": 72,  "primary": "&H00FFFFFF&", "highlight": "&H00FFFFFF&", "outline": 1, "shadow": 0, "bold": 0},
    "Fire":    {"font_size": 90,  "primary": "&H0000FFFF&", "highlight": "&H000080FF&", "outline": 4, "shadow": 2, "bold": 1},
}

def _generate_ass(words, out_path, video_w, video_h, time_offset=0, theme="Storytime", style_mode="Classic", position="Center", **kwargs):
    # Resolve style preset — fall back to Classic if unknown
    # Resolve style preset — returns a dict with all style attributes
    style = _CAPTION_STYLES.get(style_mode, _CAPTION_STYLES["Classic"])
    font_size = style["font_size"]
    main_color = style["primary"]
    high_color = style["highlight"]
    outline = style["outline"]
    shadow = style["shadow"]
    bold = style["bold"]
    font_name = "Montserrat"
    p = {"main": main_color, "high": high_color}

    align_map = {"Top": 8, "Center": 5, "Bottom": 2}
    align = align_map.get(position, 2)  # Default Bottom — CapCut style

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {video_w}",
        f"PlayResY: {video_h}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Main,{font_name},{font_size},{p['main']},&H000000FF,&H00000000,&H80000000,{bold},0,0,0,100,100,1,0,1,{outline},{shadow},{align},40,40,360,1",
        f"Style: Highlight,{font_name},{font_size},{p['high']},&H000000FF,&H00000000,&H80000000,{bold},0,0,0,100,100,1,0,1,{outline},{shadow},{align},40,40,360,1",
        f"Style: Header,{font_name},64,&H00FFFFFF&,&H000000FF&,&H00000000&,&H80000000&,1,0,0,0,100,100,0,0,1,5,2,8,40,40,180,1"
    ]
    
    if kwargs.get("magic_hook_text"):
        lines.append(f"Style: MagicHook,{font_name},64,&H0044FFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,3,4,3,8,40,40,120,1")

    lines.extend([
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    ])
    
    if kwargs.get("magic_hook_text"):
        hook_text = kwargs['magic_hook_text']
        words_list = hook_text.split()
        current_line = ""
        wrapped_lines = []
        for word in words_list:
            if len(current_line) + len(word) + (1 if current_line else 0) > 22:
                wrapped_lines.append(current_line)
                current_line = word
            else:
                if current_line:
                    current_line += " " + word
                else:
                    current_line = word
        if current_line:
            wrapped_lines.append(current_line)
        wrapped_text = "\\N".join(wrapped_lines).upper()
        lines.append(f"Dialogue: 0,0:00:00.00,0:00:02.50,MagicHook,,0,0,0,,{wrapped_text}")

    def fmt_time(secs):
        h = int(secs // 3600); m = int((secs % 3600) // 60); s = int(secs % 60); cs = int((secs - int(secs)) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    seg_duration = max(0, words[-1]['end'] - time_offset) if words else 0.0
    if kwargs.get("header_text") and seg_duration > 0:
        header_text = kwargs["header_text"].strip().upper()
        # Wrap header text to 2 lines if it is too long (e.g. > 20 characters)
        words_list = header_text.split()
        current_line = ""
        wrapped_lines = []
        for word in words_list:
            if len(current_line) + len(word) + (1 if current_line else 0) > 20:
                wrapped_lines.append(current_line)
                current_line = word
            else:
                if current_line:
                    current_line += " " + word
                else:
                    current_line = word
        if current_line:
            wrapped_lines.append(current_line)
        wrapped_header = "\\N".join(wrapped_lines)
        lines.append(f"Dialogue: 0,0:00:00.00,{fmt_time(seg_duration)},Header,,0,0,0,,{wrapped_header}")

    chunks = []
    curr = []
    for w in words:
        # Enforce strict word wrapping of max 3 words per line
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
            fade_tag = f"{{\fad({fade_in},{fade_out})}}"

            styled = fade_tag
            hl_color = style["highlight"]
            main_color = style["primary"]
            for x in chunk:
                txt = x['word'].strip()
                txt = txt.upper()
                if x == w:
                    styled += f"{{\\c{hl_color}\\fscx120\\fscy120}}{txt}{{\\c{main_color}\\fscx100\\fscy100}} "
                else:
                    styled += f"{txt} "

            lines.append(f"Dialogue: 0,{fmt_time(w_st)},{fmt_time(w_et)},Main,,0,0,0,,{styled.strip()}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _generate_text_card(output_path, text, duration, font_file, font_size=64):
    safe_text = text.replace("'", "").replace(":", "")
    vf_filter = f"drawtext=text='{safe_text}':fontcolor=white:fontsize={font_size}:x=(w-text_w)/2:y=(h-text_h)/2"
    if font_file and os.path.exists(font_file):
        safe_font = font_file.replace("\\", "/").replace(":", "\\:")
        vf_filter = f"drawtext=fontfile='{safe_font}':text='{safe_text}':fontcolor=white:fontsize={font_size}:x=(w-text_w)/2:y=(h-text_h)/2"
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s=1080x1920:r=30:d={duration}",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-vf", vf_filter,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "16",
        "-profile:v", "high", "-pix_fmt", "yuv420p", "-x264opts", "keyint=30",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        output_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)

def render_short(input_video, clip_data, word_timestamps, output_dir, work_dir,
                 face_center=True, add_subs=True, theme="Storytime", 
                 caption_style="Classic", caption_pos="Bottom",
                 override_start=None, override_end=None, excluded_sentences=None,
                 magic_hook=False, remove_silence=True, broll_intensity="Medium",
                 all_sentences=None, padding=3.0):

    ui_logger.log("Initializing render pipeline...")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)

    # ── Guarantee Montserrat-Bold font exists in /content/work ──
    _colab_font = os.path.join(_FONT_DIR, _FONT_FILE)
    if not os.path.exists(_colab_font):
        try:
            urllib.request.urlretrieve(_FONT_URL, _colab_font)
            subprocess.run(["fc-cache", "-fv"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            ui_logger.log(f"Downloaded Montserrat-Bold to {_colab_font}")
        except Exception as _fe:
            ui_logger.log(f"Font download failed: {_fe}")
    if os.path.exists(_colab_font):
        ui_logger.log(f"Montserrat-Bold font ready at {_colab_font}")
        # Refresh fontconfig cache so libass finds the font at render time
        subprocess.run(["fc-cache", "-fv"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=10)
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
        
        filter_complex = f"[0:v]{base_crop}[base];"

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
                    # FIX: tightened y expression — no spaces, added parens for correct precedence
                    filter_complex += f"[{current_v}][emoji{input_idx}]overlay=x='W-w-50':y='H-h-300+100*max(0,(0.2-(t-{rel_st}))/0.2)':enable='between(t,{rel_st},{rel_et})'[{next_v}];"
                    current_v = next_v
                    input_idx += 1

        sfx_path = os.path.join(work_dir, "pop.mp3")
        if sfx_delays:
            sfx_ok = get_sfx(sfx_path) and os.path.exists(sfx_path)
            if not sfx_ok:
                ui_logger.log("SFX download failed — skipping pop sounds (clip will still render).")
                sfx_delays = []  # clear so audio filter is skipped safely
            else:
                for delay in sfx_delays:
                    inputs.extend(["-i", sfx_path])

        # FIX: snapshot the SFX starting index NOW, before ASS subtitles and
        # flash drawbox increment input_idx for non-input filter operations.
        # Previously sfx_idx = input_idx + i pointed to a ghost index because
        # ASS and flash each did input_idx += 1 without adding a real -i input.
        sfx_start_idx = input_idx

        seg_words = [w for w in block_words if w["start"] >= seg_st - 0.2 and w["end"] <= seg_et + 0.2]
        if add_subs and seg_words:
            mh_text = clip_data.get("hook_sentence") if (magic_hook and idx == 0) else None
            safe_font = os.path.join(_FONT_DIR, _FONT_FILE).replace("\\", "/").replace(":", "\\:")

            ass_path = os.path.join(work_dir, f"subs_{out_id}_{idx}.ass")
            _generate_ass(seg_words, ass_path, target_w, target_h, time_offset=seg_st,
                          theme=theme, style_mode=caption_style, position=caption_pos,
                          magic_hook_text=mh_text, header_text=clip_data.get("title", ""))
            safe_ass = ass_path.replace("\\", "/").replace(":", "\\:")
            next_v = f"v{input_idx}_ass"
            safe_fonts_dir = _FONT_DIR.replace("\\", "/").replace(":", "\\:")
            filter_complex += f"[{current_v}]ass='{safe_ass}':fontsdir='{safe_fonts_dir}'[{next_v}];"
            current_v = next_v
            input_idx += 1
            
        if idx > 0:
            next_v = f"v{input_idx}_flash"
            filter_complex += f"[{current_v}]drawbox=w=iw:h=ih:color=white:t=fill:enable='between(t,0,0.10)'[{next_v}];"
            current_v = next_v
            input_idx += 1

        filter_complex += f";[{current_v}]eq=saturation=1.25:gamma=0.95:contrast=1.15:brightness=0.02,vignette,setpts=PTS-STARTPTS[v_out]"
        current_v = "v_out"
        filter_complex = filter_complex.replace(";;", ";").rstrip(';')

        # Apply loudnorm to base speech audio to normalize speaker energy to -16 LUFS
        filter_complex += f";[{audio_source}]loudnorm=I=-16:TP=-1.5:LRA=11[a_norm]"
        audio_source_norm = "a_norm"

        audio_filter = ""
        if sfx_delays:
            audio_filter = f"[{audio_source_norm}]volume=1.0[a_base];"
            amix_inputs = "[a_base]"
            for i, delay_sec in enumerate(sfx_delays):
                # FIX: use sfx_start_idx (captured before ASS/flash bumped input_idx)
                sfx_idx = sfx_start_idx + i
                delay_ms = max(0, int(delay_sec * 1000))
                audio_filter += f"[{sfx_idx}:a]adelay={delay_ms}|{delay_ms},volume=0.6[sfx_{i}];"
                amix_inputs += f"[sfx_{i}]"
            audio_filter += f"{amix_inputs}amix=inputs={len(sfx_delays)+1}:duration=first,asetpts=PTS-STARTPTS[a_out]"
            audio_map = "[a_out]"
            filter_complex += f";{audio_filter}"
        else:
            filter_complex += f";[{audio_source_norm}]asetpts=PTS-STARTPTS[a_out]"
            audio_map = "[a_out]"

        seg_out = os.path.join(work_dir, f"seg_{out_id}_{idx}.mp4")

        cmd = ["ffmpeg", "-y"]
        if not face_center:
            cmd.extend(["-ss", str(seg_st), "-to", str(seg_et)])
            
        cmd.extend(inputs)
        
        encoder = _get_best_encoder()
        enc_args = ["-c:v", encoder]
        if encoder == "h264_nvenc":
            enc_args.extend(["-preset", "fast"])
        else:
            enc_args.extend(["-preset", "fast", "-crf", "16"])

        # High quality encoding parameters, enforcing a hard end to prevent infinitely hanging processes
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", f"[{current_v}]", "-map", audio_map,
        ] + enc_args + [
            "-profile:v", "high", "-pix_fmt", "yuv420p",
        ])
        if encoder == "libx264":
            cmd.extend(["-x264opts", "keyint=30"])

        cmd.extend([
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart",
            "-t", str(round(seg_et - seg_st, 3)),  # Explicit duration — prevents looped B-roll inputs from truncating segment
            seg_out
        ])

        ui_logger.log(f"PROGRESS|0|Rendering segment {idx+1}...")
        try:
            proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True)
            import re as _re_ffmpeg
            total_time_secs = seg_et - seg_st
            last_pct = -1
            stderr_lines = []
            for line in proc.stderr:
                stderr_lines.append(line)
                m = _re_ffmpeg.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
                if m and total_time_secs > 0:
                    h, m_m, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
                    cur_secs = h*3600 + m_m*60 + s
                    pct = min(99, int((cur_secs / total_time_secs) * 100))
                    if pct > last_pct:
                        ui_logger.log(f"PROGRESS|{pct}|Rendering {pct}%...")
                        last_pct = pct
            proc.wait()
            if proc.returncode != 0:
                err_msg = "".join(stderr_lines[-20:])  # last 20 lines of stderr
                ui_logger.log(f"FFmpeg error details:\n{err_msg}")
                raise subprocess.CalledProcessError(proc.returncode, cmd, stderr=err_msg)
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
    # Prepend 0.5s opening title card and append 1.5s outro CTA card
    try:
        open_card_path = os.path.join(work_dir, f"open_{out_id}.mp4")
        title_text = clip_data.get("title", "Viral Clip").upper()
        _generate_text_card(open_card_path, title_text, 0.5, _colab_font, font_size=60)
        
        end_card_path = os.path.join(work_dir, f"end_{out_id}.mp4")
        _generate_text_card(end_card_path, "FOLLOW FOR MORE!", 1.5, _colab_font, font_size=70)
        
        rendered_segs = [open_card_path] + rendered_segs + [end_card_path]
    except Exception as card_err:
        ui_logger.log(f"  Warning: Title/End card generation failed ({card_err}), continuing without them.")

    if len(rendered_segs) == 1:
        shutil.copy2(rendered_segs[0], final_output)
    else:
        n_segs = len(rendered_segs)
        fc_inputs = []
        for s in rendered_segs:
            fc_inputs.extend(["-i", s])
        
        # Apply fps and setsar normalization to every segment before concatenating 
        # to prevent FFmpeg hangs from frame-rate/timebase mismatches
        fc_str = ""
        for i in range(n_segs):
            fc_str += f"[{i}:v]fps=30,settb=1/30,setsar=1[v{i}];"
        fc_str += (
            "".join(f"[v{i}][{i}:a]" for i in range(n_segs))
            + f"concat=n={n_segs}:v=1:a=1[v_concat_raw][a_concat_raw];[v_concat_raw]setpts=PTS-STARTPTS[v_concat];[a_concat_raw]asetpts=PTS-STARTPTS[a_concat]"
        )

        encoder = _get_best_encoder()
        enc_args = ["-c:v", encoder]
        if encoder == "h264_nvenc":
            enc_args.extend(["-preset", "fast"])
        else:
            enc_args.extend(["-preset", "fast", "-crf", "16"])

        concat_cmd = ["ffmpeg", "-y"] + fc_inputs + [
            "-filter_complex", fc_str,
            "-map", "[v_concat]", "-map", "[a_concat]",
        ] + enc_args + [
            "-profile:v", "high", "-pix_fmt", "yuv420p",
        ]
        if encoder == "libx264":
            concat_cmd.extend(["-x264opts", "keyint=30"])

        concat_cmd.extend([
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart",
            final_output
        ])
        try:
            subprocess.run(concat_cmd, check=True, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            ui_logger.log("FFmpeg concat timed out after 60s!")
            raise RuntimeError("FFmpeg concatenation timed out due to segment stream mismatch.")
        except subprocess.CalledProcessError as e:
            ui_logger.log(f"FFmpeg concat error: {e.stderr[-500:]}")
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
                    "[0:a]volume=0.56[speech];[1:a]volume=0.1[bgm];[speech][bgm]amix=inputs=2:duration=first:dropout_transition=2,asetpts=PTS-STARTPTS[a]",
                    "-map", "0:v", "-map", "[a]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                    "-movflags", "+faststart",
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
