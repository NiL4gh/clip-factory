import os
import sys
import glob
import uuid
import subprocess
import traceback

import gradio as gr
from huggingface_hub import hf_hub_download

# ── Resolve repo root — works whether launched via `python app.py`
#    or via `exec(open('app.py').read())` in Colab (where __file__ is not set)
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

# ── Ensure directories exist ─────────────────────────────────────
for d in [WORK_DIR, OUTPUT_DIR, LLM_DIR, WHISPER_DIR]:
    os.makedirs(d, exist_ok=True)

# ── Session state ─────────────────────────────────────────────────
_state = {
    "clips": [],
    "word_timestamps": [],
    "current_url": None,
}

# ─────────────────────────────────────────────────────────────────
def analyze_video(url, llm_idx, wsp_idx):
    try:
        llm_entry = LLM_CATALOG[int(llm_idx)]
        wsp_size  = WHISPER_CATALOG[int(wsp_idx)]["size"]
        llm_path  = os.path.join(LLM_DIR, llm_entry["filename"])

        yield gr.update(), "⬇️ Checking LLM model..."

        if not os.path.exists(llm_path):
            yield gr.update(), f"⬇️ Downloading {llm_entry['label']} (first time only, ~4 GB)..."
            hf_hub_download(
                repo_id=llm_entry["repo"],
                filename=llm_entry["filename"],
                local_dir=LLM_DIR,
                local_dir_use_symlinks=False,
            )

        # Skip re-download for same URL
        source_mp4 = os.path.join(WORK_DIR, "source.mp4")
        if url != _state["current_url"] or not os.path.exists(source_mp4):
            yield gr.update(), "⬇️ Downloading video..."
            _state["current_url"] = url
            download_video(url, WORK_DIR, cookie_path=COOKIE_PATH)

        yield gr.update(), "🎤 Transcribing audio (this takes a minute)..."
        full_text, words = transcribe_audio(
            source_mp4,
            model_size=wsp_size,
            whisper_dir=WHISPER_DIR,
        )
        _state["word_timestamps"] = words

        yield gr.update(), "🧠 AI scoring viral moments..."
        result = get_highlights(
            full_text,
            num_clips=5,
            llm_path=llm_path,
            gpu_layers=llm_entry["gpu_layers"],
        )
        _state["clips"] = result.get("highlights", [])

        table = [
            [
                i + 1,
                c.get("title", "Clip"),
                f"🔥 {c.get('score', 0)}/100",
                f"{c.get('start_time', c.get('start', 0)):.0f}s → {c.get('end_time', c.get('end', 0)):.0f}s",
                c.get("hook_sentence", c.get("reason", "")),
                c.get("virality_reason", ""),
            ]
            for i, c in enumerate(_state["clips"])
        ]
        yield table, f"✅ Found {len(_state['clips'])} viral clips. Enter a clip # and hit Render."

    except Exception as e:
        traceback.print_exc()
        yield gr.update(), f"❌ {e}"

def render_clip(idx_str, face_center, add_subs):
    try:
        if not _state["clips"]:
            return None, [], "❌ Analyze a video first."

        idx  = int(idx_str) - 1
        if idx < 0 or idx >= len(_state["clips"]):
            return None, [], f"❌ Invalid clip number. Choose 1–{len(_state['clips'])}."

        clip      = _state["clips"][idx]
        input_mp4 = os.path.join(WORK_DIR, "source.mp4")

        out_path = render_short(
            input_video=input_mp4,
            clip_data=clip,
            word_timestamps=_state["word_timestamps"] if add_subs else [],
            output_dir=OUTPUT_DIR,
            work_dir=WORK_DIR,
            face_center=face_center,
            add_subs=add_subs,
        )

        gallery = sorted(glob.glob(f"{OUTPUT_DIR}/*.mp4"), key=os.path.getmtime, reverse=True)[:6]
        return out_path, gallery, f"✅ Rendered: {os.path.basename(out_path)}"

    except Exception as e:
        traceback.print_exc()
        return None, [], f"❌ {e}"

with gr.Blocks(title="The Clip Factory Pro", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# ✂️ The Clip Factory Pro\n> Convert long-form content into viral shorts — fully local, free.")

    with gr.Row():
        # ── Left panel ───────────────────────────────────────────
        with gr.Column(scale=3):
            gr.Markdown("### 1 · Engine Setup")
            url_input = gr.Textbox(label="Video URL", placeholder="Paste YouTube URL...")
            llm_drop  = gr.Dropdown(
                choices=[e["label"] for e in LLM_CATALOG],
                value=LLM_CATALOG[0]["label"],
                label="LLM Intelligence",
                type="index",
            )
            wsp_drop  = gr.Dropdown(
                choices=[e["label"] for e in WHISPER_CATALOG],
                value=WHISPER_CATALOG[3]["label"],
                label="Whisper Accuracy",
                type="index",
            )
            cookie_status = (
                "✅ Cookie auth active" if os.path.exists(COOKIE_PATH)
                else "⚠️ No cookie file — age-restricted videos may fail"
            )
            gr.Markdown(f"*{cookie_status}*")
            analyze_btn = gr.Button("🔍 Analyze & Score Video", variant="primary", size="lg")

            gr.HTML("<hr style='margin:16px 0'>")

            gr.Markdown("### 2 · Render Settings")
            render_idx = gr.Number(
                label="Clip # to Render", value=1, precision=0, minimum=1, maximum=10
            )
            with gr.Row():
                face_center = gr.Checkbox(label="AI Subject Tracking", value=True)
                sub_toggle  = gr.Checkbox(label="Hormozi Captions", value=True)
            render_btn = gr.Button("🎬 Render Short", variant="secondary", size="lg")
            status_box = gr.Textbox(label="Status", interactive=False, lines=2)

        # ── Right panel ──────────────────────────────────────────
        with gr.Column(scale=7):
            gr.Markdown("### AI Virality Matrix")
            results_table = gr.Dataframe(
                headers=["#", "Title", "Score", "Timestamps", "Hook", "Why It Works"],
                interactive=False,
                wrap=True,
            )
            gr.HTML("<hr style='margin:16px 0'>")
            with gr.Row():
                video_preview = gr.Video(label="▶ Preview", height=520)
                gallery       = gr.Gallery(
                    label="📁 Clip Library",
                    columns=2,
                    height=520,
                    object_fit="contain",
                )

    # ── Wire events ───────────────────────────────────────────────
    analyze_btn.click(
        analyze_video,
        inputs=[url_input, llm_drop, wsp_drop],
        outputs=[results_table, status_box],
    )
    render_btn.click(
        render_clip,
        inputs=[render_idx, face_center, sub_toggle],
        outputs=[video_preview, gallery, status_box],
    )


if __name__ == "__main__":
    demo.launch(share=True, debug=True)
else:
    # Launched via exec() in Colab
    demo.launch(share=True, debug=True)
