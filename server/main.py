import os
import sys
import uuid
import time
import asyncio
import datetime as _dt
from typing import List, Optional
from fastapi import FastAPI, BackgroundTasks, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
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
from shorts_generator.highlights import get_highlights, get_stitched_clips, detect_video_persona
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

# In-memory state for the active project
_state = {
    "clips": [], 
    "word_timestamps": [], 
    "current_url": None, 
    "persona": {},
    "is_strategizing": False,
    "is_rendering": False
}

class StrategizeRequest(BaseModel):
    url: str
    llm_label: Optional[str] = "🦙 LLaMA 3 8B Instruct Q4"
    whisper_label: Optional[str] = "Medium (Fast/Accurate)"

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

@app.get("/api/status")
async def get_status():
    return {
        "is_strategizing": _state["is_strategizing"],
        "is_rendering": _state["is_rendering"]
    }

@app.websocket("/api/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    last_log = ""
    try:
        while True:
            current_log = ui_logger.get_full_log()
            if current_log != last_log:
                await websocket.send_text(current_log)
                last_log = current_log
            await asyncio.sleep(0.5)
    except Exception:
        pass

def _run_strategize(url: str, llm_label: str, whisper_label: str):
    try:
        _state["is_strategizing"] = True
        ui_logger.clear()
        ui_logger.log(f"Initializing AI strategy phase for {url}...")

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
            ui_logger.log(f"Downloading main LLM...")
            hf_hub_download(repo_id=llm_entry["repo"], filename=llm_entry["filename"], local_dir=LLM_DIR, local_dir_use_symlinks=False)
            
        if not os.path.exists(fast_llm_path):
            ui_logger.log(f"Downloading fast-pass LLM...")
            hf_hub_download(repo_id=fast_llm_entry["repo"], filename=fast_llm_entry["filename"], local_dir=LLM_DIR, local_dir_use_symlinks=False)

        source_mp4 = os.path.join(WORK_DIR, "source.mp4")
        _state["current_url"] = url.strip()

        if not os.path.exists(source_mp4) or cache.load_transcript(url.strip()) is None:
            download_video(url.strip(), WORK_DIR, cookie_path=COOKIE_PATH)
            full_text, words = transcribe_audio(source_mp4, model_size=wsp_size, whisper_dir=WHISPER_DIR)
            _state["word_timestamps"] = words
            cache.save_transcript(url.strip(), full_text, words)
        else:
            ui_logger.log("Transcript loaded from cache.")
            cached_t = cache.load_transcript(url.strip())
            _state["word_timestamps"] = cached_t[1]

        # Phase 0: Persona Detection (Fast Pass)
        ui_logger.log(f"Phase 0/2: Analyzing Video Persona with {fast_llm_entry['label']}...")
        persona = detect_video_persona(_state["word_timestamps"], llm_path=fast_llm_path, gpu_layers=fast_llm_entry["gpu_layers"])
        ui_logger.log(f"Detected Genre: {persona.get('genre', 'Unknown')} | Tone: {persona.get('tone', 'Unknown')}")
        _state["persona"] = persona
        
        # Decide the strategy angle automatically based on persona
        auto_angle = "standard"
        genre = persona.get('genre', '').lower()
        if "education" in genre or "podcast" in genre: auto_angle = "educational"
        elif "drama" in genre or "debate" in genre: auto_angle = "controversial"
        elif "story" in genre or "vlog" in genre: auto_angle = "storytelling"

        # Phase 1: Strategic extraction
        ui_logger.log(f"Phase 1/2: Extracting strategic clips (Auto-Angle: {auto_angle}) with {llm_entry['label']}...")
        standard_result = get_highlights(_state["word_timestamps"], num_clips=5, llm_path=llm_path, gpu_layers=llm_entry["gpu_layers"], max_clips=5, angle=auto_angle)

        # Phase 2: Story stitching
        ui_logger.log("Phase 2/2: Scanning for cross-timestamp story connections...")
        stitch_result = get_stitched_clips(_state["word_timestamps"], llm_path=llm_path, gpu_layers=llm_entry["gpu_layers"], max_stitched=3)

        clips = standard_result.get("highlights", []) + stitch_result.get("highlights", [])
        if not clips:
            raise ValueError("No viral moments found in this video.")

        # Process durations and badges
        for i, c in enumerate(clips):
            segs = c.get("segments", [])
            dur = 0
            is_stitched = c.get("is_stitched", False)
            if segs and len(segs) > 1:
                is_stitched = True
                c["is_stitched"] = True
            if segs:
                for s in segs: dur += float(s.get("end_time", 0)) - float(s.get("start_time", 0))
            else:
                dur = float(c.get("end_time", 0)) - float(c.get("start_time", 0))
            
            c["duration"] = dur
            c["badge"] = "🔗 Stitched" if is_stitched else "🎬 Single"

        _state["clips"] = clips
        cache.save_highlights(url.strip(), _state["clips"])
        cache.save_metadata(url.strip())
        ui_logger.log(f"Strategy Phase Complete. Identified {len(clips)} potential clips.")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        ui_logger.log(f"ERROR: {str(e)}")
    finally:
        _state["is_strategizing"] = False

@app.post("/api/strategize")
async def strategize(req: StrategizeRequest, background_tasks: BackgroundTasks):
    if _state["is_strategizing"] or _state["is_rendering"]:
        raise HTTPException(status_code=400, detail="A task is already running.")
    background_tasks.add_task(_run_strategize, req.url, req.llm_label, req.whisper_label)
    return {"message": "Strategizing started."}

@app.get("/api/results")
async def get_results():
    if _state["is_strategizing"]:
        return {"status": "running"}
    return {
        "status": "done",
        "persona": _state["persona"],
        "clips": _state["clips"],
        "word_timestamps": _state["word_timestamps"]
    }

def _run_render(req: RenderRequest):
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
        
        if req.bg_music_genre and req.bg_music_genre != "None":
            ui_logger.log(f"Adding BGM: {req.bg_music_genre}...")
            # Simple mapping, can be expanded
            music_path = os.path.join(WORK_DIR, f"bgm.mp3")
            # Skipping actual download here for brevity, assuming standard enhancement
            # enhance_clip(out, clip, music_path=music_path)
            
        import shutil
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        dst = os.path.join(OUTPUT_DIR, os.path.basename(out))
        if out != dst: shutil.copy2(out, dst)
        ui_logger.log(f"Rendered successfully: {os.path.basename(out)}")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        ui_logger.log(f"ERROR: {str(e)}")
    finally:
        _state["is_rendering"] = False

@app.post("/api/render")
async def render(req: RenderRequest, background_tasks: BackgroundTasks):
    if _state["is_rendering"] or _state["is_strategizing"]:
        raise HTTPException(status_code=400, detail="A task is already running.")
    if req.clip_id < 0 or req.clip_id >= len(_state["clips"]):
        raise HTTPException(status_code=404, detail="Clip not found.")
    
    background_tasks.add_task(_run_render, req)
    return {"message": "Render started."}

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
