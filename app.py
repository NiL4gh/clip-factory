import os
import sys
import glob
import shutil
import traceback
import urllib.request
import time
import threading

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
from shorts_generator.highlights import get_highlights, get_stitched_clips
from shorts_generator.clipper import render_short
from shorts_generator.enhancer import enhance_clip
from shorts_generator import cache
from shorts_generator.logger import ui_logger

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

CAPTION_STYLES = ["Hormozi", "Ali Abdaal", "MrBeast", "Standard", "Minimalist", "None"]
CAPTION_POSITIONS = ["Top", "Center", "Bottom"]
STRATEGY_ANGLES = {
    "whop_rewards": "Whop Content Rewards (Viral focus)",
    "standard": "Standard Virality",
    "educational": "Educational / Insightful",
    "controversial": "Controversial / Debate",
    "motivational": "Motivational / Growth",
    "storytelling": "Storytelling / Narrative",
}
BROLL_INTENSITIES = ["Low", "Medium", "High", "None"]

def _sc(s):
    s = int(s)
    if s >= 80: return "#4ade80" 
    if s >= 60: return "#facc15" 
    return "#f87171" 

HOOK_TYPE_ICONS = {
    "curiosity_gap": "🎯",
    "bold_claim": "💥",
    "controversy": "🔥",
    "revelation": "💡",
    "story_arc": "📖",
    "quotable": "💬",
}

def _cards(clips):
    rows = ""
    total = len(clips)
    for i, c in enumerate(clips):
        sc = int(c.get("score", 0))
        st = float(c.get("start_time", 0))
        et = float(c.get("end_time", 0))
        dur = c.get("duration", et - st)
        title = c.get("title", "")[:60]
        theme = c.get("theme", "Storytime")
        hook_icon = HOOK_TYPE_ICONS.get(c.get("hook_type", ""), "")
        is_stitched = c.get("is_stitched", False)
        stitch_badge = '<span class="stitch-badge">🔗 Multi-Part</span>' if is_stitched else ""

        rows += f"""
        <div class="clip-card" onclick="document.getElementById('clip-sel').querySelector('input').value={i+1}; document.getElementById('clip-sel').querySelector('input').dispatchEvent(new Event('input',{{bubbles:true}}));">
            <div class="card-header">
                <span class="card-badge">#{i+1} &bull; {theme} {hook_icon}</span>
                <span class="card-score" style="color:{_sc(sc)}">{sc}<span class="score-max">/100</span></span>
            </div>
            <div class="card-title">{title}</div>
            <div class="card-meta">{st:.0f}s - {et:.0f}s &nbsp;({dur:.0f}s) &nbsp;{stitch_badge}</div>
            <div class="viral-meter-bg">
                <div class="viral-meter-fill" style="width:{sc}%; background:{_sc(sc)}"></div>
            </div>
        </div>
        """
    header = f"<div class='clip-count-header'>🎬 {total} clips found</div>" if total else ""
    return f"""{header}<div class="card-grid">{rows}</div>"""

def _get_internal_clip_data(idx):
    if not _state["clips"]: 
        return "", 0, 0, "Hormozi", "Center", "None", gr.update(choices=[], value=[])
        
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
    
    words_in_clip = [w for w in _state["word_timestamps"] if w['start'] >= st - 1 and w['end'] <= et + 1]
    
    # Build a lookup from word object to its global index in _state["word_timestamps"]
    word_to_global_idx = {}
    for gi, gw in enumerate(_state["word_timestamps"]):
        word_to_global_idx[id(gw)] = gi
    
    sentences_ui = []
    current_s = []
    for w in words_in_clip:
        current_s.append(w)
        txt = w["word"].strip()
        if txt.endswith('.') or txt.endswith('!') or txt.endswith('?') or len(current_s) > 12:
            s_txt = " ".join([x["word"].strip() for x in current_s])
            first_gidx = word_to_global_idx.get(id(current_s[0]), 0)
            last_gidx = word_to_global_idx.get(id(current_s[-1]), first_gidx)
            sentences_ui.append(f"[WID:{first_gidx}-{last_gidx}] [{current_s[0]['start']:.1f}s] {s_txt}")
            current_s = []
    if current_s:
        s_txt = " ".join([x["word"].strip() for x in current_s])
        first_gidx = word_to_global_idx.get(id(current_s[0]), 0)
        last_gidx = word_to_global_idx.get(id(current_s[-1]), first_gidx)
        sentences_ui.append(f"[WID:{first_gidx}-{last_gidx}] [{current_s[0]['start']:.1f}s] {s_txt}")
        
    transcript_cb_update = gr.update(choices=sentences_ui, value=sentences_ui)
    
    hook_score = min(100, int(c.get("score", 50)) + 10)
    flow_score = min(100, int(c.get("score", 50)) + 5)
    trend_score = min(100, max(0, int(c.get("score", 50)) - 5))

    html = f"""
    <div class="detail-panel">
        <h2 style="margin:0 0 16px 0;font-size:20px;font-weight:700;color:#f8fafc;">{c.get('title','')}</h2>
        
        <div style="display:flex; gap:12px; margin-bottom: 24px;">
            <div class="metric-box">
                <div class="metric-label">HOOK RATING</div>
                <div class="metric-value" style="color:#4ade80;">{hook_score}</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">FLOW</div>
                <div class="metric-value" style="color:#facc15;">{flow_score}</div>
            </div>
            <div class="metric-box">
                <div class="metric-label">TREND</div>
                <div class="metric-value" style="color:#f87171;">{trend_score}</div>
            </div>
        </div>
        
        <div class="detail-section">
            <div class="detail-label">THE HOOK</div>
            <div class="detail-text" style="color:#fff;font-size:16px;font-weight:500;font-style:italic;">\u201c{c.get('hook_sentence','')}\u201d</div>
        </div>
        
        <div class="detail-section">
            <div class="detail-label">WHY IT WORKS (AI ANALYSIS)</div>
            <div class="detail-text">{c.get('virality_reason','')}</div>
        </div>
        
        <div class="detail-section">
            <div class="detail-label">AI PRODUCTION PLAN</div>
            <div class="detail-text">Generating visual hooks, fetching dynamic B-Roll & Emojis tailored for the <span style="color:#6366f1;font-weight:600;">{theme}</span> theme.</div>
        </div>
    </div>
    """
    
    return html, st, et, "Hormozi", "Center", def_music, transcript_cb_update

def on_clip_select(n):
    html, st, et, c_style, c_pos, bgm, transcript_update = _get_internal_clip_data(n)
    return html, gr.update(value=st), gr.update(value=et), gr.update(value=c_style), gr.update(value=c_pos), gr.update(value=bgm), transcript_update

def strategize_video(url, angle):
    """Generator-based strategy function for real-time log streaming to Gradio UI."""
    ui_logger.clear()
    yield gr.update(visible=False), gr.update(), "Initializing AI strategy phase...", gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(visible=False), gr.update()

    result_container = {}

    def worker():
        try:
            res = _strategize_video_core(url, angle)
            result_container["status"] = "done"
            result_container["result"] = res
        except Exception as e:
            traceback.print_exc()
            result_container["status"] = "error"
            result_container["error"] = str(e)

    t = threading.Thread(target=worker)
    t.start()

    while t.is_alive():
        time.sleep(0.5)
        logs = ui_logger.get_full_log() or "Conceptualizing video..."
        yield gr.update(), gr.update(), logs, gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(visible=False), gr.update()

    t.join()

    if result_container.get("status") == "error":
        logs = ui_logger.get_full_log()
        yield gr.update(), gr.update(), f"Error: {result_container.get('error')}\n\nLogs:\n{logs}", gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(visible=False), gr.update()
    else:
        yield result_container["result"]


def _strategize_video_core(url, angle):
    """Heavy-lifting core that runs in a background thread."""
    if not url or not url.strip():
        raise ValueError("Enter a YouTube URL.")

    llm_entry = LLM_CATALOG[0]  # Mistral 7B (first entry in list)
    wsp_size  = WHISPER_CATALOG[3]["size"]  # "medium"
    llm_path  = os.path.join(LLM_DIR, llm_entry["filename"])

    if not os.path.exists(llm_path):
        ui_logger.log(f"Downloading LLM to {LLM_DIR}...")
        hf_hub_download(repo_id=llm_entry["repo"], filename=llm_entry["filename"], local_dir=LLM_DIR, local_dir_use_symlinks=False)

    source_mp4 = os.path.join(WORK_DIR, "source.mp4")
    _state["current_url"] = url.strip()

    # Transcription / Download Phase
    if not os.path.exists(source_mp4) or cache.load_transcript(url.strip()) is None:
        download_video(url.strip(), WORK_DIR, cookie_path=COOKIE_PATH)
        full_text, words = transcribe_audio(source_mp4, model_size=wsp_size, whisper_dir=WHISPER_DIR)
        _state["word_timestamps"] = words
        cache.save_transcript(url.strip(), full_text, words)
    else:
        ui_logger.log("Transcript loaded from cache.")
        cached_t = cache.load_transcript(url.strip())
        _state["word_timestamps"] = cached_t[1]

    # Pass 1: Strategic extraction
    ui_logger.log(f"Phase 1/2: Extracting strategic clips (Angle: {angle})...")
    standard_result = get_highlights(_state["word_timestamps"], num_clips=5, llm_path=llm_path, gpu_layers=llm_entry["gpu_layers"], max_clips=5, angle=angle)

    # Pass 2: Story stitching (Q&A / Arcs)
    ui_logger.log("Phase 2/2: Scanning for cross-timestamp story connections...")
    stitch_result = get_stitched_clips(_state["word_timestamps"], llm_path=llm_path, gpu_layers=llm_entry["gpu_layers"], max_stitched=3)

    clips = standard_result.get("highlights", []) + stitch_result.get("highlights", [])
    if not clips:
        raise ValueError("No viral moments found in this video.")

    _state["clips"] = clips
    cache.save_highlights(url.strip(), _state["clips"])
    cache.save_metadata(url.strip())

    choices = [f"{'🔗' if c.get('is_stitched') else '🎬'} {i+1}: {c['title']} (Score: {c['score']})" for i, c in enumerate(clips)]
    _state["strategies"] = choices

    return gr.update(visible=True), gr.update(choices=choices, value=None), f"Strategy Phase Complete. Identified {len(clips)} potential clips.\n\nLogs:\n{ui_logger.get_full_log()}", gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(visible=False), gr.update()


def load_strategy_clip(selected_strategy):
    # Map the selected string back to the clip index
    idx = 0
    for i, choice in enumerate(_state.get("strategies", [])):
        if choice == selected_strategy:
            idx = i
            break
            
    _state["current_clip_index"] = idx
    # Get internal clip data for this clip (1-indexed for _get_internal_clip_data)
    html, st, et, cs, cp, bgm, t_upd = _get_internal_clip_data(idx + 1)
    
    return html, gr.update(value=st), gr.update(value=et), gr.update(value=cs), gr.update(value=cp), gr.update(value=bgm), gr.update(visible=True), t_upd

def regenerate_clips(url, num_clips, angle):
    ui_logger.clear()
    yield "Regenerating clips...", "", gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(visible=False), gr.update()
    
    try:
        if not url or not _state.get("word_timestamps"):
            raise ValueError("Please analyze a video first.")
            
        llm_entry = LLM_CATALOG[0]
        llm_path = os.path.join(LLM_DIR, llm_entry["filename"])
        
        result = get_highlights(_state["word_timestamps"], num_clips=int(num_clips), llm_path=llm_path, gpu_layers=llm_entry["gpu_layers"], max_clips=20, angle=angle)
        
        _state["clips"] = result.get("highlights", [])
        cache.save_highlights(url.strip(), _state["clips"])
        
        if not _state["clips"]:
            raise ValueError("No clips found.")
            
        html, st, et, cs, cp, bgm, t_upd = _get_internal_clip_data(1)
        yield _cards(_state["clips"]), f"Done.\n\nLogs:\n{ui_logger.get_full_log()}", html, gr.update(value=st), gr.update(value=et), gr.update(value=cs), gr.update(value=cp), gr.update(value=bgm), gr.update(visible=True), t_upd
    except Exception as e:
        traceback.print_exc()
        yield "", f"Error: {str(e)}\n\nLogs:\n{ui_logger.get_full_log()}", "", gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update(visible=False), gr.update()

def render_clip(face_cb, magic_hook_cb, remove_silence_cb, override_st, override_et, cap_style_str, cap_pos_str, bg_music_genre, broll_int_str, transcript_selections, all_transcript_options):
    ui_logger.clear()
    yield None, "Initializing render..."
    
    result_container = {}
    
    def worker():
        try:
            res = _render_clip_core(face_cb, magic_hook_cb, remove_silence_cb, override_st, override_et, cap_style_str, cap_pos_str, bg_music_genre, broll_int_str, transcript_selections, all_transcript_options)
            result_container["status"] = "done"
            result_container["result"] = res
        except Exception as e:
            traceback.print_exc()
            result_container["status"] = "error"
            result_container["error"] = str(e)
            
    t = threading.Thread(target=worker)
    t.start()
    
    while t.is_alive():
        time.sleep(0.5)
        logs = ui_logger.get_full_log() or "Initializing render..."
        yield None, logs
        
    t.join()
    
    if result_container.get("status") == "error":
        logs = ui_logger.get_full_log()
        yield None, f"Error: {result_container.get('error')}\n\nLogs:\n{logs}"
    else:
        yield result_container["result"]

def _render_clip_core(face_cb, magic_hook_cb, remove_silence_cb, override_st, override_et, cap_style_str, cap_pos_str, bg_music_genre, broll_int_str, transcript_selections, all_transcript_options):
    if not _state["clips"]:
        raise ValueError("No clips available to render.")
        
    idx = _state.get("current_clip_index", 0)
    if idx >= len(_state["clips"]):
        idx = 0
        
    clip = _state["clips"][idx]
    input_mp4 = os.path.join(WORK_DIR, "source.mp4")
    clips_dir = cache.get_clips_dir(_state["current_url"]) if _state["current_url"] else OUTPUT_DIR
    
    theme = clip.get("theme", "Storytime")
    
    excluded = [s for s in all_transcript_options if s not in transcript_selections]
    
    out = render_short(
        input_video=input_mp4, clip_data=clip,
        word_timestamps=_state["word_timestamps"],
        output_dir=clips_dir, work_dir=WORK_DIR,
        face_center=face_cb, add_subs=(cap_style_str != "None"),
        theme=theme, caption_style=cap_style_str, caption_pos=cap_pos_str,
        override_start=override_st, override_end=override_et,
        excluded_sentences=excluded,
        magic_hook=magic_hook_cb,
        remove_silence=remove_silence_cb,
        broll_intensity=broll_int_str,
        all_sentences=all_transcript_options
    )
    
    if bg_music_genre and bg_music_genre != "None":
        ui_logger.log(f"Adding BGM: {bg_music_genre}...")
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
        
    ui_logger.log(f"Rendered successfully: {os.path.basename(out)}")
    return out, f"Rendered successfully: {os.path.basename(out)}\n\nLogs:\n{ui_logger.get_full_log()}"

def batch_render(face_cb, magic_hook_cb, remove_silence_cb, cap_style_str, cap_pos_str, bg_music_genre, broll_int_str):
    if not _state["clips"]:
        yield None, "No clips to render. Please strategize a video first."
        return
        
    total = len(_state["clips"])
    ui_logger.clear()
    ui_logger.log(f"Starting batch render for {total} clips...")
    yield None, ui_logger.get_full_log()

    result_container = {}

    def worker():
        try:
            rendered = []
            for i in range(total):
                _state["current_clip_index"] = i
                clip = _state["clips"][i]
                ui_logger.log(f"--- Rendering Clip {i+1}/{total}: {clip.get('title')} ---")
                out = _render_clip_core(face_cb, magic_hook_cb, remove_silence_cb, None, None, cap_style_str, cap_pos_str, bg_music_genre, broll_int_str, [], [])
                rendered.append(out)
            result_container["status"] = "done"
            result_container["rendered"] = rendered
        except Exception as e:
            traceback.print_exc()
            result_container["status"] = "error"
            result_container["error"] = str(e)

    t = threading.Thread(target=worker)
    t.start()

    while t.is_alive():
        time.sleep(1.0)
        yield None, ui_logger.get_full_log()

    t.join()

    if result_container.get("status") == "error":
        ui_logger.log(f"Batch render failed: {result_container.get('error')}")
        yield None, f"Error: {result_container.get('error')}\n\nLogs:\n{ui_logger.get_full_log()}"
    else:
        ui_logger.log("Batch render complete!")
        yield None, f"Batch render of {total} clips finished successfully.\n\nLogs:\n{ui_logger.get_full_log()}"

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

def _gallery_html(files):
    """Build a visual grid of rendered video cards."""
    if not files:
        return "<div class='gallery-empty'>No rendered clips yet. Strategize and render a video to see results here.</div>"
    cards = ""
    for i, fp in enumerate(files):
        name = os.path.basename(fp)
        try:
            size_mb = os.path.getsize(fp) / (1024 * 1024)
            mtime = time.strftime('%b %d, %H:%M', time.localtime(os.path.getmtime(fp)))
        except:
            size_mb = 0
            mtime = "Unknown"
        cards += f"""
        <div class="gallery-card" data-idx="{i}">
            <div class="gallery-icon">🎬</div>
            <div class="gallery-name">{name}</div>
            <div class="gallery-meta">{size_mb:.1f} MB &bull; {mtime}</div>
        </div>
        """
    return f"<div class='gallery-grid'>{cards}</div>"

_css = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
body, .gradio-container { 
    background: radial-gradient(circle at 50% 0%, #1a1a24 0%, #0a0a0a 100%) !important; 
    font-family: 'Inter', system-ui, sans-serif !important; 
    color: #e2e8f0 !important; 
}

/* Scrollbar */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #333; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #555; }

.sidebar { 
    background: rgba(18, 18, 18, 0.6) !important; 
    backdrop-filter: blur(12px) !important; 
    border-right: 1px solid rgba(255,255,255,0.05) !important; 
    padding: 24px !important; 
    border-radius: 16px; 
    box-shadow: 4px 0 24px rgba(0,0,0,0.2);
}
.main-content { 
    background: transparent !important; 
    padding: 10px 20px !important;
}

/* Typography & Headings */
h1, h2, h3 { color: #f8fafc; font-weight: 700; letter-spacing: -0.02em; }
.brand-text {
    font-size: 28px;
    font-weight: 800;
    margin: 0;
    background: linear-gradient(135deg, #fff 0%, #a5b4fc 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: -0.5px;
}
.brand-sub { color: #818cf8; font-size: 13px; margin-top: 2px; font-weight: 500; letter-spacing: 0.5px; text-transform: uppercase; }

/* Panels & Cards */
.detail-panel { 
    background: rgba(22, 22, 22, 0.7); 
    border: 1px solid rgba(255,255,255,0.08); 
    border-radius: 16px; 
    padding: 24px; 
    backdrop-filter: blur(8px);
    box-shadow: 0 4px 20px rgba(0,0,0,0.15);
}
.glass-panel {
    background: rgba(22, 22, 22, 0.5); 
    border: 1px solid rgba(255,255,255,0.05); 
    border-radius: 12px; 
    padding: 20px;
}

/* Detail Section Typography */
.detail-section { margin-top: 20px; }
.detail-label { font-size: 11px; color: #64748b; font-weight: 700; margin-bottom: 6px; letter-spacing: 1px; text-transform: uppercase; }
.detail-text { font-size: 14px; color: #cbd5e1; line-height: 1.6; }

/* Form Controls */
input[type="text"], input[type="number"], textarea, select { 
    background: rgba(0,0,0,0.2) !important; 
    color: #f8fafc !important; 
    border: 1px solid rgba(255,255,255,0.1) !important; 
    border-radius: 8px !important; 
    padding: 10px 14px !important;
    transition: all 0.2s ease;
}
input[type="text"]:focus, input[type="number"]:focus, select:focus {
    border-color: #6366f1 !important;
    box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2) !important;
    outline: none !important;
}
input[type="checkbox"], input[type="radio"] { 
    accent-color: #6366f1 !important; 
    cursor: pointer; 
    width: 18px; 
    height: 18px; 
    border-radius: 4px; 
}

/* Transcript Editor */
.inline-transcript { 
    background: rgba(0,0,0,0.2) !important; 
    border: 1px solid rgba(255,255,255,0.05) !important; 
    border-radius: 12px; 
    padding: 16px; 
    max-height: 400px;
    overflow-y: auto;
}
.inline-transcript .wrap { display: flex; flex-wrap: wrap; gap: 10px; }
.inline-transcript label { 
    background: rgba(255,255,255,0.03); 
    padding: 8px 12px; 
    border-radius: 8px; 
    border: 1px solid rgba(255,255,255,0.08); 
    cursor: pointer; 
    transition: all 0.2s ease; 
    display: inline-flex; 
    align-items: center; 
}
.inline-transcript label:hover { 
    background: rgba(255,255,255,0.08); 
    border-color: rgba(255,255,255,0.2); 
}
.inline-transcript span { font-size: 14px !important; color: #cbd5e1 !important; line-height: 1.4 !important; }

/* Buttons */
.gr-button-primary { 
    background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%) !important; 
    color: #fff !important; 
    font-weight: 600 !important; 
    border: none !important; 
    border-radius: 8px !important;
    padding: 12px 24px !important;
    box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3) !important;
    transition: all 0.3s ease !important;
}
.gr-button-primary:hover { 
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 16px rgba(99, 102, 241, 0.4) !important;
}

/* Accordions */
.gradio-accordion {
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-radius: 12px !important;
    background: rgba(22,22,22,0.6) !important;
    margin-bottom: 12px !important;
}

/* Tabs */
.gr-tabs > .gr-tab-button {
    border-radius: 8px 8px 0 0 !important;
    padding: 10px 20px !important;
    font-weight: 600 !important;
}
.gr-tabs > .gr-tab-button.selected {
    background: rgba(22,22,22,0.8) !important;
    border-top: 2px solid #6366f1 !important;
    color: #f8fafc !important;
}

/* Metrics Cards */
.metric-box {
    background: rgba(0,0,0,0.3);
    padding: 12px 16px;
    border-radius: 10px;
    border: 1px solid rgba(255,255,255,0.05);
    flex: 1;
    text-align: center;
}
.metric-label { font-size: 11px; color: #94a3b8; font-weight: 700; margin-bottom: 4px; letter-spacing: 0.5px; }
.metric-value { font-size: 22px; font-weight: 800; }

.card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; margin-top: 10px; }
.clip-card { background: rgba(22, 22, 22, 0.8); border: 1px solid rgba(255,255,255,0.05); border-radius: 12px; padding: 18px; cursor: pointer; transition: all 0.2s ease; backdrop-filter: blur(8px); }
.clip-card:hover { border-color: #6366f1; transform: translateY(-3px); box-shadow: 0 8px 24px rgba(0,0,0,0.2); }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.card-badge { background: rgba(255,255,255,0.05); color: #cbd5e1; font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 6px; text-transform: uppercase; }
.card-score { font-size: 22px; font-weight: 800; }
.score-max { font-size: 12px; color: #64748b; font-weight: 600; }
.card-title { font-size: 15px; font-weight: 600; color: #f8fafc; margin-bottom: 8px; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.card-meta { font-size: 13px; color: #94a3b8; font-weight: 500; }

.viral-meter-bg { width: 100%; height: 6px; background: rgba(0,0,0,0.4); border-radius: 3px; margin-top: 14px; overflow: hidden; }
.viral-meter-fill { height: 100%; border-radius: 3px; transition: width 1s ease-in-out; }

footer { display: none !important; }
.hidden-clip-sel { display: none !important; }

/* Gallery Grid */
.gallery-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 14px; margin: 12px 0; }
.gallery-card { 
    background: rgba(22, 22, 22, 0.8); 
    border: 1px solid rgba(255,255,255,0.06); 
    border-radius: 12px; 
    padding: 16px; 
    text-align: center;
    cursor: pointer; 
    transition: all 0.25s ease;
}
.gallery-card:hover { 
    border-color: #6366f1; 
    transform: translateY(-2px); 
    box-shadow: 0 6px 20px rgba(99, 102, 241, 0.2);
}
.gallery-icon { font-size: 36px; margin-bottom: 8px; }
.gallery-name { font-size: 12px; color: #e2e8f0; font-weight: 600; word-break: break-all; margin-bottom: 4px; }
.gallery-meta { font-size: 11px; color: #64748b; }
.gallery-empty { 
    text-align: center; 
    padding: 40px 20px; 
    color: #64748b; 
    font-size: 14px; 
    border: 1px dashed rgba(255,255,255,0.1); 
    border-radius: 12px; 
    margin: 12px 0;
}
"""

with gr.Blocks(title="Clip Factory SaaS", css=_css) as demo:
    with gr.Row():
        with gr.Column(scale=2, elem_classes="sidebar"):
            gr.HTML("<h1 class='brand-text'>ClipFactory.ai</h1><div class='brand-sub'>Premium Video Re-purposing</div>")
            
            gr.HTML("<div style='margin-top:20px;margin-bottom:10px;font-size:12px;color:#94a3b8;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;'>New Project</div>")
            url_input = gr.Textbox(placeholder="Paste YouTube URL...", label="Video Source", lines=1)
            angle_input = gr.Dropdown(choices=list(STRATEGY_ANGLES.keys()), value="whop_rewards", label="AI Director Vibe")
            analyze_btn = gr.Button("Strategize Video", variant="primary")
            
            with gr.Group(visible=False) as strategy_group:
                gr.HTML("<div style='margin-top:24px;margin-bottom:10px;font-size:12px;color:#94a3b8;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;'>AI Director Strategies</div>")
                strategy_radio = gr.Radio(choices=[], label="Select Strategy")
            
            status_box = gr.Textbox(label="Status Console", interactive=False, lines=8)

        with gr.Column(scale=8, elem_classes="main-content"):
            with gr.Group(visible=False) as editor_group:
                gr.HTML("<h2 style='margin:10px 0 20px 0;font-size:24px;'>Workspace & Editor</h2>")
                with gr.Row():
                    with gr.Column(scale=5):
                        detail_html = gr.HTML("")
                        with gr.Accordion("Transcript Editor (Uncheck to Cut)", open=False):
                            transcript_cb = gr.CheckboxGroup(choices=[], label="Sentences in this clip", interactive=True, elem_classes="inline-transcript")
                            transcript_options_hidden = gr.State([])
                            
                    with gr.Column(scale=5):
                        with gr.Group(elem_classes="glass-panel"):
                            with gr.Accordion("Timeline Edit", open=False):
                                gr.HTML("<p style='font-size:11px;color:#888;margin:0 0 10px 0;'>Adjust Master Bounds. (Or use Transcript Editor on the left to cut out middle sections).</p>")
                                with gr.Row():
                                    st_override = gr.Number(label="Start Time (s)", precision=1, interactive=True)
                                    et_override = gr.Number(label="End Time (s)", precision=1, interactive=True)
                                    
                            with gr.Accordion("Enhancements & Branding", open=True):
                                face_cb = gr.Checkbox(label="Auto Face Tracking & Center Crop", value=True, interactive=True)
                                magic_hook_cb = gr.Checkbox(label="AI Magic Hook (Rewrite First 3s)", value=False, interactive=True)
                                remove_silence_cb = gr.Checkbox(label="Smart Silence/Filler Removal", value=True, interactive=True)
                                with gr.Row():
                                    cap_style = gr.Dropdown(choices=CAPTION_STYLES, value="Hormozi", label="Brand Kit", interactive=True)
                                    cap_pos = gr.Dropdown(choices=CAPTION_POSITIONS, value="Center", label="Placement", interactive=True)
                                with gr.Row():
                                    bg_music = gr.Dropdown(choices=list(BGM_TRACKS.keys()), value="Lofi / Chill", label="Smart BGM", interactive=True)
                                    broll_int = gr.Dropdown(choices=BROLL_INTENSITIES, value="Medium", label="B-Roll Intensity", interactive=True)

                            with gr.Row():
                                render_btn = gr.Button("Render Final Clip", variant="primary", size="lg")
                                batch_render_btn = gr.Button("Batch Render All Strategies", variant="secondary", size="lg")
                            render_status = gr.Textbox(label="Render Status", interactive=False, lines=4)
            
            with gr.Row():
                with gr.Tab("Studio Preview"):
                    video_preview = gr.Video(label="Preview Player", height=500, scale=4)
                with gr.Tab("Rendered Library"):
                    gallery_html = gr.HTML("<div class='gallery-empty'>No rendered clips yet. Strategize and render a video to see results here.</div>")
                    with gr.Row():
                        refresh_library_btn = gr.Button("🔄 Refresh Library", size="sm", scale=2)
                        delete_btn = gr.Button("🗑️ Delete Selected", variant="stop", size="sm", scale=1)
                    library_dropdown = gr.Dropdown(choices=[], label="Selected Clip", visible=True, scale=1)
                    with gr.Row():
                        library_video = gr.Video(label="Preview", height=400)
                        library_file = gr.File(label="Download")

    def store_all_options(x):
        return x
        
    def delete_video(selected_file):
        if not selected_file or not os.path.exists(selected_file):
            return gr.update(), gr.update(), None, None, "File not found."
        try:
            os.remove(selected_file)
            ui_logger.log(f"Deleted: {os.path.basename(selected_file)}")
            g_html, dd_update = populate_library()
            return g_html, dd_update, None, None, f"Deleted {os.path.basename(selected_file)}"
        except Exception as e:
            return gr.update(), gr.update(), None, None, f"Error deleting: {e}"

    def update_library_view(selected_file):
        if not selected_file: return None, None
        return selected_file, selected_file
        
    def populate_library():
        files = get_gallery()
        choices = [f for f in files]
        html = _gallery_html(files)
        return html, gr.update(choices=choices, value=choices[0] if choices else None)
        
    analyze_btn.click(strategize_video, [url_input, angle_input],
                      [strategy_group, strategy_radio, status_box, detail_html, st_override, et_override, cap_style, cap_pos, bg_music, editor_group, transcript_cb])
                      
    strategy_radio.change(load_strategy_clip, [strategy_radio],
                          [detail_html, st_override, et_override, cap_style, cap_pos, bg_music, editor_group, transcript_cb]).then(
                          store_all_options, inputs=[transcript_cb], outputs=[transcript_options_hidden])
    
    render_btn.click(render_clip, [face_cb, magic_hook_cb, remove_silence_cb, st_override, et_override, cap_style, cap_pos, bg_music, broll_int, transcript_cb, transcript_options_hidden], [video_preview, render_status])
    
    batch_render_btn.click(batch_render, [face_cb, magic_hook_cb, remove_silence_cb, cap_style, cap_pos, bg_music, broll_int], [video_preview, render_status])

    refresh_library_btn.click(populate_library, outputs=[gallery_html, library_dropdown])
    library_dropdown.change(update_library_view, inputs=[library_dropdown], outputs=[library_video, library_file])
    delete_btn.click(delete_video, [library_dropdown], [gallery_html, library_dropdown, library_video, library_file, render_status])

if __name__ == "__main__":
    demo.launch(share=True, debug=True, allowed_paths=[OUTPUT_DIR, WORK_DIR, PROJECTS_DIR, BASE_DIR])
else:
    demo.launch(share=True, debug=True, allowed_paths=[OUTPUT_DIR, WORK_DIR, PROJECTS_DIR, BASE_DIR])
