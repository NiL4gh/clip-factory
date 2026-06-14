import os
import subprocess
import textwrap
import uuid
import shutil
import cv2
import urllib.request
import re as _re
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

from shorts_generator.config import FONT_PATH, AVAILABLE_FONTS, FONT_DIR
from shorts_generator.media import get_broll_image, get_twemoji, get_sfx
from shorts_generator import overlays as _overlays
from .logger import ui_logger, get_logger

def get_font_path(element_type: str, font_choice: str) -> str:
    """element_type: 'header' | 'caption' | 'hook'"""
    choice = font_choice.lower().strip() if font_choice else 'bebas'
    if choice not in AVAILABLE_FONTS:
        choice = 'bebas'
    
    font_file = AVAILABLE_FONTS.get(choice)
    # Fallback to 'bebas' if the requested file doesn't exist
    if not font_file or not os.path.exists(font_file):
        if choice != 'bebas':
            choice = 'bebas'
            font_file = AVAILABLE_FONTS.get(choice)
            
    if not font_file or not os.path.exists(font_file):
        raise FileNotFoundError(f"Font {font_choice} not found at {font_file}. Place .ttf files in work/fonts/")
    return str(font_file)

def _family_name_from_file(path: str) -> str:
    """Read a TTF's real internal family name so libass always matches it.
    Falls back to 'Bebas Neue' (the always-present shipped font) on any error."""
    try:
        from PIL import ImageFont
        return ImageFont.truetype(str(path)).getname()[0]
    except Exception:
        return "Bebas Neue"

def get_font_family(font_choice: str) -> str:
    # get_font_path already falls back to bebas if the requested file is missing
    path = get_font_path("caption", font_choice)
    return _family_name_from_file(path)

def validate_input_quality(video_path: str, session_id: str = "global") -> dict:
    """Check input resolution and warn if below 1080p using ffprobe"""
    import subprocess
    import json
    logger = get_logger(session_id)
    
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,bit_rate",
        "-of", "json",
        video_path
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        probe = json.loads(proc.stdout)
        stream = probe.get("streams", [{}])[0]
        width = int(stream.get("width", 0))
        height = int(stream.get("height", 0))
        bitrate = stream.get("bit_rate", "unknown")
        
        if height > 0 and height < 1080:
            logger.logger.warning(f"Input video is {width}x{height}, upscaling to 1080p may reduce quality")
            
        return {"width": width, "height": height, "bitrate": bitrate}
    except Exception as e:
        logger.logger.warning(f"validate_input_quality probe failed: {e}")
        return {"width": 0, "height": 0, "bitrate": "unknown"}

def run_ffmpeg_with_logging(session_id: str, cmd: list, stage: str):
    logger = get_logger(session_id)
    logger.log_app_event(stage, 'ffmpeg_started', {'command': ' '.join(cmd[:10]) + '...'})
    
    import time
    start = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    duration = time.time() - start
    
    logger.log_ffmpeg(
        command=' '.join(cmd),
        return_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        duration_sec=duration
    )
    
    if proc.returncode != 0:
        logger.log_app_event(stage, 'failed', {}, error=proc.stderr[-500:])
        raise RuntimeError(f'FFmpeg failed at {stage}: {proc.stderr[-200:]}')
    
    logger.log_app_event(stage, 'completed', {'duration_sec': duration})
    return proc

def run_ffmpeg(cmd: list, session_id: str = "global", stage: str = "ffmpeg", check: bool = False, **kwargs):
    logger = get_logger(session_id)
    logger.log_app_event(stage, 'ffmpeg_started', {'command': ' '.join(cmd[:10]) + '...'})
    
    import time
    start = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    duration = time.time() - start
    
    logger.log_ffmpeg(
        command=' '.join(cmd),
        return_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        duration_sec=duration
    )
    if proc.returncode != 0:
        logger.log_app_event(stage, 'failed', {}, error=proc.stderr[-500:])
        if check:
            raise subprocess.CalledProcessError(proc.returncode, cmd, stderr=proc.stderr)
    else:
        logger.log_app_event(stage, 'completed', {'duration_sec': duration})
    return proc

def build_ffmpeg_encode(video_path: str, output_path: str, gpu_encoder: str = None, session_id: str = "global") -> list:
    enc = gpu_encoder or "libx264"
    return [
        "ffmpeg", "-y", "-i", video_path,
        "-c:v", enc, "-pix_fmt", "yuv420p",
        output_path
    ]

def render_clip(video_path: str, output_path: str, style: dict, session_id: str, gpu_encoder: str = None):
    logger = get_logger(session_id)
    
    # Validate input quality first
    validate_input_quality(video_path, session_id)
    
    logger.log_app('render', 'started', {
        'input': str(video_path),
        'output': str(output_path),
        'encoder': gpu_encoder or 'libx264'
    })
    ui_logger.info(f'Starting render: {video_path} -> {output_path}')
    
    try:
        # Build command
        cmd = build_ffmpeg_encode(video_path, output_path, gpu_encoder, session_id)
        
        # Run with logging (replaces your existing subprocess.run)
        run_ffmpeg(cmd, session_id, stage='render')
        
        logger.log_app('render', 'completed', {'output': str(output_path)})
        ui_logger.success(f'Render complete: {output_path}')
        
        return output_path
        
    except Exception as e:
        logger.log_app('render', 'failed', {}, error=str(e))
        ui_logger.error(f'Render failed: {str(e)}')
        raise

# ── 1:1 Layout constants & Background frame extractor ────────────────────────
LAYOUT_TOP_ZONE_H  = 320   # px — hook text zone above video
LAYOUT_VIDEO_SIZE  = 1080  # px — 1:1 video square width/height
LAYOUT_VIDEO_Y     = 320   # px — y offset where video square starts
LAYOUT_BOT_ZONE_H  = 520   # px — caption/hook zone below video

def _extract_bg_frame(input_path: str, timestamp: float, output_path: str, session_id: str = "global") -> bool:
    try:
        cmd = [
            "ffmpeg", "-y", "-ss", str(timestamp), "-i", input_path,
            "-vframes", "1", "-q:v", "2", output_path
        ]
        res = run_ffmpeg(cmd, session_id=session_id, stage='extract_bg')
        if res.returncode == 0 and os.path.exists(output_path):
            return True
        return False
    except Exception as e:
        ui_logger.log(f"Warning: _extract_bg_frame failed: {e}")
        return False

def _build_layout_filtergraph(bg_style: str, bg_frame_path: str or None, fps: float, clip_duration: float, layout_mode: str = "box"):
    # VIDEO LAYER
    if layout_mode == "box":
        video_layer = (
            "[0:v]scale=1080:1080:flags=lanczos:force_original_aspect_ratio=increase,crop=1080:1080,setsar=1[video_graded]"
        )
    else:
        video_layer = (
            "[0:v]scale=1080:1920:flags=lanczos:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[video_graded]"
        )

    # BACKGROUND LAYER — five branches on bg_style
    bg_style_lower = bg_style.lower() if bg_style else "black"
    if bg_style_lower == "black":
        extra_input_args = []
        bg_layer = f"color=c=black:s=1080x1920:r={fps}[bg]"
    elif bg_style_lower == "white":
        extra_input_args = []
        bg_layer = f"color=c=white:s=1080x1920:r={fps}[bg]"
    elif bg_style_lower == "brand":
        extra_input_args = []
        bg_layer = f"color=c=0x0f172a:s=1080x1920:r={fps}[bg]"
    elif bg_style_lower == "blur":
        extra_input_args = [
            "-loop", "1",
            "-t", str(clip_duration),
            "-i", bg_frame_path
        ]
        bg_layer = (
            "[1:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,boxblur=20:5,"
            "colorchannelmixer=rr=0.6:gg=0.6:bb=0.6[bg]"
        )
    elif bg_style_lower == "gradient":
        extra_input_args = [
            "-loop", "1",
            "-t", str(clip_duration),
            "-i", bg_frame_path
        ]
        bg_layer = (
            "[1:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,boxblur=40:10,"
            "colorchannelmixer=rr=0.3:gg=0.3:bb=0.3[bg]"
        )
    else:
        # Fallback to black
        extra_input_args = []
        bg_layer = f"color=c=black:s=1080x1920:r={fps}[bg]"

    # COMPOSITE
    if layout_mode == "box":
        composite = (
            "[bg][video_graded]overlay=0:320,"
            "setpts=PTS-STARTPTS[vout]"
        )
    else:
        composite = (
            "[bg][video_graded]overlay=0:0,"
            "setpts=PTS-STARTPTS[vout]"
        )

    filter_complex = f"{bg_layer};{video_layer};{composite}"
    output_map = "[vout]"

    return extra_input_args, filter_complex, output_map

_DETECTED_ENCODER = None

def _get_best_encoder():
    global _DETECTED_ENCODER
    if _DETECTED_ENCODER is not None:
        return _DETECTED_ENCODER

    _DETECTED_ENCODER = "libx264"
    candidates = ["h264_nvenc", "h264_amf", "h264_qsv"]
    for codec in candidates:
        try:
            test_cmd = [
                "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.1",
                "-c:v", codec, "-f", "null", "-"
            ]
            test_res = subprocess.run(test_cmd, capture_output=True, timeout=5)
            if test_res.returncode == 0:
                _DETECTED_ENCODER = codec
                ui_logger.log(f"⚡ {codec} GPU hardware acceleration detected and enabled!")
                break
        except Exception:
            pass

    return _DETECTED_ENCODER

# Ensure we have our premium font (Bebas Neue) available locally
_FONT_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
_FONT_FILE = "BebasNeue-Regular.ttf"



# ── Silence Detection & Removal ──────────────────────────────────────────────

def _remove_silence_ffmpeg(input_path: str, output_path: str, noise_db: int = -30, min_silence_dur: float = 0.5, session_id: str = "global") -> str:
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
            run_ffmpeg([
                "ffmpeg", "-y", "-i", input_path, "-vn",
                "-ar", "16000", "-ac", "1", temp_wav
            ], session_id=session_id, stage='silence_wav', check=True)
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
        result = run_ffmpeg(detect_cmd, session_id=session_id, stage='silence_detect')
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
        probe_res = run_ffmpeg(probe_cmd, session_id=session_id, stage='silence_probe')
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
    # Quality unified to CRF/QP 12 across all render stages (matches the main
    # segment render) so output quality does not vary between passes.
    if encoder == "h264_nvenc":
        enc_args = ["-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr", "-cq", "12", "-b:v", "8M", "-maxrate", "10M", "-bufsize", "20M"]
    elif encoder == "h264_amf":
        enc_args = ["-c:v", "h264_amf", "-quality", "quality", "-rc", "cqp", "-qp_i", "12", "-qp_p", "12"]
    elif encoder == "h264_qsv":
        enc_args = ["-c:v", "h264_qsv", "-preset", "slower", "-global_quality", "12"]
    else:
        enc_args = ["-c:v", "libx264", "-preset", "slow", "-crf", "12"]


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
        run_ffmpeg(trim_cmd, session_id=session_id, stage='trim_segment', check=True)
        return output_path
    except subprocess.CalledProcessError:
        return input_path

# ── CapCut-Style Presets ─────────────────────────────────────────────────────
_CAPTION_STYLES = {
    "Classic":        {"font_size": 88,  "primary": "&H00FFFFFF&", "highlight": "&H0000FFFF&", "outline": 4, "shadow": 2, "bold": 1, "border_style": 1, "back_color": "&H80000000&", "casing": "upper"},
    "Pop":            {"font_size": 95,  "primary": "&H00FFFFFF&", "highlight": "&H00FF00FF&", "outline": 4, "shadow": 2, "bold": 1, "border_style": 1, "back_color": "&H80000000&", "casing": "upper"},
    "Glow":           {"font_size": 88,  "primary": "&H00FFFFFF&", "highlight": "&H00FF00FF&", "outline": 2, "shadow": 8, "bold": 1, "border_style": 1, "back_color": "&H80000000&", "casing": "upper"},
    "Outline":        {"font_size": 92,  "primary": "&H00FFFFFF&", "highlight": "&H0000FF00&", "outline": 5, "shadow": 0, "bold": 1, "border_style": 1, "back_color": "&H80000000&", "casing": "upper"},
    "Minimal":        {"font_size": 72,  "primary": "&H00FFFFFF&", "highlight": "&H00FFFFFF&", "outline": 1, "shadow": 0, "bold": 0, "border_style": 1, "back_color": "&H80000000&", "casing": "upper"},
    "Fire":           {"font_size": 90,  "primary": "&H0000FFFF&", "highlight": "&H000080FF&", "outline": 4, "shadow": 2, "bold": 1, "border_style": 1, "back_color": "&H80000000&", "casing": "upper"},
    # New Premium Styles
    "PodcastPop":     {"font_size": 90,  "primary": "&H00FFFFFF&", "highlight": "&H00C500C5&", "outline": 5, "shadow": 0, "bold": 1, "border_style": 1, "back_color": "&H00000000&", "casing": "upper"},
    "CinematicSlate": {"font_size": 76,  "primary": "&H00FFFFFF&", "highlight": "&H0033FF33&", "outline": 3, "shadow": 0, "bold": 0, "border_style": 3, "back_color": "&H99000000&", "casing": "original"},
    "NeonGlow":       {"font_size": 80,  "primary": "&H00FFFFFF&", "highlight": "&H0000FFFF&", "outline": 1.5, "shadow": 8, "bold": 1, "border_style": 1, "back_color": "&H99000000&", "casing": "lower"},
}

TITLE_STYLE_PRESETS = {
    "Impact": {
        "PrimaryColour":  "&H00FFFFFF",   # white
        "OutlineColour":  "&H00000000",   # black
        "BackColour":     "&H00000000",
        "BorderStyle":    1,
        "Outline":        6,
        "Shadow":         0,
        "casing":         "upper"
    },
    "Box": {
        "PrimaryColour":  "&H00FFFFFF",   # white
        "OutlineColour":  "&H00000000",
        "BackColour":     "&HAA000000",   # semi-transparent black box
        "BorderStyle":    3,
        "Outline":        0,
        "Shadow":         0,
        "casing":         "upper"
    },
    "Yellow": {
        "PrimaryColour":  "&H0000FFFF",   # yellow (ASS BGR)
        "OutlineColour":  "&H00000000",   # black
        "BackColour":     "&H00000000",
        "BorderStyle":    1,
        "Outline":        5,
        "Shadow":         2,
        "casing":         "upper"
    },
    "Neon": {
        "PrimaryColour":  "&H00FFFFFF",   # white
        "OutlineColour":  "&H00FF00FF",   # magenta glow
        "BackColour":     "&H00000000",
        "BorderStyle":    1,
        "Outline":        2,
        "Shadow":         12,
        "casing":         "upper"
    },
    "Orange": {
        "PrimaryColour":  "&H000066FF",   # orange (ASS BGR)
        "OutlineColour":  "&H00000000",   # black
        "BackColour":     "&H00000000",
        "BorderStyle":    1,
        "Outline":        5,
        "Shadow":         2,
        "casing":         "upper"
    },
    "Suits": {
        "PrimaryColour":  "&H00FFFFFF",   # white base
        "OutlineColour":  "&H00000000",   # black outline
        "BackColour":     "&H00000000",
        "BorderStyle":    1,
        "Outline":        5,
        "Shadow":         2,
        "casing":         "title"
    },
    "Meme": {
        "PrimaryColour":  "&H00000000",   # solid black
        "OutlineColour":  "&H00FFFFFF",   # white outline
        "BackColour":     "&H00000000",
        "BorderStyle":    1,
        "Outline":        0,
        "Shadow":         0,
        "casing":         "upper"
    },
    "ViralItalic": {
        "PrimaryColour":  "&H00FFFFFF",   # white
        "OutlineColour":  "&H00000000",   # black
        "BackColour":     "&H88000000",   # semi-transparent shadow
        "BorderStyle":    1,
        "Outline":        6,
        "Shadow":         6,
        "Italic":         -1,
        "casing":         "upper"
    },
}

def _is_header_highlight_target(word: str) -> bool:
    """
    Cleans word and checks if it contains numbers or matches high-impact trigger words.
    """
    clean_word = "".join(c for c in word if c.isalnum() or c in "$%").upper()
    is_number = any(char.isdigit() for char in clean_word)

    # Custom viral highlight trigger words
    trigger_words = {
        "SECRET", "SECRETS", "MISTAKE", "MISTAKES", "FAILED", "FAIL", "FAILS",
        "SHOCKING", "SHOCKED", "RULE", "RULES", "REVENUE", "TRUTH", "VIRAL",
        "MONEY", "EARN", "RICHEST", "RICH", "POOR", "WHOP", "REWARDS",
        "SUCCESS", "SUCCESSFUL", "ONLY", "PRO", "TINY", "HUGE", "FAST", "SLOW"
    }
    is_trigger = clean_word in trigger_words
    return is_number or is_trigger

HOOK_STYLE_PRESETS = {
    "BlackOnWhiteBox": {
        "PrimaryColour":  "&H00000000",   # black text
        "OutlineColour":  "&H00000000",
        "BackColour":     "&H00FFFFFF",   # solid white box
        "BorderStyle":    3,
        "Outline":        0,
        "Shadow":         0,
        "casing":         "upper"
    },
    "YellowOnBlackBox": {
        "PrimaryColour":  "&H0000FFFF",   # yellow text
        "OutlineColour":  "&H00000000",
        "BackColour":     "&H00000000",   # solid black box
        "BorderStyle":    3,
        "Outline":        0,
        "Shadow":         0,
        "casing":         "upper"
    },
    "BoldWhite": {
        "PrimaryColour":  "&H00FFFFFF",   # white
        "OutlineColour":  "&H00000000",   # black outline
        "BackColour":     "&H00000000",
        "BorderStyle":    1,
        "Outline":        6,
        "Shadow":         0,
        "casing":         "upper"
    },
    "BrightYellow": {
        "PrimaryColour":  "&H0000FFFF",   # yellow
        "OutlineColour":  "&H00000000",   # black outline
        "BackColour":     "&H00000000",
        "BorderStyle":    1,
        "Outline":        5,
        "Shadow":         2,
        "casing":         "upper"
    },
    "None": {
        "casing":         "upper"
    }
}

def _generate_ass(words, out_path, video_w, video_h, time_offset=0, theme="Storytime", style_mode="Classic", position="Center", title_style: str = "Impact", hook_style: str = "BlackOnWhiteBox", **kwargs):
    # Resolve style preset — fall back to Classic if unknown
    # Resolve style preset — returns a dict with all style attributes
    style = _CAPTION_STYLES.get(style_mode, _CAPTION_STYLES["Classic"])
    font_size = style["font_size"]
    main_color = style["primary"]
    high_color = style["highlight"]
    outline = style["outline"]
    shadow = style["shadow"]
    bold = style["bold"]
    border_style = style.get("border_style", 1)
    back_color = style.get("back_color", "&H80000000&")
    casing = style.get("casing", "upper")
    
    # Resolve per-element fonts from kwargs
    caption_font_choice = kwargs.get("caption_font", "bebas")
    header_font_choice = kwargs.get("header_font", "bebas")
    hook_font_choice = kwargs.get("hook_font", "bebas")
    
    # Verify font paths physically exist (raises FileNotFoundError if missing)
    get_font_path("caption", caption_font_choice)
    get_font_path("header", header_font_choice)
    get_font_path("hook", hook_font_choice)
    
    # Get the correct font family names to render inside the ASS file
    caption_font_name = get_font_family(caption_font_choice)
    header_font_name = "Impact" if title_style == "ViralItalic" else get_font_family(header_font_choice)
    hook_font_name = get_font_family(hook_font_choice)

    p = {"main": main_color, "high": high_color}

    caption_pos = position.lower() if position else "bottom"
    if caption_pos == "top":
        align = 8
        margin_v = 360  # 40px below the header zone into the video area
    else:  # bottom — owner-approved on-video position
        align = 2
        margin_v = 560

    ts = TITLE_STYLE_PRESETS.get(title_style, TITLE_STYLE_PRESETS["Impact"])

    h_italic = ts.get("Italic", 0)
    h_outline = ts.get("Outline", 12)
    h_shadow = ts.get("Shadow", 0)
    h_border_style = ts.get("BorderStyle", 3)
    h_back_color = ts.get("BackColour", "&H00000000")

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {video_w}",
        f"PlayResY: {video_h}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Main,{caption_font_name},{font_size},{p['main']},&H000000FF,&H00000000,{back_color},{bold},0,0,0,100,100,1,0,{border_style},{outline},{shadow},{align},40,40,{margin_v},1",
        f"Style: Highlight,{caption_font_name},{font_size},{p['high']},&H000000FF,&H00000000,{back_color},{bold},0,0,0,100,100,1,0,{border_style},{outline},{shadow},{align},40,40,{margin_v},1",
    ]
    # Header and MagicHook removed from ASS — they are now Pillow PNG overlays

    lines.extend([
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    ])

    def fmt_time(secs):
        h = int(secs // 3600); m = int((secs % 3600) // 60); s = int(secs % 60); cs = int((secs - int(secs)) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    seg_duration = max(0, words[-1]['end'] - time_offset) if words else 0.0

    chunks = []
    curr = []
    for i, w in enumerate(words):
        curr.append(w)
        word_text = w["word"].strip()
        ends_sentence = any(p in word_text for p in [".", "!", "?", "।", "|"])
        pause_after = False
        if i + 1 < len(words):
            pause_after = (words[i+1]["start"] - w["end"]) > 0.5

        if ends_sentence or pause_after or len(curr) >= 3:
            chunks.append(curr)
            curr = []
    if curr:
        chunks.append(curr)

    for chunk in chunks:
        chunk_st = max(0, chunk[0]['start'] - time_offset)
        chunk_et = max(0, chunk[-1]['end'] - time_offset)
        if chunk_et <= chunk_st: continue

        for active_idx, active_word in enumerate(chunk):
            active_st = max(0, active_word['start'] - time_offset)
            active_et = max(0, active_word['end'] - time_offset)
            if active_et <= active_st: continue

            # Fill small gaps between words in the same chunk
            if active_idx == 0:
                event_st = chunk_st
            else:
                event_st = active_st

            if active_idx == len(chunk) - 1:
                event_et = chunk_et
            else:
                event_et = max(active_et, chunk[active_idx+1]['start'] - time_offset)

            styled = ""
            for x_idx, x in enumerate(chunk):
                txt = x['word'].strip()
                if casing == "upper": txt = txt.upper()
                elif casing == "lower": txt = txt.lower()

                # Whisper splits hyphenated/contraction tokens as "-word" or "'s" —
                # join them to the previous word without a space so display is correct.
                needs_join = txt and txt[0] in ("-", "'")

                if x_idx == active_idx:
                    token = f"{{\\c{p['high']}}}{txt}{{\\c{p['main']}}}"
                else:
                    token = txt

                if needs_join and styled:
                    styled = styled.rstrip(" ") + token + " "
                else:
                    styled += token + " "

            lines.append(f"Dialogue: 0,{fmt_time(event_st)},{fmt_time(event_et)},Main,,0,0,0,,{styled.strip()}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _generate_text_card(output_path, text, duration, font_file, font_size=64, session_id: str = "global"):
    text = '\n'.join(textwrap.wrap(text, width=22))
    safe_text = text.replace("'", "").replace(":", "")
    vf_filter = f"drawtext=text='{safe_text}':fontcolor=white:fontsize={font_size}:line_spacing=12:x=(w-text_w)/2:y=(h-text_h)/2"
    if font_file and os.path.exists(font_file):
        safe_font = font_file.replace("\\", "/").replace(":", "\\:")
        vf_filter = f"drawtext=fontfile='{safe_font}':text='{safe_text}':fontcolor=white:fontsize={font_size}:line_spacing=12:x=(w-text_w)/2:y=(h-text_h)/2"
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s=1080x1920:r=30:d={duration}",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-map", "0:v", "-map", "1:a",
        "-vf", vf_filter,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "12",
        "-profile:v", "high", "-pix_fmt", "yuv420p", "-x264opts", "keyint=30",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        output_path
    ]
    run_ffmpeg(cmd, session_id=session_id, stage='text_card', check=True)

def render_short(input_video, clip_data, word_timestamps, output_dir, work_dir,
                 face_center=True, add_subs=True, theme="Storytime",
                 caption_style="Classic", caption_pos="Bottom",
                 override_start=None, override_end=None, excluded_sentences=None,
                 magic_hook=False, remove_silence=True, broll_intensity="Medium",
                 all_sentences=None, padding=3.0, bg_style="black", hook_position="top", hook_display="full", show_outro: bool = False, title_style: str = "Impact",
                 layout_mode: str = "box", hook_style: str = "BlackOnWhiteBox",
                 header_font: str = "bebas", caption_font: str = "montserrat semibold", hook_font: str = "montserrat semibold",
                 header_style: str = "card",
                 session_id: str = "global"):

    ui_logger.log("Initializing render pipeline...")
    cap_fps = cv2.VideoCapture(input_video)
    fps = cap_fps.get(cv2.CAP_PROP_FPS) or 30.0
    cap_fps.release()
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)

    # ── Guarantee Bebas Neue font exists locally ──
    _colab_font = os.path.join(_FONT_DIR, _FONT_FILE)
    if os.path.exists(_colab_font):
        # Refresh fontconfig cache so libass finds the font at render time
        if os.name != 'nt':
            try:
                subprocess.run(["fc-cache", "-fv"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            except Exception:
                pass
    else:
        ui_logger.log(f"Warning: bundled font missing at {_colab_font}")
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
        for idx, seg in enumerate(raw_segments):
            seg_st = float(seg["start_time"])
            seg_et = float(seg["end_time"])
            
            # Smart Padding for Context & Payoff
            seg_st = max(0, seg_st - 0.3)
            seg_et = seg_et + 0.2
            if idx == 0:
                seg_st = max(0, seg_st - 0.8) # Allow hook to breathe
            if idx == len(raw_segments) - 1:
                seg_et = seg_et + 1.5 # Let the payoff linger
                
            block_words.extend([w for w in word_timestamps if seg_st - 0.5 <= w["start"] <= seg_et + 0.5])
            raw_segments[idx]["start_time"] = seg_st
            raw_segments[idx]["end_time"] = seg_et
            
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

        # ── Setup Video/Audio Inputs & 1:1 Layout ──
        bg_frame_path = None
        if bg_style in ["blur", "gradient"]:
            bg_timestamp = min(seg_st + 2.0, seg_et)
            bg_frame_path = os.path.join(work_dir, f"bg_frame_{out_id}_{idx}.jpg")
            _extract_bg_frame(input_video, bg_timestamp, bg_frame_path, session_id=session_id)

        clip_duration = seg_et - seg_st
        extra_input_args, layout_fc, layout_out = _build_layout_filtergraph(
            bg_style, bg_frame_path, fps, clip_duration, layout_mode=layout_mode
        )

        if extra_input_args:
            inputs = ["-ss", str(seg_st), "-to", str(seg_et), "-i", input_video] + extra_input_args
            input_idx = 2
        else:
            inputs = ["-ss", str(seg_st), "-to", str(seg_et), "-i", input_video]
            input_idx = 1
        audio_source = "0:a"

        filter_complex = layout_fc + ";"
        current_v = "vout"
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

                    if layout_mode == "box":
                        filter_complex += f"[{input_idx}:v]scale=1080:1080:flags=lanczos:force_original_aspect_ratio=increase,crop=1080:1080[broll{input_idx}];"
                    else:
                        filter_complex += f"[{input_idx}:v]scale={target_w}:{target_h}:flags=lanczos:force_original_aspect_ratio=increase,crop={target_w}:{target_h}[broll{input_idx}];"

                    rel_st = b_st - seg_st
                    rel_et = rel_st + 2.0
                    next_v = f"v{input_idx}"

                    if layout_mode == "box":
                        filter_complex += f"[{current_v}][broll{input_idx}]overlay=0:320:enable='between(t,{rel_st},{rel_et})'[{next_v}];"
                    else:
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
            mh_text = clip_data.get("hook_text") if (magic_hook and idx == 0) else None
            safe_font = os.path.join(_FONT_DIR, _FONT_FILE).replace("\\", "/").replace(":", "\\:")

            ass_path = os.path.join(work_dir, f"subs_{out_id}_{idx}.ass")
            _generate_ass(seg_words, ass_path, target_w, target_h, time_offset=seg_st,
                          theme=theme, style_mode=caption_style, position=caption_pos,
                          magic_hook_text=mh_text, header_text=clip_data.get("title", ""),
                          hook_position=hook_position, hook_display=hook_display,
                          title_style=title_style, hook_style=hook_style,
                          header_font=header_font, caption_font=caption_font, hook_font=hook_font)
            safe_ass = ass_path.replace("\\", "/").replace(":", "\\:")
            next_v = f"v{input_idx}_ass"
            # FONT_DIR is a pathlib.Path (config.py); Path.replace() means "move file",
            # not string replace — calling it with 2 args crashed every captioned render.
            # Cast to str first, exactly like _FONT_DIR above.
            safe_fonts_dir = str(FONT_DIR).replace("\\", "/").replace(":", "\\:")
            filter_complex += f"[{current_v}]ass='{safe_ass}':fontsdir='{safe_fonts_dir}'[{next_v}];"
            current_v = next_v
            input_idx += 1

        # ── Header (top, persistent) + magic-hook (center screen, timed) ──
        # Re-sync input_idx: ASS pseudo-incremented it without adding a real -i;
        # SFX audio inputs were added before sfx_start_idx without incrementing.
        input_idx = sfx_start_idx + len(sfx_delays)
        header_path = get_font_path("header", header_font)
        hook_path = get_font_path("hook", hook_font)
        hook_on = bool(magic_hook and idx == 0 and clip_data.get("hook_text") and hook_display != "off")

        # Header: topic reminder pinned at top, visible the whole clip
        if clip_data.get("title"):
            hdr_png = os.path.join(work_dir, f"hdr_{out_id}_{idx}.png")
            _overlays.render_overlay_png(clip_data["title"], header_style, header_path,
                                         out_path=hdr_png, max_font_size=90)
            inputs.extend(["-loop", "1", "-t", str(clip_duration), "-i", hdr_png])
            hy = 0 if layout_mode == "box" else 40
            next_v = f"v{input_idx}_hdr"
            filter_complex += (f"[{current_v}][{input_idx}:v]"
                               f"overlay=0:{hy}:enable='gte(t,0)'[{next_v}];")
            current_v = next_v
            input_idx += 1

        # Hook: punchy phrase centered on canvas (Y=800), first N seconds only
        if hook_on:
            hook_until = 5.0 if hook_display == "full" else (3.0 if hook_display == "3s" else 5.0)
            hk_png = os.path.join(work_dir, f"hook_{out_id}_{idx}.png")
            _overlays.render_overlay_png(clip_data["hook_text"], header_style, hook_path,
                                         out_path=hk_png, max_font_size=72, opacity=0.5)
            inputs.extend(["-loop", "1", "-t", str(clip_duration), "-i", hk_png])
            next_v = f"v{input_idx}_hook"
            filter_complex += (f"[{current_v}][{input_idx}:v]"
                               f"overlay=0:800:enable='lt(t,{hook_until})'[{next_v}];")
            current_v = next_v
            input_idx += 1

        if idx > 0:
            next_v = f"v{input_idx}_flash"
            filter_complex += f"[{current_v}]drawbox=w=iw:h=ih:color=white:t=fill:enable='between(t,0,0.10)'[{next_v}];"
            current_v = next_v
            input_idx += 1

        # eq, vignette, and setpts are already handled in the layout filtergraph, so we do not re-apply them.
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
        if encoder == "h264_nvenc":
            enc_args = ["-c:v", "h264_nvenc", "-preset", "p7", "-rc", "vbr", "-cq", "12", "-b:v", "15M", "-maxrate", "20M", "-bufsize", "40M"]
        elif encoder == "h264_amf":
            enc_args = ["-c:v", "h264_amf", "-quality", "quality", "-rc", "cqp", "-qp_i", "12", "-qp_p", "12"]
        elif encoder == "h264_qsv":
            enc_args = ["-c:v", "h264_qsv", "-preset", "veryslow", "-global_quality", "12"]
        else:
            enc_args = ["-c:v", "libx264", "-preset", "slower", "-crf", "12"]

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
        # Persist this composition step to the on-disk logs. Previously this raw
        # Popen call only streamed to the WebSocket, so when it failed the real
        # ffmpeg error never reached the Drive logs — the render looked like it
        # "vanished" mid-run. Now every failure is captured for diagnosis.
        seg_logger = get_logger(session_id)
        seg_logger.log_app_event(
            'segment_render', 'ffmpeg_started',
            {'command': ' '.join(cmd), 'clip': out_id, 'segment': idx,
             'duration_sec': round(seg_et - seg_st, 2)}
        )
        import time as _t_render
        _seg_start = _t_render.time()
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
            full_stderr = "".join(stderr_lines)
            seg_logger.log_ffmpeg(
                command=' '.join(cmd), return_code=proc.returncode,
                stdout="", stderr=full_stderr,
                duration_sec=_t_render.time() - _seg_start
            )
            if proc.returncode != 0:
                err_msg = "".join(stderr_lines[-20:])  # last 20 lines of stderr
                seg_logger.log_app_event(
                    'segment_render', 'failed', {'clip': out_id, 'segment': idx},
                    error=full_stderr[-1500:]
                )
                ui_logger.log(f"FFmpeg error details:\n{err_msg}")
                raise subprocess.CalledProcessError(proc.returncode, cmd, stderr=err_msg)
            seg_logger.log_app_event('segment_render', 'completed', {'clip': out_id, 'segment': idx})
            ui_logger.log(f"PROGRESS|100|Rendering 100%...")
        except subprocess.CalledProcessError as e:
            ui_logger.log(f"FFmpeg error: {e.stderr[-500:] if hasattr(e, 'stderr') and e.stderr else 'unknown'}")
            raise

        # ── Post-render silence removal pass ──
        if remove_silence:
            desilenced = os.path.join(work_dir, f"desil_{out_id}_{idx}.mp4")
            seg_out = _remove_silence_ffmpeg(seg_out, desilenced, session_id=session_id)
        rendered_segs.append(seg_out)

    if not rendered_segs:
        raise ValueError("No valid segments could be rendered. (Check your transcript exclusions)")

    ui_logger.log("Combining segments into final short...")
    # Prepend 0.5s opening title card and append 1.5s outro CTA card
    try:
        if show_outro:
            end_card_path = os.path.join(work_dir, f"end_{out_id}.mp4")
            _generate_text_card(end_card_path, "FOLLOW FOR MORE!", 1.5, _colab_font, font_size=70, session_id=session_id)
            rendered_segs = rendered_segs + [end_card_path]
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
            fc_str += f"[{i}:a]aresample=48000,asetpts=PTS-STARTPTS[a{i}];"
        fc_str += (
            "".join(f"[v{i}][a{i}]" for i in range(n_segs))
            + f"concat=n={n_segs}:v=1:a=1[v_concat_raw][a_concat_raw];[v_concat_raw]setpts=PTS-STARTPTS[v_concat];[a_concat_raw]asetpts=PTS-STARTPTS[a_concat]"
        )

        concat_enc_args = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "0"]

        concat_cmd = ["ffmpeg", "-y"] + fc_inputs + [
            "-filter_complex", fc_str,
            "-map", "[v_concat]", "-map", "[a_concat]",
        ] + concat_enc_args + [
            "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-x264opts", "keyint=30"
        ]

        concat_cmd.extend([
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart",
            final_output
        ])
        try:
            run_ffmpeg(concat_cmd, session_id=session_id, stage='concat', check=True, timeout=300)
        except subprocess.TimeoutExpired:
            ui_logger.log("FFmpeg concat timed out after 300s!")
            raise RuntimeError("FFmpeg concatenation timed out due to segment stream mismatch.")
        except subprocess.CalledProcessError as e:
            ui_logger.log(f"FFmpeg concat error: {e.stderr[-500:] if hasattr(e, 'stderr') and e.stderr else 'unknown'}")
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
                run_ffmpeg(bgm_cmd, session_id=session_id, stage='bgm_mix', check=True)
                shutil.move(bgm_output, final_output)
                ui_logger.log("BGM mixed successfully.")
        except Exception as bgm_err:
            ui_logger.log(f"LLM BGM mixing failed ({bgm_err}) — clip saved without AI music.")

    ui_logger.log(f"Render complete: {os.path.basename(final_output)}")
    return final_output

