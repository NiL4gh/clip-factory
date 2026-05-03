import os
import sys
import glob
import shutil
import traceback
import urllib.request

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
from shorts_generator.enhancer import enhance_clip
from shorts_generator import cache

for d in [WORK_DIR, OUTPUT_DIR, LLM_DIR, WHISPER_DIR, PROJECTS_DIR]:
    os.makedirs(d, exist_ok=True)

_state = {"clips": [], "word_timestamps": [], "current_url": None}

BGM_TRACKS = {
    "None": None,
    "Epic / Cinematic": "https://cdn.pixabay.com/audio/2022/01/18/audio_d0a13f69d2.mp3",
    "Lofi / Chill": "https://cdn.pixabay.com/audio/2022/05/27/audio_1808fbf07a.mp3",
    "Suspense / Hook": "https://cdn.pixabay.com/audio/2022/10/25/audio_24923e2060.mp3",
    "Upbeat / Viral": "https://cdn.pixabay.com/audio/2022/03/15/audio_c8b817bb6b.mp3"
}

THEMES = ["Motivation", "Educational", "Comedy", "Suspense", "Storytime"]

def _sc(s):
    s = int(s)
    if s >= 80: return "#4ade80"
    if s >= 55: return "#facc15"
    return "#f87171"


def _cards(clips, show_all=False):
    vis = clips if show_all else clips[:5]
    extra = max(0, len(clips) - 5)
    rows = ""
    for i, c in enumerate(vis):
        sc = int(c.get("score", 0))
        segs = c.get("segments", [{"start_time": c.get("start_time",0), "end_time": c.get("end_time",0)}])
        st = float(segs[0]["start_time"])
        et = float(segs[-1]["end_time"])
        dur = sum((float(s["end_time"]) - float(s["start_time"])) for s in segs)
        
        title = c.get("title", "")[:55]
        hook = c.get("hook_sentence", "")[:70]
        
        seg_badge = f"<span style='background:#333;padding:2px 6px;border-radius:4px;font-size:10px;margin-left:6px'>{len(segs)} cuts</span>" if len(segs) > 1 else ""
        
        rows += f"""<tr style='border-bottom:1px solid #2a2a2a;cursor:pointer' 
            onclick="document.getElementById('clip-sel').querySelector('input').value={i+1};
            document.getElementById('clip-sel').querySelector('input').dispatchEvent(new Event('input',{{bubbles:true}}));">
          <td style='padding:8px 10px;color:#888;font-size:12px'>#{i+1}</td>
          <td style='padding:8px 0'><span style='font-weight:700;font-size:18px;color:{_sc(sc)}'>{sc}</span></td>
          <td style='padding:8px 10px;font-size:13px;color:#ddd'>{title} {seg_badge}</td>
          <td style='padding:8px 10px;font-size:12px;color:#888'>{st:.0f}s\u2013{et:.0f}s ({dur:.0f}s)</td>
          <td style='padding:8px 10px;font-size:12px;color:#aaa;font-style:italic'>\u201c{hook}\u201d</td>
        </tr>"""
    more = ""
    if extra > 0 and not show_all:
        more = f"<p style='color:#666;font-size:12px;margin:8px 0 0'>+ {extra} more clips available</p>"
    return f"""<table style='width:100%;border-collapse:collapse;font-family:system-ui'>
      <thead><tr style='border-bottom:2px solid #333;text-align:left'>
        <th style='padding:6px 10px;color:#666;font-size:11px'>#</th>
        <th style='padding:6px 0;color:#666;font-size:11px'>SCORE</th>
        <th style='padding:6px 10px;color:#666;font-size:11px'>TITLE</th>
        <th style='padding:6px 10px;color:#666;font-size:11px'>TIME</th>
        <th style='padding:6px 10px;color:#666;font-size:11px'>HOOK</th>
      </tr></thead><tbody>{rows}</tbody></table>{more}"""


def _get_internal_clip_data(idx):
    if not _state["clips"]: return "", "Storytime", "Lofi / Chill"
    i = max(0, min(int(idx)-1, len(_state["clips"])-1))
    c = _state["clips"][i]
    sc = int(c.get("score",0))
    theme = c.get("theme", "Storytime")
    
    music_map = {
        "Motivation": "Epic / Cinematic",
        "Educational": "Lofi / Chill",
        "Comedy": "Upbeat / Viral",
        "Suspense": "Suspense / Hook",
        "Storytime": "Lofi / Chill"
    }
    def_music = music_map.get(theme, "Lofi / Chill")
    
    segs = c.get("segments", [{"start_time": c.get("start_time",0), "end_time": c.get("end_time",0)}])
    st = float(segs[0]["start_time"])
    et = float(segs[-1]["end_time"])
    dur = sum((float(s["end_time"]) - float(s["start_time"])) for s in segs)
    
    seg_html = ""
    if len(segs) > 1:
        seg_html = "<div style='font-size:11px;color:#888;margin-bottom:8px'>Multi-segment stitch: "
        for j, s in enumerate(segs):
            seg_html += f"[{s['start_time']:.0f}s-{s['end_time']:.0f}s] "
        seg_html += "</div>"
        
    html = f"""<div style='background:#1a1a1a;border:1px solid #2a2a2a;border-radius:8px;padding:16px;font-family:system-ui'>
  <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:12px'>
    <div>
        <span style='font-size:12px;color:#666;font-weight:600'>CLIP {i+1}</span>
        <span style='font-size:10px;background:#333;color:#aaa;padding:2px 6px;border-radius:4px;margin-left:8px'>Theme: {theme}</span>
    </div>
    <span style='font-size:28px;font-weight:800;color:{_sc(sc)}'>{sc}<span style='font-size:12px;color:#666'>/100</span></span>
  </div>
  <h3 style='margin:0 0 10px;font-size:15px;color:#eee'>{c.get('title','')}</h3>
  <div style='font-size:13px;color:#888;margin-bottom:4px'>Range: {st:.0f}s \u2192 {et:.0f}s \u00b7 Final duration: {dur:.0f}s</div>
  {seg_html}
  <div style='background:#111;border-radius:6px;padding:10px;margin-bottom:8px'>
    <div style='font-size:10px;color:#666;font-weight:600;margin-bottom:3px'>HOOK</div>
    <div style='font-size:13px;color:#ccc'>\u201c{c.get('hook_sentence','')}\u201d</div>
  </div>
  <div style='background:#111;border-radius:6px;padding:10px'>
    <div style='font-size:10px;color:#666;font-weight:600;margin-bottom:3px'>WHY IT WORKS</div>
    <div style='font-size:13px;color:#aaa'>{c.get('virality_reason','')}</div>
  </div>
</div>"""
    return html, theme, def_music

def on_clip_select(n):
    html, t, m = _get_internal_clip_data(n)
    return html, gr.update(value=t), gr.update(value=m)

def analyze_video(url, llm_idx, wsp_idx, num_clips):
    if not url or not url.strip():
        yield "", "Enter a YouTube URL.", "", gr.update(), gr.update(), gr.update(visible=False)
        return
    try:
        llm_entry = LLM_CATALOG[int(llm_idx)]
        wsp_size  = WHISPER_CATALOG[int(wsp_idx)]["size"]
        llm_path  = os.path.join(LLM_DIR, llm_entry["filename"])
        n = int(num_clips)

        cached_h = cache.load_highlights(url.strip())
        cached_t = cache.load_transcript(url.strip())
        if cached_h and cached_t:
            _state["clips"] = cached_h
            _state["word_timestamps"] = cached_t[1]
            _state["current_url"] = url.strip()
            html, t, m = _get_internal_clip_data(1)
            yield _cards(_state["clips"]), f"Loaded {len(cached_h)} cached clips.", html, gr.update(value=t), gr.update(value=m), gr.update(visible=True)
            return

        yield "", "Checking model...", "", gr.update(), gr.update(), gr.update(visible=False)
        if not os.path.exists(llm_path):
            yield "", f"Downloading {llm_entry['label']} (~4 GB, one-time)...", "", gr.update(), gr.update(), gr.update(visible=False)
            hf_hub_download(repo_id=llm_entry["repo"], filename=llm_entry["filename"],
                           local_dir=LLM_DIR, local_dir_use_symlinks=False)

        source_mp4 = os.path.join(WORK_DIR, "source.mp4")
        yield "", "Downloading video...", "", gr.update(), gr.update(), gr.update(visible=False)
        _state["current_url"] = url.strip()
        download_video(url.strip(), WORK_DIR, cookie_path=COOKIE_PATH)

        yield "", f"Transcribing ({wsp_size})...", "", gr.update(), gr.update(), gr.update(visible=False)
        full_text, words = transcribe_audio(source_mp4, model_size=wsp_size, whisper_dir=WHISPER_DIR)
        _state["word_timestamps"] = words
        cache.save_transcript(url.strip(), full_text, words)

        yield "", "AI scoring multi-segment viral moments...", "", gr.update(), gr.update(), gr.update(visible=False)
        result = get_highlights(full_text, num_clips=n, llm_path=llm_path,
                               gpu_layers=llm_entry["gpu_layers"], max_clips=20)
        _state["clips"] = result.get("highlights", [])
        cache.save_highlights(url.strip(), _state["clips"])
        cache.save_metadata(url.strip())

        if not _state["clips"]:
            yield "", "No clips found. Try a different video.", "", gr.update(), gr.update(), gr.update(visible=False)
            return

        html, t, m = _get_internal_clip_data(1)
        yield _cards(_state["clips"]), f"Found {len(_state['clips'])} clips.", html, gr.update(value=t), gr.update(value=m), gr.update(visible=True)
    except Exception as e:
        traceback.print_exc()
        yield "", f"Error: {e}", "", gr.update(), gr.update(), gr.update(visible=False)


def show_all():
    return _cards(_state["clips"], show_all=True) if _state["clips"] else ""

def render_clip(clip_num, face_center, cap_style_str, bg_music_genre):
    if not _state["clips"]:
        return None, "Analyse a video first."
    idx = int(clip_num) - 1
    if idx < 0 or idx >= len(_state["clips"]):
        return None, f"Choose 1\u2013{len(_state['clips'])}."
    try:
        clip = _state["clips"][idx]
        input_mp4 = os.path.join(WORK_DIR, "source.mp4")
        clips_dir = cache.get_clips_dir(_state["current_url"]) if _state["current_url"] else OUTPUT_DIR
        
        out = render_short(
            input_video=input_mp4, clip_data=clip,
            word_timestamps=_state["word_timestamps"] if cap_style_str != "None" else [],
            output_dir=clips_dir, work_dir=WORK_DIR,
            face_center=face_center, add_subs=(cap_style_str != "None"),
            theme=cap_style_str
        )
        
        if bg_music_genre and bg_music_genre != "None":
            music_url = BGM_TRACKS[bg_music_genre]
            music_path = os.path.join(WORK_DIR, f"{bg_music_genre.replace(' ', '_').replace('/', '')}.mp3")
            
            if not os.path.exists(music_path):
                urllib.request.urlretrieve(music_url, music_path)
                
            enhance_clip(out, clip, music_path=music_path)
        
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        dst = os.path.join(OUTPUT_DIR, os.path.basename(out))
        if out != dst:
            shutil.copy2(out, dst)
            
        return out, f"Rendered: {os.path.basename(out)}"
    except Exception as e:
        traceback.print_exc()
        return None, f"Error: {e}"

def get_gallery():
    files = []
    for d in [OUTPUT_DIR]:
        files.extend(glob.glob(f"{d}/*.mp4"))
    if _state.get("current_url"):
        files.extend(glob.glob(f"{cache.get_clips_dir(_state['current_url'])}/*.mp4"))
    seen, unique = set(), []
    for f in sorted(files, key=os.path.getmtime, reverse=True):
        b = os.path.basename(f)
        if b not in seen:
            seen.add(b)
            unique.append(f)
    return unique[:12]

def load_history(choice):
    if not choice: return gr.update(), "", "", gr.update(), gr.update(), gr.update(visible=False)
    vid = choice.split(" | ")[0].strip()
    for p in cache.list_projects():
        if p.get("video_id") == vid:
            url = p.get("url", "")
            h = cache.load_highlights(url)
            t = cache.load_transcript(url)
            if h and t:
                _state["clips"], _state["word_timestamps"] = h, t[1]
                _state["current_url"] = url
                html, thm, mus = _get_internal_clip_data(1)
                return url, _cards(h), html, gr.update(value=thm), gr.update(value=mus), gr.update(visible=True)
    return gr.update(), "", "", gr.update(), gr.update(), gr.update(visible=False)

def history_list():
    return [f"{p['video_id']} | {p.get('url','')}" for p in cache.list_projects()] or []


_css = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
body,.gradio-container{background:#0f0f0f!important;font-family:'Inter',system-ui,sans-serif!important;color:#e0e0e0!important}
.gr-box,.gr-form,.gr-panel,.gr-group{background:#161616!important;border-color:#2a2a2a!important}
.gr-button-primary{background:#fff!important;color:#000!important;font-weight:600!important;border:none!important;border-radius:6px!important}
.gr-button-primary:hover{background:#e0e0e0!important}
.gr-button-secondary{background:#1a1a1a!important;color:#ccc!important;border:1px solid #333!important;border-radius:6px!important}
label span{color:#888!important;font-size:12px!important;font-weight:500!important}
input,textarea,select{background:#1a1a1a!important;color:#e0e0e0!important;border:1px solid #2a2a2a!important;border-radius:6px!important}
.gr-accordion{background:#161616!important;border:1px solid #2a2a2a!important;border-radius:6px!important}
footer{display:none!important}
"""

with gr.Blocks(title="Clip Factory", css=_css) as demo:
    gr.HTML("<div style='padding:16px 0 8px;font-family:Inter,system-ui'>"
            "<h1 style='font-size:22px;font-weight:700;color:#fff;margin:0'>Clip Factory</h1>"
            "<p style='font-size:13px;color:#666;margin:4px 0 0'>Paste a video URL. AI finds the best clips. Render and download.</p></div>")

    with gr.Row():
        url_input = gr.Textbox(placeholder="https://youtube.com/watch?v=...", label="Video URL", scale=5)
        analyze_btn = gr.Button("Analyse", variant="primary", scale=1, min_width=100)

    with gr.Row():
        num_clips = gr.Slider(1, 10, value=5, step=1, label="Top clips to show", scale=3)
        history_drop = gr.Dropdown(choices=history_list(), label="Previously processed", scale=3, interactive=True)
        load_btn = gr.Button("Load", variant="secondary", scale=1, min_width=60)

    with gr.Accordion("Settings", open=False):
        with gr.Row():
            llm_drop = gr.Dropdown([e["label"] for e in LLM_CATALOG], value=LLM_CATALOG[0]["label"],
                                  label="AI Model", type="index", scale=1)
            wsp_drop = gr.Dropdown([e["label"] for e in WHISPER_CATALOG], value=WHISPER_CATALOG[3]["label"],
                                  label="Whisper", type="index", scale=1)

    status_box = gr.Textbox(label="Status", interactive=False, lines=1)
    clips_html = gr.HTML("")
    show_all_btn = gr.Button("Show all clips", variant="secondary", visible=False)

    with gr.Group(visible=False) as detail_group:
        with gr.Row():
            with gr.Column(scale=6):
                detail_html = gr.HTML("")
            with gr.Column(scale=4):
                clip_num = gr.Number(value=1, label="Clip #", precision=0, minimum=1, maximum=20, elem_id="clip-sel")
                
                with gr.Accordion("Automated Enhancements", open=True):
                    face_cb = gr.Checkbox(label="Smart Visual Edit (AI Face Center)", value=True)
                    cap_style = gr.Dropdown(choices=THEMES + ["None"], value="Storytime", label="Caption Style (Auto-detected)")
                    bg_music = gr.Dropdown(
                        choices=list(BGM_TRACKS.keys()), 
                        value="Lofi / Chill",
                        label="Smart Background Music (Auto-ducking)"
                    )
                    
                render_btn = gr.Button("Render clip", variant="primary")
                render_status = gr.Textbox(label="", interactive=False, lines=1)

    with gr.Row():
        video_preview = gr.Video(label="Preview", height=420, scale=5)
        gallery = gr.Gallery(label="Rendered clips", columns=3, height=420, object_fit="contain", scale=5)
    refresh_btn = gr.Button("Refresh library", variant="secondary")

    # Events
    analyze_btn.click(analyze_video, [url_input, llm_drop, wsp_drop, num_clips],
                      [clips_html, status_box, detail_html, cap_style, bg_music, detail_group]).then(
                      lambda: gr.update(visible=True), outputs=[show_all_btn])
                      
    clip_num.change(on_clip_select, [clip_num], [detail_html, cap_style, bg_music])
    
    show_all_btn.click(show_all, outputs=[clips_html])
    
    render_btn.click(render_clip, [clip_num, face_cb, cap_style, bg_music], [video_preview, render_status])
    
    refresh_btn.click(get_gallery, outputs=[gallery])
    
    load_btn.click(load_history, [history_drop], [url_input, clips_html, detail_html, cap_style, bg_music, detail_group])

if __name__ == "__main__":
    demo.launch(share=True, debug=True, allowed_paths=[OUTPUT_DIR, WORK_DIR, PROJECTS_DIR, BASE_DIR])
else:
    demo.launch(share=True, debug=True, allowed_paths=[OUTPUT_DIR, WORK_DIR, PROJECTS_DIR, BASE_DIR])
