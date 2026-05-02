import subprocess
import os
import cv2
import uuid
import statistics


# ── Style constants ───────────────────────────────────────────────
FONT_NAME      = "Impact"
FONT_SIZE      = 95
PRIMARY_COLOR  = "&H00FFFFFF"   # white
HIGHLIGHT_COLOR = "&H0000FFFF"  # yellow
OUTLINE_COLOR  = "&H00000000"   # black
BACK_COLOR     = "&H00000000"
BOLD           = -1
OUTLINE_WIDTH  = 5
SHADOW         = 0
MARGIN_V       = 160
WORDS_PER_LINE = 3


def _sample_face_x(video_path: str, timestamps: list, frame_w: int, crop_w: int) -> int:
    face_cc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    offsets = []
    cap = cv2.VideoCapture(video_path)
    for ts in timestamps:
        cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000)
        ret, frame = cap.read()
        if not ret:
            continue
        faces = face_cc.detectMultiScale(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 1.3, 5)
        if len(faces):
            fx, _, fw, _ = faces[0]
            offset = int(fx + fw / 2 - crop_w / 2)
            offsets.append(max(0, min(frame_w - crop_w, offset)))
    cap.release()
    if offsets:
        return int(statistics.median(offsets))
    return (frame_w - crop_w) // 2


def render_short(
    input_video: str,
    clip_data: dict,
    word_timestamps: list,
    output_dir: str,
    work_dir: str,
    face_center: bool = True,
    add_subs: bool = True,
) -> str:
    start = float(clip_data.get("start_time", clip_data.get("start", 0)))
    end   = float(clip_data.get("end_time",   clip_data.get("end",   start + 60)))
    out_path = os.path.join(output_dir, f"short_{uuid.uuid4().hex[:6]}.mp4")

    # ── Face-aware crop ───────────────────────────────────────────
    x_offset = "(iw-ih*9/16)/2"
    if face_center:
        cap = cv2.VideoCapture(input_video)
        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        crop_w = int(frame_h * 9 / 16)
        sample_ts = [start, start + (end - start) * 0.5, start + (end - start) * 0.85]
        px = _sample_face_x(input_video, sample_ts, frame_w, crop_w)
        x_offset = str(px)

    # ── Subtitles ─────────────────────────────────────────────────
    vf = [
        f"crop=ih*9/16:ih:{x_offset}:0",
        "scale=1080:1920:flags=lanczos",
    ]

    if add_subs and word_timestamps:
        ass_path = os.path.join(work_dir, f"subs_{uuid.uuid4().hex[:4]}.ass")
        generate_ass_file(word_timestamps, start, end, ass_path)
        safe_ass = ass_path.replace("\\", "/").replace(":", r"\:")
        vf.append(f"ass='{safe_ass}'")

    # ── FFmpeg render ─────────────────────────────────────────────
    result = subprocess.run([
        "ffmpeg", "-y", "-ss", str(start), "-to", str(end),
        "-i", input_video,
        "-vf", ",".join(vf),
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        out_path,
    ], capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed:\n{result.stderr[-2000:]}")

    return out_path


def _to_ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def generate_ass_file(words: list, start_time: float, end_time: float, out_path: str):
    clip_words = [w for w in words if float(w["start"]) >= start_time and float(w["end"]) <= end_time]

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Hormozi,{FONT_NAME},{FONT_SIZE},"
        f"{PRIMARY_COLOR},{HIGHLIGHT_COLOR},{OUTLINE_COLOR},{BACK_COLOR},"
        f"{BOLD},0,0,0,100,100,0,0,1,{OUTLINE_WIDTH},{SHADOW},"
        f"2,10,10,{MARGIN_V},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    lines = [header]
    for i in range(0, len(clip_words), WORDS_PER_LINE):
        chunk = clip_words[i : i + WORDS_PER_LINE]
        if not chunk:
            continue
        t_s = _to_ass_time(float(chunk[0]["start"]) - start_time)
        t_e = _to_ass_time(float(chunk[-1]["end"])   - start_time)
        text = r"{\c&H0000FFFF&}" + " ".join(w["word"] for w in chunk) + r"{\r}"
        lines.append(f"Dialogue: 0,{t_s},{t_e},Hormozi,,0,0,0,,{text}\n")

    with open(out_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
