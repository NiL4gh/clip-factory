import os
import sys
import glob
import shutil
import traceback

import gradio as gr
from huggingface_hub import hf_hub_download

try:
    REPO_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    REPO_DIR = os.getcwd()

if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

from shorts_generator.config import (
    BASE_DIR, WORK_DIR, OUTPUT_DIR, LLM_DIR, WHISPER_DIR,
    COOKIE_PATH, LLM_CATALOG, WHISPER_CATALOG, PROJECTS_DIR,
)
from shorts_generator.downloader import download_video
from shorts_generator.transcriber import transcribe_audio
from shorts_generator.highlights import get_highlights
from shorts_generator.clipper import render_short
from shorts_generator import cache

for d in [WORK_DIR, OUTPUT_DIR, LLM_DIR, WHISPER_DIR, PROJECTS_DIR]:
    os.makedirs(d, exist_ok=True)

_state = {
    "clips": [],
    "word_timestamps": [],
    "current_url": None,
}


def score_color(s: int) -> str:
    if s >= 80: return "#22c55e"
    if s >= 55: return "#f59e0b"
    return "#ef4444"


def build_cards_html(clips, show_all=False):
    visible = clips if show_all else clips[:5]
    extra = len(clips) - 5
    cards = ""
    for i, c in enumerate(visible):
        sc = int(c.get("score", 0))
        col = score_color(sc)
        st = float(c.get("start_time", 0))
        et = float(c.get("end_time", 0))
        dur = max(0, et - st)
        title = c.get("title", f"Clip {i+1}")[:50]
        hook = c.get("hook_sentence", "")[:80]
        cards += f"""
<div onclick="document.getElementById('clip-num-input').querySelector('input').value={i+1};
     document.getElementById('clip-num-input').querySelector('input').dispatchEvent(new Event('input', {{bubbles:true}}));"
     style='background:#1e1e2e;border:1px solid #313244;border-radius:10px;padding:12px;
            cursor:pointer;transition:all .15s;flex:0 0 180px;min-width:160px'
     onmouseover="this.style.borderColor='#89b4fa'" onmouseout="this.style.borderColor='#313244'">
  <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:6px'>
    <span style='font-size:10px;color:#6c7086;font-weight:700'>#{i+1}</span>
    <span style='font-size:22px;font-weight:800;color:{col}'>{sc}</span>
  </div>
  <div style='width:100%;background:#313244;border-radius:4px;height:4px;margin-bottom:8px'>
    <div style='width:{sc}%;background:{col};height:100%;border-radius:4px'></div>
  </div>
  <div style='font-size:12px;color:#cdd6f4;font-weight:600;margin-bottom:4px;
              overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>{title}</div>
  <div style='font-size:11px;color:#6c7086'>{st:.0f}s \u2192 {et:.0f}s \u00b7 {dur:.0f}s</div>
  <div style='font-size:11px;color:#a6e3a1;margin-top:4px;overflow:hidden;
              text-overflow:ellipsis;white-space:nowrap'>\u201c{hook}\u201d</div>
</div>"""

    show_more = ""
    if extra > 0 and not show_all:
        show_more = f"<div style='color:#89b4fa;font-size:13px;margin-top:12px;cursor:pointer'>\u25bc {extra} more clips available</div>"

    return f"""<div style='display:flex;gap:10px;overflow-x:auto;padding:8px 0'>{cards}</div>{show_more}"""


def build_detail_html(clip_idx):
    if not _state["clips"]:
        return "<p style='color:#6c7086'>No clips analysed yet.</p>"
    idx = max(0, min(int(clip_idx) - 1, len(_state["clips"]) - 1))
    c = _state["clips"][idx]
    sc = int(c.get("score", 0))
    col = score_color(sc)
    st = float(c.get("start_time", 0))
    et = float(c.get("end_time", 0))
    return f"""
<div style='background:#1e1e2e;border:1px solid #313244;border-radius:12px;padding:20px'>
  <div style='display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px'>
    <div>
      <span style='font-size:11px;color:#6c7086;font-weight:700;text-transform:uppercase'>CLIP {idx+1}</span>
      <h3 style='margin:4px 0;font-size:17px;color:#cdd6f4'>{c.get('title','Untitled')}</h3>
    </div>
    <div style='text-align:right'>
      <div style='font-size:32px;font-weight:800;color:{col}'>{sc}</div>
      <div style='font-size:10px;color:#6c7086'>Virality Score</div>
    </div>
  </div>
  <div style='width:100%;background:#313244;border-radius:6px;height:6px;margin-bottom:14px'>
    <div style='width:{sc}%;background:{col};height:100%;border-radius:6px'></div>
  </div>
  <div style='display:flex;gap:16px;margin-bottom:14px;font-size:13px;color:#89b4fa'>
    <span>\u23f1 {st:.0f}s \u2192 {et:.0f}s</span>
    <span>\u00b7</span>
    <span>\ud83c\udfac {max(0, et-st):.0f}s clip</span>
  </div>
  <div style='background:#181825;border-radius:8px;padding:12px;margin-bottom:10px'>
    <div style='font-size:11px;color:#6c7086;font-weight:600;margin-bottom:4px'>HOOK</div>
    <div style='font-size:14px;color:#a6e3a1'>\u201c{c.get('hook_sentence','')}\u201d</div>
  </div>
  <div style='background:#181825;border-radius:8px;padding:12px'>
    <div style='font-size:11px;color:#6c7086;font-weight:600;margin-bottom:4px'>WHY IT WORKS</div>
    <div style='font-size:13px;color:#cdd6f4'>{c.get('virality_reason','')}</div>
  </div>
</div>"""


def history_choices():
    projects = cache.list_projects()
    if not projects:
        return []
    return [f"{p.get('video_id','')} \u2014 {p.get('url','')}" for p in projects]


def analyze_video(url, llm_idx, wsp_idx, num_clips, language):
    if not url or not url.strip():
        yield "", "<p style='color:#ef4444'>Enter a YouTube URL.</p>", "", gr.update(visible=False)
        return
    try:
        llm_entry = LLM_CATALOG[int(llm_idx)]
        wsp_size  = WHISPER_CATALOG[int(wsp_idx)]["size"]
        llm_path  = os.path.join(LLM_DIR, llm_entry["filename"])
        n = int(num_clips)
        lang = language.strip() if language and language.strip() else None

        def st(icon, msg):
            return f"<p style='color:#cdd6f4;font-family:Inter,sans-serif'>{icon} {msg}</p>"

        # Check cache first
        cached_h = cache.load_highlights(url.strip())
        cached_t = cache.load_transcript(url.strip())
        if cached_h and cached_t:
            _state["clips"] = cached_h
            _state["word_timestamps"] = cached_t[1]
            _state["current_url"] = url.strip()
            cards = build_cards_html(_state["clips"])
            detail = build_detail_html(1)
            yield cards, st("\u26a1", f"Loaded {len(cached_h)} clips from cache."), detail, gr.update(visible=True)
            return

        yield "", st("\u2b07\ufe0f", "Checking model..."), "", gr.update(visible=False)
        if not os.path.exists(llm_path):
            yield "", st("\u2b07\ufe0f", f"Downloading {llm_entry['label']} (~4 GB)..."), "", gr.update(visible=False)
            hf_hub_download(repo_id=llm_entry["repo"], filename=llm_entry["filename"],
                           local_dir=LLM_DIR, local_dir_use_symlinks=False)

        source_mp4 = os.path.join(WORK_DIR, "source.mp4")
        if url.strip() != _state["current_url"] or not os.path.exists(source_mp4):
            yield "", st("\u2b07\ufe0f", "Downloading video..."), "", gr.update(visible=False)
            _state["current_url"] = url.strip()
            download_video(url.strip(), WORK_DIR, cookie_path=COOKIE_PATH)

        yield "", st("\ud83c\udfa4", f"Transcribing ({wsp_size})..."), "", gr.update(visible=False)
        full_text, words = transcribe_audio(source_mp4, model_size=wsp_size, whisper_dir=WHISPER_DIR, language=lang)
        _state["word_timestamps"] = words
        cache.save_transcript(url.strip(), full_text, words)

        yield "", st("\ud83e\udde0", "AI scoring viral moments..."), "", gr.update(visible=False)
        result = get_highlights(full_text, num_clips=n, llm_path=llm_path,
                               gpu_layers=llm_entry["gpu_layers"], max_clips=20, language=lang or "")
        _state["clips"] = result.get("highlights", [])
        cache.save_highlights(url.strip(), _state["clips"])
        cache.save_metadata(url.strip())

        if not _state["clips"]:
            yield "", st("\u26a0\ufe0f", "No clips found."), "", gr.update(visible=False)
            return

        cards = build_cards_html(_state["clips"])
        detail = build_detail_html(1)
        yield cards, st("\u2705", f"{len(_state['clips'])} viral clips found."), detail, gr.update(visible=True)

    except Exception as e:
        traceback.print_exc()
        yield "", f"<p style='color:#ef4444'>\u274c {e}</p>", "", gr.update(visible=False)


def on_clip_select(clip_num):
    return build_detail_html(clip_num)


def show_all_clips():
    if not _state["clips"]:
        return ""
    return build_cards_html(_state["clips"], show_all=True)


def render_clip(clip_num, face_center, add_subs):
    if not _state["clips"]:
        return None, "<p style='color:#ef4444'>Analyse a video first.</p>"
    idx = int(clip_num) - 1
    if idx < 0 or idx >= len(_state["clips"]):
        return None, f"<p style='color:#ef4444'>Choose 1\u2013{len(_state['clips'])}.</p>"
    try:
        clip = _state["clips"][idx]
        input_mp4 = os.path.join(WORK_DIR, "source.mp4")
        clips_dir = cache.get_clips_dir(_state["current_url"]) if _state["current_url"] else OUTPUT_DIR

        out_path = render_short(
            input_video=input_mp4, clip_data=clip,
            word_timestamps=_state["word_timestamps"] if add_subs else [],
            output_dir=clips_dir, work_dir=WORK_DIR,
            face_center=face_center, add_subs=add_subs,
        )
        # Copy to main output too
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        dst = os.path.join(OUTPUT_DIR, os.path.basename(out_path))
        if out_path != dst:
            shutil.copy2(out_path, dst)

        return out_path, f"<p style='color:#a6e3a1'>\u2705 Rendered: <b>{os.path.basename(out_path)}</b></p>"
    except Exception as e:
        traceback.print_exc()
        return None, f"<p style='color:#ef4444'>\u274c {e}</p>"


def get_gallery():
    files = []
    for d in [OUTPUT_DIR]:
        files.extend(glob.glob(f"{d}/*.mp4"))
    if _state.get("current_url"):
        cd = cache.get_clips_dir(_state["current_url"])
        files.extend(glob.glob(f"{cd}/*.mp4"))
    seen = set()
    unique = []
    for f in sorted(files, key=os.path.getmtime, reverse=True):
        bn = os.path.basename(f)
        if bn not in seen:
            seen.add(bn)
            unique.append(f)
    return unique[:12]


def load_from_history(choice):
    if not choice:
        return gr.update(), "", "", gr.update(visible=False)
    vid = choice.split(" \u2014 ")[0].strip()
    projects = cache.list_projects()
    for p in projects:
        if p.get("video_id") == vid:
            url = p.get("url", "")
            cached_h = cache.load_highlights(url)
            cached_t = cache.load_transcript(url)
            if cached_h and cached_t:
                _state["clips"] = cached_h
                _state["word_timestamps"] = cached_t[1]
                _state["current_url"] = url
                cards = build_cards_html(_state["clips"])
                detail = build_detail_html(1)
                return url, cards, detail, gr.update(visible=True)
    return gr.update(), "", "", gr.update(visible=False)


# \u2500\u2500 CSS \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
_css = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');
body,.gradio-container{background:#11111b!important;font-family:'Inter',sans-serif!important;color:#cdd6f4!important}
.gr-box,.gr-form,.gr-panel{background:#181825!important;border-color:#313244!important}
.gr-button-primary{background:linear-gradient(135deg,#cba6f7,#89b4fa)!important;
  color:#11111b!important;font-weight:700!important;border:none!important;border-radius:10px!important}
.gr-button-secondary{background:#313244!important;color:#cdd6f4!important;
  border:1px solid #45475a!important;border-radius:10px!important}
.gr-button-primary:hover{opacity:.9!important}
label span{color:#a6adc8!important;font-size:13px!important;font-weight:600!important}
input,textarea,select{background:#1e1e2e!important;color:#cdd6f4!important;
  border:1px solid #313244!important;border-radius:8px!important}
.gr-accordion{background:#181825!important;border:1px solid #313244!important;border-radius:10px!important}
footer{display:none!important}
"""

_HERO = """
<div style='text-align:center;padding:20px 0 8px'>
  <div style='font-size:11px;letter-spacing:3px;color:#cba6f7;text-transform:uppercase;font-weight:700'>FREE &amp; LOCAL</div>
  <h1 style='font-size:32px;font-weight:800;margin:4px 0;
             background:linear-gradient(135deg,#cba6f7,#89b4fa,#a6e3a1);
             -webkit-background-clip:text;-webkit-text-fill-color:transparent'>Clip Factory</h1>
  <p style='color:#6c7086;font-size:13px;margin:4px 0'>Paste URL \u2192 AI finds viral moments \u2192 Render vertical shorts with captions</p>
</div>"""

with gr.Blocks(title="Clip Factory", css=_css) as demo:
    gr.HTML(_HERO)

    # \u2500\u2500 Input row \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    with gr.Row():
        url_input = gr.Textbox(placeholder="https://youtube.com/watch?v=...", label="YouTube URL", scale=5)
        analyze_btn = gr.Button("\ud83d\udd0d Find Viral Clips", variant="primary", scale=1, min_width=160)

    with gr.Row():
        num_clips = gr.Slider(1, 10, value=5, step=1, label="Show top N clips", scale=2)
        history_drop = gr.Dropdown(choices=history_choices(), label="\ud83d\udcc2 History", scale=2, interactive=True)
        load_hist_btn = gr.Button("Load", variant="secondary", scale=1, min_width=80)

    with gr.Accordion("\u2699\ufe0f Settings", open=False):
        with gr.Row():
            llm_drop = gr.Dropdown([e["label"] for e in LLM_CATALOG], value=LLM_CATALOG[0]["label"],
                                  label="AI Model", type="index", scale=2)
            wsp_drop = gr.Dropdown([e["label"] for e in WHISPER_CATALOG], value=WHISPER_CATALOG[3]["label"],
                                  label="Whisper Quality", type="index", scale=2)
            lang_input = gr.Textbox(label="Language", placeholder="auto (or bn, en, es...)", scale=1)

    # \u2500\u2500 Status \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    status_html = gr.HTML("")

    # \u2500\u2500 Clip cards (horizontal scroll) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    clips_html = gr.HTML("")
    show_all_btn = gr.Button("Show All Clips", variant="secondary", visible=False)

    # \u2500\u2500 Detail + Render panel \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    with gr.Group(visible=False) as detail_group:
        with gr.Row():
            with gr.Column(scale=6):
                detail_html = gr.HTML("")
            with gr.Column(scale=4):
                gr.HTML("<h4 style='color:#cdd6f4;margin:0 0 8px'>Render Settings</h4>")
                clip_num = gr.Number(value=1, label="Clip #", precision=0, minimum=1, maximum=20,
                                    elem_id="clip-num-input")
                face_cb = gr.Checkbox(label="AI Face Tracking", value=True)
                subs_cb = gr.Checkbox(label="Burn Captions", value=True)
                render_btn = gr.Button("\ud83c\udfac Render This Clip", variant="primary")
                render_status = gr.HTML("")

    # \u2500\u2500 Preview + Library \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    with gr.Row():
        video_preview = gr.Video(label="Preview", height=480, scale=5)
        gallery = gr.Gallery(label="Clip Library", columns=3, height=480, object_fit="contain", scale=5)
    refresh_btn = gr.Button("\ud83d\udd04 Refresh Library", variant="secondary")

    # \u2500\u2500 Wire events \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    analyze_btn.click(
        analyze_video,
        inputs=[url_input, llm_drop, wsp_drop, num_clips, lang_input],
        outputs=[clips_html, status_html, detail_html, detail_group],
    ).then(lambda: gr.update(visible=True), outputs=[show_all_btn])

    clip_num.change(on_clip_select, inputs=[clip_num], outputs=[detail_html])
    show_all_btn.click(show_all_clips, outputs=[clips_html])
    render_btn.click(render_clip, inputs=[clip_num, face_cb, subs_cb], outputs=[video_preview, render_status])
    refresh_btn.click(get_gallery, outputs=[gallery])
    load_hist_btn.click(load_from_history, inputs=[history_drop],
                        outputs=[url_input, clips_html, detail_html, detail_group])


if __name__ == "__main__":
    demo.launch(share=True, debug=True, allowed_paths=[OUTPUT_DIR, WORK_DIR, PROJECTS_DIR, BASE_DIR])
else:
    demo.launch(share=True, debug=True, allowed_paths=[OUTPUT_DIR, WORK_DIR, PROJECTS_DIR, BASE_DIR])
