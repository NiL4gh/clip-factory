import os
import sys
import uuid
import time
import asyncio
import datetime as _dt
import urllib.request as _urlreq
from typing import List, Optional
from fastapi import FastAPI, BackgroundTasks, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Ensure repo root is in sys.path
try:
    REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
from shorts_generator.highlights import get_highlights, get_topic_index, detect_video_persona, estimate_clip_potential
from shorts_generator.clipper import render_short
from shorts_generator.enhancer import enhance_clip
from shorts_generator import cache
from shorts_generator.logger import ui_logger
from huggingface_hub import hf_hub_download

app = FastAPI(title="ClipFactory AI Director API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve rendered clips as static media
os.makedirs(OUTPUT_DIR, exist_ok=True)
app.mount("/media", StaticFiles(directory=OUTPUT_DIR), name="media")

# ── Bundled CC0 Background Music (direct download, no API key) ───────────
BGM_CATALOG = {
    "Lofi / Chill":        {"url": "https://cdn.pixabay.com/audio/2022/05/27/audio_1808fbf07a.mp3", "file": "bgm_lofi.mp3"},
    "High Energy / Phonk": {"url": "https://cdn.pixabay.com/audio/2022/10/09/audio_c714eab8c3.mp3", "file": "bgm_energy.mp3"},
    "Suspense / Dark":     {"url": "https://cdn.pixabay.com/audio/2022/03/15/audio_8cb749d484.mp3", "file": "bgm_suspense.mp3"},
    "Corporate / Upbeat":  {"url": "https://cdn.pixabay.com/audio/2023/07/30/audio_e08fa075b6.mp3", "file": "bgm_corporate.mp3"},
}
BGM_DIR = os.path.join(WORK_DIR, "bgm")

def _get_bgm(genre: str) -> str:
    """Download and cache a CC0 BGM track. Returns file path or empty string."""
    entry = BGM_CATALOG.get(genre)
    if not entry:
        return ""
    os.makedirs(BGM_DIR, exist_ok=True)
    path = os.path.join(BGM_DIR, entry["file"])
    if not os.path.exists(path):
        try:
            ui_logger.log(f"Downloading BGM: {genre}...")
            _urlreq.urlretrieve(entry["url"], path)
            ui_logger.log(f"BGM cached: {entry['file']}")
        except Exception as e:
            ui_logger.log(f"BGM download failed ({e}) — rendering without music.")
            return ""
    return path

# In-memory state for the active project
_state = {
    "clips": [], 
    "word_timestamps": [], 
    "current_url": None, 
    "persona": {},
    "topics": [],
    "estimated_clips": 0,
    "video_duration": 0,
    "is_strategizing": False,
    "is_rendering": False,
    "is_cancelled": False
}

class StrategizeRequest(BaseModel):
    url: str
    llm_label: Optional[str] = "🦙 LLaMA 3 8B Instruct Q4"
    whisper_label: Optional[str] = "Medium (Fast/Accurate)"
    target_platform: Optional[str] = "TikTok / Shorts (Vertical)"

# Render tracking
_render_status = {} # { task_id: { status: "running"|"done"|"error", filename: str } }

class RenderRequest(BaseModel):
    clip_id: int # index in _state["clips"]
    face_center: bool = True
    magic_hook: bool = True
    remove_silence: bool = True
    caption_style: str = "Hormozi"
    caption_pos: str = "Center"
    bg_music_genre: str = "None"
    broll_intensity: str = "Medium"
    excluded_sentences: List[str] = []

@app.get("/api/config")
async def get_config():
    return {
        "llm_catalog": [{"label": e["label"]} for e in LLM_CATALOG],
        "whisper_catalog": [{"label": e["label"]} for e in WHISPER_CATALOG],
        "bgm_genres": list(BGM_CATALOG.keys()),
    }

@app.get("/api/status")
async def get_status():
    return {
        "is_strategizing": _state["is_strategizing"],
        "is_rendering": _state["is_rendering"]
    }

@app.websocket("/api/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            new_entries = ui_logger.get_new_entries()
            for entry in new_entries:
                import json as _json
                await websocket.send_text(_json.dumps(entry))
            await asyncio.sleep(0.4)
    except Exception:
        pass

def _run_strategize(url: str, llm_label: str, whisper_label: str, target_platform: str = "TikTok / Shorts (Vertical)"):
    try:
        _state["is_strategizing"] = True
        _state["is_cancelled"] = False
        ui_logger.clear()
        ui_logger.log("PROGRESS|0|Initializing AI strategy phase...")

        # Find LLM in catalog
        llm_entry = LLM_CATALOG[0]
        for entry in LLM_CATALOG:
            if entry["label"] == llm_label:
                llm_entry = entry
                break
                
        # Find Fast Pass LLM (Gemma 2B)
        fast_llm_entry = None
        for entry in LLM_CATALOG:
            if "Gemma 2" in entry["label"]:
                fast_llm_entry = entry
                break
        if not fast_llm_entry: fast_llm_entry = llm_entry
                
        # Find Whisper
        wsp_size = "medium"
        for entry in WHISPER_CATALOG:
            if entry["label"] == whisper_label:
                wsp_size = entry["size"]
                break

        llm_path = os.path.join(LLM_DIR, llm_entry["filename"])
        fast_llm_path = os.path.join(LLM_DIR, fast_llm_entry["filename"])

        if not os.path.exists(llm_path):
            ui_logger.log("PROGRESS|5|Downloading main LLM...")
            hf_hub_download(repo_id=llm_entry["repo"], filename=llm_entry["filename"], local_dir=LLM_DIR, local_dir_use_symlinks=False)
            
        if not os.path.exists(fast_llm_path):
            ui_logger.log("PROGRESS|10|Downloading fast-pass LLM...")
            hf_hub_download(repo_id=fast_llm_entry["repo"], filename=fast_llm_entry["filename"], local_dir=LLM_DIR, local_dir_use_symlinks=False)

        source_mp4 = os.path.join(WORK_DIR, "source.mp4")
        _state["current_url"] = url.strip()

        if _state["is_cancelled"]: return

        if not os.path.exists(source_mp4) or cache.load_transcript(url.strip()) is None:
            ui_logger.log("PROGRESS|15|Downloading video...")
            download_video(url.strip(), WORK_DIR, cookie_path=COOKIE_PATH)
            if _state["is_cancelled"]: return
            ui_logger.log("PROGRESS|25|Transcribing audio (this may take a few minutes)...")
            full_text, words = transcribe_audio(source_mp4, model_size=wsp_size, whisper_dir=WHISPER_DIR)
            _state["word_timestamps"] = words
            cache.save_transcript(url.strip(), full_text, words)
        else:
            ui_logger.log("PROGRESS|25|Transcript loaded from cache.")
            cached_t = cache.load_transcript(url.strip())
            _state["word_timestamps"] = cached_t[1]

        if _state["is_cancelled"]: return

        # Phase 0: Persona Detection (Fast Pass)
        ui_logger.log(f"PROGRESS|40|Phase 0/3: Analyzing Video Persona with {fast_llm_entry['label']}...")
        persona = detect_video_persona(_state["word_timestamps"], llm_path=fast_llm_path, gpu_layers=fast_llm_entry["gpu_layers"])
        ui_logger.log(f"PROGRESS|45|Detected Genre: {persona.get('genre', 'Unknown')} | Tone: {persona.get('tone', 'Unknown')}")
        _state["persona"] = persona

        # Calculate estimated clip potential
        estimated = estimate_clip_potential(_state["word_timestamps"])
        _state["estimated_clips"] = estimated
        
        # Calculate video duration
        if _state["word_timestamps"]:
            wts = _state["word_timestamps"]
            _state["video_duration"] = wts[-1].get("end", 0) - wts[0].get("start", 0)
        
        ui_logger.log(f"PROGRESS|48|Video duration: {_state['video_duration']/60:.0f} min | Estimated clip potential: ~{estimated} clips")

        if _state["is_cancelled"]: return

        # Phase 1: Topic Indexing
        ui_logger.log(f"PROGRESS|55|Phase 1/3: Mapping video topics...")
        topics = get_topic_index(_state["word_timestamps"], llm_path=fast_llm_path, gpu_layers=fast_llm_entry["gpu_layers"])
        _state["topics"] = topics
        ui_logger.log(f"PROGRESS|65|Found {len(topics)} distinct topics in the video.")

        if _state["is_cancelled"]: return

        # Phase 2: Per-Topic Clip Extraction
        ui_logger.log(f"PROGRESS|70|Phase 2/3: Extracting clips per topic with {llm_entry['label']}...")
        result = get_highlights(
            _state["word_timestamps"],
            num_clips=estimated,
            llm_path=llm_path,
            gpu_layers=llm_entry["gpu_layers"],
            max_clips=30,
            angle="standard",
            topics=topics,
        )

        clips = result.get("highlights", [])
        if not clips:
            raise ValueError("No viral moments found in this video.")

        # Process durations and badges
        for i, c in enumerate(clips):
            dur = float(c.get("duration", 0))
            if dur == 0:
                dur = float(c.get("end_time", 0)) - float(c.get("start_time", 0))
            c["duration"] = dur
            c["badge"] = "🎬 Single"

        _state["clips"] = clips
        cache.save_highlights(url.strip(), _state["clips"])
        cache.save_metadata(url.strip())
        ui_logger.log(f"PROGRESS|100|Strategy Complete. Found {len(clips)} clips (estimated potential: ~{_state['estimated_clips']}).")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        if not _state.get("is_cancelled"):
            ui_logger.log(f"ERROR: {str(e)}")
    finally:
        _state["is_strategizing"] = False
        if _state.get("is_cancelled"):
            ui_logger.log("PROGRESS|0|Analysis was stopped by the user.")
            _state["is_cancelled"] = False

@app.post("/api/strategize")
async def strategize(req: StrategizeRequest, background_tasks: BackgroundTasks):
    if _state["is_strategizing"] or _state["is_rendering"]:
        raise HTTPException(status_code=400, detail="A task is already running.")
    background_tasks.add_task(_run_strategize, req.url, req.llm_label, req.whisper_label, req.target_platform)
    return {"message": "Strategizing started."}

@app.post("/api/cancel_strategize")
async def cancel_strategize():
    if _state["is_strategizing"]:
        _state["is_cancelled"] = True
        return {"message": "Cancellation requested."}
    return {"message": "No task running."}

@app.post("/api/reset")
async def reset_state():
    _state["clips"] = []
    _state["word_timestamps"] = []
    _state["current_url"] = None
    _state["persona"] = {}
    _state["topics"] = []
    _state["estimated_clips"] = 0
    _state["video_duration"] = 0
    _state["is_strategizing"] = False
    _state["is_rendering"] = False
    _state["is_cancelled"] = False
    ui_logger.clear()
    return {"message": "State reset."}

@app.get("/api/results")
async def get_results():
    if _state["is_strategizing"]:
        return {"status": "running"}
    return {
        "status": "done",
        "persona": _state["persona"],
        "clips": _state["clips"],
        "topics": _state["topics"],
        "estimated_clips": _state["estimated_clips"],
        "video_duration": _state["video_duration"],
        "word_timestamps": _state["word_timestamps"]
    }

@app.get("/api/render_status")
async def get_render_status(task_id: str):
    if task_id in _render_status:
        return _render_status[task_id]
    return {"status": "not_found"}

def _run_render(req: RenderRequest, task_id: str):
    try:
        _state["is_rendering"] = True
        ui_logger.clear()
        ui_logger.log(f"Initializing render for clip index {req.clip_id}...")
        
        clip = _state["clips"][req.clip_id]
        input_mp4 = os.path.join(WORK_DIR, "source.mp4")
        clips_dir = cache.get_clips_dir(_state["current_url"]) if _state["current_url"] else OUTPUT_DIR
        theme = clip.get("theme", "Storytime")
        
        all_sentences = [] # We would need to rebuild this from word_timestamps if needed, but for now we pass empty or rebuild.
        
        out = render_short(
            input_video=input_mp4, clip_data=clip,
            word_timestamps=_state["word_timestamps"],
            output_dir=clips_dir, work_dir=WORK_DIR,
            face_center=req.face_center, add_subs=(req.caption_style != "None"),
            theme=theme, caption_style=req.caption_style, caption_pos=req.caption_pos,
            override_start=None, override_end=None,
            excluded_sentences=req.excluded_sentences,
            magic_hook=req.magic_hook,
            remove_silence=req.remove_silence,
            broll_intensity=req.broll_intensity,
            all_sentences=all_sentences
        )
        
        # ── BGM mixing via enhance_clip ──
        if req.bg_music_genre and req.bg_music_genre != "None":
            music_path = _get_bgm(req.bg_music_genre)
            if music_path:
                ui_logger.log(f"Mixing BGM ({req.bg_music_genre}) with dynamic peak swell...")
                try:
                    enhance_clip(out, clip, music_path=music_path)
                except Exception as bgm_err:
                    ui_logger.log(f"BGM mixing failed ({bgm_err}) — clip saved without music.")

        import shutil
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        dst = os.path.join(OUTPUT_DIR, os.path.basename(out))
        if out != dst: shutil.copy2(out, dst)
        ui_logger.log(f"Rendered successfully: {os.path.basename(out)}")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        ui_logger.log(f"ERROR: {str(e)}")
        _render_status[task_id] = {"status": "error", "error": str(e)}
    finally:
        _state["is_rendering"] = False
        if _render_status.get(task_id, {}).get("status") != "error":
            _render_status[task_id]["status"] = "done"

@app.post("/api/render")
async def render(req: RenderRequest, background_tasks: BackgroundTasks):
    if _state["is_rendering"] or _state["is_strategizing"]:
        raise HTTPException(status_code=400, detail="A task is already running.")
    if req.clip_id < 0 or req.clip_id >= len(_state["clips"]):
        raise HTTPException(status_code=404, detail="Clip not found.")
    
    task_id = f"render_{req.clip_id}_{int(time.time())}"
    _render_status[task_id] = {"status": "running"}
    
    background_tasks.add_task(_run_render, req, task_id)
    return {"message": "Render started.", "task_id": task_id}

@app.get("/api/gallery")
async def get_gallery():
    import glob
    files = glob.glob(os.path.join(OUTPUT_DIR, "*.mp4"))
    files.sort(key=os.path.getmtime, reverse=True)
    result = []
    for f in files:
        try:
            stat = os.stat(f)
            result.append({
                "filename": os.path.basename(f),
                "url": f"/media/{os.path.basename(f)}",
                "size_mb": round(stat.st_size / (1024 * 1024), 1),
                "created_at": _dt.datetime.fromtimestamp(stat.st_mtime).strftime("%b %d, %H:%M"),
            })
        except OSError:
            continue
    return result

# ── Serve Next.js static build (Catch-all for SPA) ──────────
FRONTEND_DIR = os.path.join(REPO_DIR, "frontend", "out")

@app.get("/")
async def serve_index():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"detail": "Frontend not built. Run Cell 1 in Colab."}

@app.get("/{path:path}")
async def catch_all(path: str):
    # Skip API and Media routes
    if path.startswith("api") or path.startswith("media") or path.startswith("ws"):
        raise HTTPException(status_code=404)
        
    # Check if file exists in out dir (e.g. _next/static/...)
    file_path = os.path.join(FRONTEND_DIR, path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
        
    # Fallback to index.html for client-side routing
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
        
    return FileResponse(index_path) if os.path.exists(index_path) else {"detail": "Not Found"}
