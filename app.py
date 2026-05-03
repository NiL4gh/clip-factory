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

_state = {"clips": [], "word_timestamps": [], "current_url": None, "transcript_sentences": []}

BGM_TRACKS = {
    "None": None,
    "Epic / Cinematic": "https://cdn.pixabay.com/audio/2022/01/18/audio_d0a13f69d2.mp3",
    "Lofi / Chill": "https://cdn.pixabay.com/audio/2022/05/27/audio_1808fbf07a.mp3",
    "Suspense / Hook": "https://cdn.pixabay.com/audio/2022/10/25/audio_24923e2060.mp3",
    "Upbeat / Viral": "https://cdn.pixabay.com/audio/2022/03/15/audio_c8b817bb6b.mp3"
}

CAPTION_STYLES = ["Hormozi", "Standard", "Minimalist", "None"]
CAPTION_POSITIONS = ["Top", "Center", "Bottom"]

def _sc(s):
    s = int(s)
    if s >= 80: return "#4ade80" 
    if s >= 60: return "#facc15" 
    return "#f87171" 

def _cards(clips):
    rows = ""
    for i, c in enumerate(clips):
        sc = int(c.get("score", 0))
        st = float(c.get("start_time", 0))
        et = float(c.get("end_time", 0))
        dur = et - st
        title = c.get("title", "")[:60]
        theme = c.get("theme", "Storytime")
        
        rows += f"""
        <div class="clip-card" onclick="document.getElementById('clip-sel').querySelector('input').value={i+1}; document.getElementById('clip-sel').querySelector('input').dispatchEvent(new Event('input',{{bubbles:true}}));">
            <div class="card-header">
                <span class="card-badge">#{i+1} &bull; {theme}</span>
                <span class="card-score" style="color:{_sc(sc)}">{sc}<span class="score-max">/100</span></span>
            </div>
            <div class="card-title">{title}</div>
            <div class="card-meta">{st:.0f}s - {et:.0f}s ({dur:.0f}s)</div>
            
            <div class="viral-meter-bg">
                <div class="viral-meter-fill" style="width:{sc}%; background:{_sc(sc)}"></div>
            </div>
        </div>
        """
    return f"""<div class="card-grid">{rows}</div>"""

def _get_internal_clip_data(idx):
    if not _state["clips"]: 
        return "", "", 0, 0, "Hormozi", "Center", "None", gr.update(choices=[], value=[])
        
    i = max(0, min(int(idx)-1, len(_state["clips"])-1))
    c = _state["clips"][i]
    
    st = float(c.get("start_time", 0))
    et = float(c.get("end_time", 0))
    theme = c.get("theme", "Storytime")
    
    music_map = {
        "Motivation": "Epic / Cinematic",
        "Educational": "Lofi / Chill",
        "Comedy": "Upbeat / Viral",
        "Suspense": "Suspense / Hook",
        "Storytime": "Lofi / Chill"
    }
    def_music = music_map.get(theme, "Lofi / Chill")
    
    # Process transcript into selectable sentences
    words_in_clip = [w for w in _state["word_timestamps"] if w['start'] >= st - 1 and w['end'] <= et + 1]
    
    sentences_ui = []
    current_s = []
    for w in words_in_clip:
        current_s.append(w)
        txt = w["word"].strip()
        if txt.endswith('.') or txt.endswith('!') or txt.endswith('?') or len(current_s) > 12:
            s_txt = " ".join([x["word"].strip() for x in current_s])
            sentences_ui.append(f"[{current_s[0]['start']:.1f}s] {s_txt}")
            current_s = []
    if current_s:
        s_txt = " ".join([x["word"].strip() for x in current_s])
        sentences_ui.append(f"[{current_s[0]['start']:.1f}s] {s_txt}")
        
    transcript_cb_update = gr.update(choices=sentences_ui, value=sentences_ui)
    
    html = f"""
    <div class="detail-panel">
        <h2 style="margin:0 0 10px 0;font-size:18px;">{c.get('title','')}</h2>
        
        <div class="detail-section">
            <div class="detail-label">THE HOOK</div>
            <div class="detail-text" style="color:#fff;">\u201c{c.get('hook_sentence','')}\u201d</div>
        </div>
        
        <div class="detail-section">
            <div class="detail-label">WHY IT WORKS (AI ANALYSIS)</div>
            <div class="detail-text">{c.get('virality_reason','')}</div>
        </div>
        
        <div class="detail-section">
            <div class="detail-label">B-ROLL / EMOJIS</div>
            <div class="detail-text">Auto-fetching enabled for this theme.</div>
        </div>
    </div>
    """
    
    return html, st, et, "Hormozi", "Center", def_music, transcript_cb_update

def on_clip_select(n):
    html, st, et, c_style, c_pos, bgm, transcript_update = _get_internal_clip_data(n)
    return html, gr.update(value=st), gr.update(value=et), gr.update(value=c_style), gr.update(value=c_pos), gr.update(value=bgm), transcript_update

def analyze_video(url, num_clips):
    if not url or not url.strip():
        return "", "Enter a YouTube URL.", "", gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(visible=False), gr.update()
    try:
        llm_entry = LLM_CATALOG[0]
        wsp_size  = WHISPER_CATALOG[3]["size"]
        llm_path  = os.path.join(LLM_DIR, llm_entry["filename"])
        n = int(num_clips)

        cached_h = cache.load_highlights(url.strip())
        cached_t = cache.load_transcript(url.strip())
        if cached_h and cached_t:
            _state["clips"] = cached_h
            _state["word_timestamps"] = cached_t[1]
            _state["current_url"] = url.strip()
            html, st, et, cs, cp, bgm, t_upd = _get_internal_clip_data(1)
            return _cards(_state["clips"]), f"Loaded from cache.", html, gr.update(value=st), gr.update(value=et), gr.update(value=cs), gr.update(value=cp), gr.update(value=bgm), gr.update(visible=True), t_upd

        if not os.path.exists(llm_path):
            hf_hub_download(repo_id=llm_entry["repo"], filename=llm_entry["filename"], local_dir=LLM_DIR, local_dir_use_symlinks=False)

        source_mp4 = os.path.join(WORK_DIR, "source.mp4")
        _state["current_url"] = url.strip()
        download_video(url.strip(), WORK_DIR, cookie_path=COOKIE_PATH)

        full_text, words = transcribe_audio(source_mp4, model_size=wsp_size, whisper_dir=WHISPER_DIR)
        _state["word_timestamps"] = words
        cache.save_transcript(url.strip(), full_text, words)

        result = get_highlights(full_text, num_clips=n, llm_path=llm_path, gpu_layers=llm_entry["gpu_layers"], max_clips=20)
        _state["clips"] = result.get("highlights", [])
        cache.save_highlights(url.strip(), _state["clips"])
        cache.save_metadata(url.strip())

        if not _state["clips"]:
            return "", "No clips found.", "", gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(visible=False), gr.update()

        html, st, et, cs, cp, bgm, t_upd = _get_internal_clip_data(1)
        return _cards(_state["clips"]), "Done.", html, gr.update(value=st), gr.update(value=et), gr.update(value=cs), gr.update(value=cp), gr.update(value=bgm), gr.update(visible=True), t_upd
    except Exception as e:
        traceback.print_exc()
        return "", f"Error: {e}", "", gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(visible=False), gr.update()


def render_clip(clip_num, face_center, override_st, override_et, cap_style_str, cap_pos_str, bg_music_genre, transcript_selections, all_transcript_options):
    if not _state["clips"]:
        return None, "Analyse a video first."
    idx = int(clip_num) - 1
    if idx < 0 or idx >= len(_state["clips"]):
        return None, "Invalid clip number."
    try:
        clip = _state["clips"][idx]
        input_mp4 = os.path.join(WORK_DIR, "source.mp4")
        clips_dir = cache.get_clips_dir(_state["current_url"]) if _state["current_url"] else OUTPUT_DIR
        
        theme = clip.get("theme", "Storytime")
        
        # Calculate excluded sentences
        excluded = [s for s in all_transcript_options if s not in transcript_selections]
        
        out = render_short(
            input_video=input_mp4, clip_data=clip,
            word_timestamps=_state["word_timestamps"] if cap_style_str != "None" else [],
            output_dir=clips_dir, work_dir=WORK_DIR,
            face_center=face_center, add_subs=(cap_style_str != "None"),
            theme=theme, caption_style=cap_style_str, caption_pos=cap_pos_str,
            override_start=override_st, override_end=override_et,
            excluded_sentences=excluded
        )
        
        if bg_music_genre and bg_music_genre != "None":
            music_url = BGM_TRACKS[bg_music_genre]
            music_path = os.path.join(WORK_DIR, f"{bg_music_genre.replace(' ', '_').replace('/', '')}.mp3")
            
            if not os.path.exists(music_path):
                req = urllib.request.Request(music_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req) as response, open(music_path, 'wb') as out_file:
                    shutil.copyfileobj(response, out_file)
                
            enhance_clip(out, clip, music_path=music_path)
        
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        dst = os.path.join(OUTPUT_DIR, os.path.basename(out))
        if out != dst:
            shutil.copy2(out, dst)
            
        return out, f"Rendered successfully: {os.path.basename(out)}"
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

_css = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
body, .gradio-container { background: #0a0a0a !important; font-family: 'Inter', system-ui, sans-serif !important; color: #ededed !important; }

.sidebar { background: #121212 !important; border-right: 1px solid #222 !important; padding: 20px !important; border-radius: 12px; }
.main-content { background: #0a0a0a !important; }

.card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; margin-top: 10px; }
.clip-card { background: #161616; border: 1px solid #2a2a2a; border-radius: 10px; padding: 16px; cursor: pointer; transition: all 0.2s ease; }
.clip-card:hover { border-color: #555; transform: translateY(-2px); background: #1c1c1c; }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.card-badge { background: #2a2a2a; color: #aaa; font-size: 10px; font-weight: 600; padding: 3px 8px; border-radius: 4px; text-transform: uppercase; }
.card-score { font-size: 20px; font-weight: 800; }
.score-max { font-size: 11px; color: #666; font-weight: 500; }
.card-title { font-size: 14px; font-weight: 600; color: #eee; margin-bottom: 6px; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.card-meta { font-size: 12px; color: #888; }

.viral-meter-bg { width: 100%; height: 4px; background: #222; border-radius: 2px; margin-top: 12px; overflow: hidden; }
.viral-meter-fill { height: 100%; border-radius: 2px; }

.detail-panel { background: #121212; border: 1px solid #222; border-radius: 10px; padding: 20px; }
.detail-section { margin-top: 16px; }
.detail-label { font-size: 10px; color: #888; font-weight: 700; margin-bottom: 4px; letter-spacing: 0.5px; }
.detail-text { font-size: 13px; color: #bbb; line-height: 1.5; }

input, textarea, select { background: #161616 !important; color: #eee !important; border: 1px solid #333 !important; border-radius: 6px !important; }
.gr-button-primary { background: linear-gradient(135deg, #FF4500, #FF8C00) !important; color: #fff !important; font-weight: 700 !important; border: none !important; }
.gr-button-primary:hover { opacity: 0.9 !important; }
footer { display: none !important; }
"""

with gr.Blocks(title="Clip Factory SaaS", css=_css) as demo:
    with gr.Row():
        with gr.Column(scale=2, elem_classes="sidebar"):
            gr.HTML("<h1 style='font-size:24px;font-weight:800;margin:0;background:linear-gradient(90deg,#fff,#aaa);-webkit-background-clip:text;-webkit-text-fill-color:transparent;'>ClipFactory.ai</h1><p style='color:#666;font-size:12px;margin-top:4px'>Premium Video Re-purposing</p>")
            
            url_input = gr.Textbox(placeholder="Paste YouTube URL...", label="Video Source", lines=1)
            num_clips = gr.Slider(1, 15, value=10, step=1, label="Target Clips Count")
            analyze_btn = gr.Button("Analyze Video", variant="primary")
            status_box = gr.Textbox(label="Status", interactive=False, lines=1)
            
            gr.HTML("<hr style='border-color:#222;margin:20px 0;'>")
            refresh_btn = gr.Button("Refresh Gallery", variant="secondary")

        with gr.Column(scale=8, elem_classes="main-content"):
            clips_html = gr.HTML("<div style='padding:40px;text-align:center;color:#444;border:1px dashed #222;border-radius:12px;'>Awaiting video URL...</div>")
            
            with gr.Group(visible=False) as editor_group:
                gr.HTML("<h2 style='margin:20px 0 10px 0;font-size:18px;'>Edit & Render</h2>")
                with gr.Row():
                    with gr.Column(scale=5):
                        detail_html = gr.HTML("")
                        with gr.Accordion("Transcript Editor (Uncheck to Cut)", open=False):
                            transcript_cb = gr.CheckboxGroup(choices=[], label="Sentences in this clip")
                            # Hidden component to store the full list of options
                            transcript_options_hidden = gr.State([])
                            
                    with gr.Column(scale=5):
                        clip_num = gr.Number(value=1, label="Selected Clip", precision=0, minimum=1, maximum=20, elem_id="clip-sel", visible=False)
                        
                        with gr.Accordion("Timeline Edit", open=True):
                            gr.HTML("<p style='font-size:11px;color:#888;margin:0 0 10px 0;'>Adjust Master Bounds. (Or use Transcript Editor on the left to cut out middle sections).</p>")
                            with gr.Row():
                                st_override = gr.Number(label="Start Time (s)", precision=1)
                                et_override = gr.Number(label="End Time (s)", precision=1)
                                
                        with gr.Accordion("Enhancements", open=True):
                            face_cb = gr.Checkbox(label="Auto Face Tracking & B-Roll / Emojis", value=True)
                            with gr.Row():
                                cap_style = gr.Dropdown(choices=CAPTION_STYLES, value="Hormozi", label="Caption Template")
                                cap_pos = gr.Dropdown(choices=CAPTION_POSITIONS, value="Center", label="Placement")
                            bg_music = gr.Dropdown(choices=list(BGM_TRACKS.keys()), value="Lofi / Chill", label="Smart BGM")
                            
                        render_btn = gr.Button("Render Final Clip", variant="primary", size="lg")
                        render_status = gr.Textbox(label="", interactive=False, lines=1)
            
            with gr.Row():
                video_preview = gr.Video(label="Preview Player", height=500, scale=4)
                gallery = gr.Gallery(label="Library", columns=3, height=500, object_fit="contain", scale=6)

    def store_all_options(x):
        return x
        
    analyze_btn.click(analyze_video, [url_input, num_clips],
                      [clips_html, status_box, detail_html, st_override, et_override, cap_style, cap_pos, bg_music, editor_group, transcript_cb]).then(
                      store_all_options, inputs=[transcript_cb], outputs=[transcript_options_hidden])
                      
    clip_num.change(on_clip_select, [clip_num], [detail_html, st_override, et_override, cap_style, cap_pos, bg_music, transcript_cb]).then(
                      store_all_options, inputs=[transcript_cb], outputs=[transcript_options_hidden])
    
    render_btn.click(render_clip, [clip_num, face_cb, st_override, et_override, cap_style, cap_pos, bg_music, transcript_cb, transcript_options_hidden], [video_preview, render_status])
    
    refresh_btn.click(get_gallery, outputs=[gallery])

if __name__ == "__main__":
    demo.launch(share=True, debug=True, allowed_paths=[OUTPUT_DIR, WORK_DIR, PROJECTS_DIR, BASE_DIR])
else:
    demo.launch(share=True, debug=True, allowed_paths=[OUTPUT_DIR, WORK_DIR, PROJECTS_DIR, BASE_DIR])
