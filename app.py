import os
import sys
import glob
import uuid
import traceback

import gradio as gr
from huggingface_hub import hf_hub_download

# ── Repo root — works both from `python app.py` and `exec()` in Colab ────────
try:
    REPO_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    REPO_DIR = os.getcwd()

if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

from shorts_generator.config import (
    BASE_DIR, WORK_DIR, OUTPUT_DIR, LLM_DIR, WHISPER_DIR,
    COOKIE_PATH, LLM_CATALOG, WHISPER_CATALOG,
)
from shorts_generator.downloader import download_video
from shorts_generator.transcriber import transcribe_audio
from shorts_generator.highlights import get_highlights
from shorts_generator.clipper import render_short

for d in [WORK_DIR, OUTPUT_DIR, LLM_DIR, WHISPER_DIR]:
    os.makedirs(d, exist_ok=True)

# ── Session state ─────────────────────────────────────────────────────────────
_state = {
    "clips": [],
    "word_timestamps": [],
    "current_url": None,
}

CAPTION_STYLES = ["Hormozi (Yellow Highlight)", "Clean White", "Bold Outline", "None"]

# ── Score → colour helper ─────────────────────────────────────────────────────
def score_color(score: int) -> str:
    if score >= 80:
        return "#22c55e"   # green
    if score >= 55:
        return "#f59e0b"   # amber
    return "#ef4444"       # red

def score_bar(score: int) -> str:
    color = score_color(score)
    return (
        f"<div style='width:100%;background:#1e1e2e;border-radius:6px;overflow:hidden;height:8px;margin:4px 0'>"
        f"<div style='width:{score}%;background:{color};height:100%'></div></div>"
    )

def build_clip_card(idx: int, clip: dict) -> str:
    score   = int(clip.get("score", 0))
    title   = clip.get("title", f"Clip {idx}")
    hook    = clip.get("hook_sentence", "")
    reason  = clip.get("virality_reason", "")
    start   = clip.get("start_time", clip.get("start", 0))
    end     = clip.get("end_time",   clip.get("end", 0))
    dur     = max(0, float(end) - float(start))
    color   = score_color(score)
    bar     = score_bar(score)
    return f"""
<div style='background:#1e1e2e;border:1px solid #313244;border-radius:12px;
            padding:16px;margin-bottom:12px;font-family:Inter,sans-serif;color:#cdd6f4'>
  <div style='display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px'>
    <div>
      <span style='font-size:11px;color:#6c7086;font-weight:600;text-transform:uppercase'>
        Clip {idx}
      </span>
      <h3 style='margin:2px 0 0;font-size:15px;color:#cdd6f4'>{title}</h3>
    </div>
    <div style='text-align:right'>
      <div style='font-size:26px;font-weight:800;color:{color}'>{score}</div>
      <div style='font-size:10px;color:#6c7086'>Virality Score</div>
    </div>
  </div>
  {bar}
  <div style='display:flex;gap:8px;margin:10px 0 8px;font-size:12px;color:#89b4fa'>
    <span>⏱ {float(start):.0f}s → {float(end):.0f}s</span>
    <span>·</span>
    <span>🎬 {dur:.0f}s clip</span>
  </div>
  <div style='font-size:13px;color:#a6e3a1;margin-bottom:6px'>
    <strong>Hook:</strong> "{hook}"
  </div>
  <div style='font-size:12px;color:#6c7086'>{reason}</div>
</div>"""

# ── Core functions ────────────────────────────────────────────────────────────
def analyze_video(url, llm_idx, wsp_idx, num_clips):
    if not url or not url.strip():
        yield "", "<p style='color:#ef4444'>Please enter a YouTube URL.</p>", gr.update(visible=False)
        return

    try:
        llm_entry = LLM_CATALOG[int(llm_idx)]
        wsp_size  = WHISPER_CATALOG[int(wsp_idx)]["size"]
        llm_path  = os.path.join(LLM_DIR, llm_entry["filename"])
        n_clips   = int(num_clips)

        def status(icon, msg):
            return f"<p style='color:#cdd6f4;font-family:Inter,sans-serif'>{icon} {msg}</p>"

        yield "", status("⬇️", "Checking model — downloading if first time (~4 GB)..."), gr.update(visible=False)

        if not os.path.exists(llm_path):
            hf_hub_download(
                repo_id=llm_entry["repo"],
                filename=llm_entry["filename"],
                local_dir=LLM_DIR,
                local_dir_use_symlinks=False,
            )

        source_mp4 = os.path.join(WORK_DIR, "source.mp4")
        if url.strip() != _state["current_url"] or not os.path.exists(source_mp4):
            yield "", status("⬇️", "Downloading video..."), gr.update(visible=False)
            _state["current_url"] = url.strip()
            download_video(url.strip(), WORK_DIR, cookie_path=COOKIE_PATH)

        yield "", status("🎤", f"Transcribing with Whisper {wsp_size} — hang tight..."), gr.update(visible=False)
        full_text, words = transcribe_audio(source_mp4, model_size=wsp_size, whisper_dir=WHISPER_DIR)
        _state["word_timestamps"] = words

        yield "", status("🧠", "AI scoring viral moments across full transcript..."), gr.update(visible=False)
        result = get_highlights(full_text, num_clips=n_clips, llm_path=llm_path, gpu_layers=llm_entry["gpu_layers"])
        _state["clips"] = result.get("highlights", [])

        if not _state["clips"]:
            yield "", status("⚠️", "No clips found. Try a different video or increase clip count."), gr.update(visible=False)
            return

        cards_html = "".join(build_clip_card(i + 1, c) for i, c in enumerate(_state["clips"]))
        summary = status("✅", f"Found <strong>{len(_state['clips'])} viral clips</strong>. Select one below to render.")
        yield cards_html, summary, gr.update(visible=True)

    except Exception as e:
        traceback.print_exc()
        yield "", f"<p style='color:#ef4444'>❌ {e}</p>", gr.update(visible=False)


def render_clip(clip_num, face_center, caption_style, aspect_ratio):
    if not _state["clips"]:
        return None, "<p style='color:#ef4444'>Analyze a video first.</p>"

    idx = int(clip_num) - 1
    if idx < 0 or idx >= len(_state["clips"]):
        return None, f"<p style='color:#ef4444'>Choose 1–{len(_state['clips'])}.</p>"

    try:
        clip      = _state["clips"][idx]
        input_mp4 = os.path.join(WORK_DIR, "source.mp4")
        add_subs  = caption_style != "None"

        out_path = render_short(
            input_video=input_mp4,
            clip_data=clip,
            word_timestamps=_state["word_timestamps"] if add_subs else [],
            output_dir=OUTPUT_DIR,
            work_dir=WORK_DIR,
            face_center=face_center,
            add_subs=add_subs,
        )

        fname = os.path.basename(out_path)
        return out_path, f"<p style='color:#a6e3a1'>✅ Rendered: <strong>{fname}</strong></p>"

    except Exception as e:
        traceback.print_exc()
        return None, f"<p style='color:#ef4444'>❌ {e}</p>"


def get_clip_gallery():
    files = sorted(glob.glob(f"{OUTPUT_DIR}/*.mp4"), key=os.path.getmtime, reverse=True)
    return files[:12]


# ── UI ────────────────────────────────────────────────────────────────────────
_css = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');

body, .gradio-container {
    background: #11111b !important;
    font-family: 'Inter', sans-serif !important;
    color: #cdd6f4 !important;
}
.gr-box, .gr-form, .gr-panel { background: #181825 !important; border-color: #313244 !important; }
.gr-button-primary {
    background: linear-gradient(135deg, #cba6f7, #89b4fa) !important;
    color: #11111b !important; font-weight: 700 !important;
    border: none !important; border-radius: 10px !important;
}
.gr-button-secondary {
    background: #313244 !important; color: #cdd6f4 !important;
    border: 1px solid #45475a !important; border-radius: 10px !important;
}
.gr-button-primary:hover { opacity: 0.9 !important; transform: translateY(-1px); }
label span { color: #a6adc8 !important; font-size: 13px !important; font-weight: 600 !important; }
input, textarea, select {
    background: #1e1e2e !important; color: #cdd6f4 !important;
    border: 1px solid #313244 !important; border-radius: 8px !important;
}
.gr-accordion { background: #181825 !important; border: 1px solid #313244 !important; border-radius: 10px !important; }
footer { display: none !important; }
"""

_HERO = """
<div style='text-align:center;padding:32px 0 16px;font-family:Inter,sans-serif'>
  <div style='font-size:13px;letter-spacing:3px;color:#cba6f7;text-transform:uppercase;font-weight:700;margin-bottom:8px'>
    FREE &amp; LOCAL
  </div>
  <h1 style='font-size:36px;font-weight:800;margin:0;
             background:linear-gradient(135deg,#cba6f7 0%,#89b4fa 50%,#a6e3a1 100%);
             -webkit-background-clip:text;-webkit-text-fill-color:transparent'>
    The Clip Factory
  </h1>
  <p style='color:#6c7086;font-size:15px;margin:8px 0 0'>
    Paste a YouTube URL · AI finds viral moments · Get vertical shorts with captions
  </p>
</div>"""

_STEPS = """
<div style='display:flex;justify-content:center;gap:0;margin:12px 0 24px;font-family:Inter,sans-serif'>
  <div style='text-align:center;padding:0 20px'>
    <div style='width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,#cba6f7,#89b4fa);
                display:flex;align-items:center;justify-content:center;font-weight:800;color:#11111b;margin:0 auto 6px'>1</div>
    <div style='font-size:12px;color:#a6adc8'>Drop URL</div>
  </div>
  <div style='display:flex;align-items:center;margin-bottom:20px;color:#313244'>──────</div>
  <div style='text-align:center;padding:0 20px'>
    <div style='width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,#89b4fa,#a6e3a1);
                display:flex;align-items:center;justify-content:center;font-weight:800;color:#11111b;margin:0 auto 6px'>2</div>
    <div style='font-size:12px;color:#a6adc8'>AI Scores</div>
  </div>
  <div style='display:flex;align-items:center;margin-bottom:20px;color:#313244'>──────</div>
  <div style='text-align:center;padding:0 20px'>
    <div style='width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,#a6e3a1,#f9e2af);
                display:flex;align-items:center;justify-content:center;font-weight:800;color:#11111b;margin:0 auto 6px'>3</div>
    <div style='font-size:12px;color:#a6adc8'>Render</div>
  </div>
  <div style='display:flex;align-items:center;margin-bottom:20px;color:#313244'>──────</div>
  <div style='text-align:center;padding:0 20px'>
    <div style='width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,#f9e2af,#f38ba8);
                display:flex;align-items:center;justify-content:center;font-weight:800;color:#11111b;margin:0 auto 6px'>4</div>
    <div style='font-size:12px;color:#a6adc8'>Download</div>
  </div>
</div>"""

with gr.Blocks(title="The Clip Factory", css=_css) as demo:

    gr.HTML(_HERO)
    gr.HTML(_STEPS)

    # ── Step 1: Input + settings ──────────────────────────────────────────────
    with gr.Group():
        with gr.Row():
            url_input = gr.Textbox(
                placeholder="https://www.youtube.com/watch?v=...",
                label="YouTube URL",
                scale=5,
            )
            analyze_btn = gr.Button("🔍 Find Viral Clips", variant="primary", scale=1, min_width=180)

        with gr.Row():
            num_clips_slider = gr.Slider(
                minimum=1, maximum=10, value=5, step=1,
                label="Number of clips to find"
            )

        with gr.Accordion("⚙️ Advanced Settings", open=False):
            with gr.Row():
                llm_drop = gr.Dropdown(
                    choices=[e["label"] for e in LLM_CATALOG],
                    value=LLM_CATALOG[0]["label"],
                    label="AI Model (LLM)",
                    type="index",
                    info="Smaller models (Phi-3, Gemma 2B) use less VRAM",
                )
                wsp_drop = gr.Dropdown(
                    choices=[e["label"] for e in WHISPER_CATALOG],
                    value=WHISPER_CATALOG[3]["label"],
                    label="Transcription Quality (Whisper)",
                    type="index",
                    info="medium = best speed/accuracy balance on T4",
                )

    # ── Step 2: Status + Results ──────────────────────────────────────────────
    status_html = gr.HTML("")

    with gr.Group(visible=False) as results_group:
        gr.HTML("<h3 style='color:#cdd6f4;font-family:Inter,sans-serif;margin:16px 0 4px'>🔥 Viral Clip Candidates</h3>")
        clips_html = gr.HTML("")

    # ── Step 3: Render ────────────────────────────────────────────────────────
    with gr.Group(visible=False) as render_group:
        gr.HTML("<h3 style='color:#cdd6f4;font-family:Inter,sans-serif;margin:24px 0 8px'>🎬 Render a Short</h3>")
        with gr.Row():
            clip_num = gr.Number(value=1, label="Clip # to render", precision=0, minimum=1, maximum=10, scale=1)
            caption_style = gr.Dropdown(
                choices=CAPTION_STYLES,
                value=CAPTION_STYLES[0],
                label="Caption Style",
                scale=2,
            )
            with gr.Column(scale=1):
                face_center = gr.Checkbox(label="AI Subject Tracking (face crop)", value=True)
            aspect_radio = gr.Radio(
                choices=["9:16 (Shorts/Reels/TikTok)", "1:1 (Feed)", "16:9 (YouTube)"],
                value="9:16 (Shorts/Reels/TikTok)",
                label="Aspect Ratio",
                scale=2,
            )
        render_btn = gr.Button("🎬 Render This Clip", variant="primary")
        render_status = gr.HTML("")

    # ── Step 4: Preview + Library ─────────────────────────────────────────────
    with gr.Row():
        with gr.Column(scale=5):
            gr.HTML("<h3 style='color:#cdd6f4;font-family:Inter,sans-serif;margin:24px 0 8px'>▶ Preview</h3>")
            video_preview = gr.Video(label="", height=560)
        with gr.Column(scale=5):
            gr.HTML("<h3 style='color:#cdd6f4;font-family:Inter,sans-serif;margin:24px 0 8px'>📁 Clip Library</h3>")
            gallery = gr.Gallery(
                label="",
                columns=3,
                height=560,
                object_fit="contain",
            )
            refresh_btn = gr.Button("🔄 Refresh Library", variant="secondary")

    # ── Wire events ───────────────────────────────────────────────────────────
    analyze_btn.click(
        analyze_video,
        inputs=[url_input, llm_drop, wsp_drop, num_clips_slider],
        outputs=[clips_html, status_html, results_group],
    ).then(
        lambda: gr.update(visible=True),
        outputs=[render_group],
    )

    render_btn.click(
        render_clip,
        inputs=[clip_num, face_center, caption_style, aspect_radio],
        outputs=[video_preview, render_status],
    )

    refresh_btn.click(get_clip_gallery, outputs=[gallery])

if __name__ == "__main__":
    demo.launch(share=True, debug=True, allowed_paths=[OUTPUT_DIR, WORK_DIR])
else:
    demo.launch(share=True, debug=True, allowed_paths=[OUTPUT_DIR, WORK_DIR])
