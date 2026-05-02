# shorts_generator/clipper.py
import subprocess
import os
import cv2
import uuid
import statistics


# ── Style constants (tweak here to change the look) ─────────────────────────
FONT_NAME       = "Impact"          # Hormozi signature font
FONT_SIZE       = 95                # big and punchy
PRIMARY_COLOR   = "&H00FFFFFF"      # white body text
HIGHLIGHT_COLOR = "&H0000FFFF"      # yellow for active word group
OUTLINE_COLOR   = "&H00000000"      # black outline
BACK_COLOR      = "&H00000000"      # no box background
BOLD            = -1                # bold on
OUTLINE_WIDTH   = 5                 # thick black stroke
SHADOW          = 0
MARGIN_V        = 160               # distance from bottom (px at 1920h)
WORDS_PER_LINE  = 3                 # words grouped per subtitle event


def _sample_face_x(video_path: str, timestamps: list[float], frame_w: int, crop_w: int) -> int:
    """
    Samples up to 3 frames and returns a stable face-centered x_offset.
    Falls back to center crop if no face found.
    """
    face_cc = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    x_offsets = []
    cap = cv2.VideoCapture(video_path)

    for ts in timestamps:
        cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000)
        ret, frame = cap.read()
        if not ret:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cc.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=5)
        if len(faces):
            fx, _, fw, _ = faces[0]
            face_cx = fx + fw / 2
            offset = int(face_cx - crop_w / 2)
            offset = max(0, min(frame_w - crop_w, offset))
            x_offsets.append(offset)

    cap.release()

    if x_offsets:
        return int(statistics.median(x_offsets))
    return (frame_w - crop_w) // 2  # centre fallback


def render_short(
    input_video: str,
    clip_data: dict,
    word_timestamps: list,
    output_dir: str,
    work_dir: str,
    face_center: bool = True,
) -> str:
    start, end = float(clip_data["start"]), float(clip_data["end"])
    out_path = os.path.join(output_dir, f"short_{uuid.uuid4().hex[:6]}.mp4")

    # ── 1. Face-aware crop offset ────────────────────────────────────────────
    x_offset_expr = "(iw-ih*9/16)/2"  # default: centre

    if face_center:
        cap = cv2.VideoCapture(input_video)
        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        crop_w = int(frame_h * 9 / 16)

        sample_ts = [
            start,
            start + (end - start) * 0.5,
            start + (end - start) * 0.85,
        ]
        px = _sample_face_x(input_video, sample_ts, frame_w, crop_w)
        x_offset_expr = str(px)

    # ── 2. Build subtitles ───────────────────────────────────────────────────
    ass_path = os.path.join(work_dir, f"subs_{uuid.uuid4().hex[:6]}.ass")
    generate_ass_file(word_timestamps, start, end, ass_path)

    # ── 3. FFmpeg render ─────────────────────────────────────────────────────
    # Escape Windows-style drive letter colons for the ass filter path
    safe_ass = ass_path.replace("\\", "/").replace(":", r"\:")

    vf = ",".join([
        f"crop=ih*9/16:ih:{x_offset_expr}:0",
        "scale=1080:1920:flags=lanczos",
        f"ass='{safe_ass}'",
    ])

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start), "-to", str(end),
        "-i", input_video,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        out_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed:\n{result.stderr[-2000:]}")

    return out_path


# ── ASS generation ────────────────────────────────────────────────────────────

def _to_ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def generate_ass_file(
    words: list,
    start_time: float,
    end_time: float,
    out_path: str,
) -> None:
    """
    Groups words into WORDS_PER_LINE chunks.
    The active group renders in HIGHLIGHT_COLOR; others in PRIMARY_COLOR.
    Hormozi-style: Impact, large, bottom-centre, thick outline.
    """
    clip_words = [
        w for w in words
        if float(w["start"]) >= start_time and float(w["end"]) <= end_time
    ]

    # Offset all timestamps so t=0 is the clip start
    for w in clip_words:
        w = w.copy()

    # Build groups of N words
    groups = []
    for i in range(0, len(clip_words), WORDS_PER_LINE):
        chunk = clip_words[i : i + WORDS_PER_LINE]
        if not chunk:
            continue
        groups.append({
            "words": [w["word"].strip() for w in chunk],
            "start": float(chunk[0]["start"]) - start_time,
            "end":   float(chunk[-1]["end"])  - start_time,
        })

    # ── ASS header ───────────────────────────────────────────────────────────
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "ScaledBorderAndShadow: yes\n\n"
    )

    style_line = (
        f"Style: Hormozi,"
        f"{FONT_NAME},{FONT_SIZE},"
        f"{PRIMARY_COLOR},{HIGHLIGHT_COLOR},"
        f"{OUTLINE_COLOR},{BACK_COLOR},"
        f"{BOLD},0,0,0,"          # Bold, Italic, Underline, StrikeOut
        f"100,100,0,0,"            # ScaleX, ScaleY, Spacing, Angle
        f"1,{OUTLINE_WIDTH},{SHADOW},"  # BorderStyle, Outline, Shadow
        f"2,10,10,{MARGIN_V},1\n"  # Alignment=2 (bottom-centre), margins
    )

    styles = (
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        + style_line + "\n"
    )

    events_header = (
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    lines = [header, styles, events_header]

    for g in groups:
        t_start = _to_ass_time(g["start"])
        t_end   = _to_ass_time(g["end"])
        # Highlight active group in yellow; plain white otherwise
        text = f"{{\\c{HIGHLIGHT_COLOR}}}" + " ".join(g["words"]) + "{\\r}"
        lines.append(
            f"Dialogue: 0,{t_start},{t_end},Hormozi,,0,0,0,,{text}\n"
        )

    with open(out_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
