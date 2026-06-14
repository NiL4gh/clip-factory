import os
import sys
import uuid
import time
import asyncio
import datetime as _dt
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
import urllib.request as _urlreq
from typing import List, Optional
from fastapi import FastAPI, BackgroundTasks, WebSocket, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field

# Ensure repo root is in sys.path
try:
    REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
except NameError:
    REPO_DIR = os.getcwd()
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

from shorts_generator.config import (
    BASE_DIR, WORK_DIR, OUTPUT_DIR, LLM_DIR, WHISPER_DIR,
    COOKIE_PATH, LLM_CATALOG, WHISPER_CATALOG, PROJECTS_DIR, SESSIONS_DIR, AVAILABLE_FONTS,
)
from shorts_generator.downloader import download_video, download_srt, get_video_title
from shorts_generator.transcriber import transcribe_audio, parse_srt_to_word_timestamps
from shorts_generator.highlights import get_highlights, get_topic_index, detect_video_persona, estimate_clip_potential
from shorts_generator.clipper import render_short
from shorts_generator.enhancer import enhance_clip
from shorts_generator import cache
from shorts_generator.logger import ui_logger, get_logger, LOG_DIR, safe_print
from shorts_generator.audio_analyzer import analyze_audio_energy
from huggingface_hub import hf_hub_download

import subprocess

_GPU_ENCODER = "libx264"  # fallback default

_ENCODER_CANDIDATES = [
    ("h264_nvenc",  ["-c:v", "h264_nvenc", "-preset", "fast"]),
    ("h264_amf",    ["-c:v", "h264_amf",   "-quality", "speed"]),
    ("h264_qsv",    ["-c:v", "h264_qsv",   "-preset", "fast"]),
]

def _probe_encoder(codec_name: str) -> bool:
    """Return True if the given encoder is available on this system."""
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=black:s=64x64:r=1:d=0.1",
                "-c:v", codec_name, "-t", "0.1", "-f", "null", "-"
            ],
            capture_output=True,
            timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False

for encoder_name, encoder_args in _ENCODER_CANDIDATES:
    if _probe_encoder(encoder_name):
        _GPU_ENCODER = encoder_name
        ui_logger.log(f"⚡ GPU Encoder selected: {encoder_name}")
        break
else:
    ui_logger.log("💻 No GPU encoder found — using CPU libx264")

# Update the clipper._DETECTED_ENCODER global state
import shorts_generator.clipper as clipper
clipper._DETECTED_ENCODER = _GPU_ENCODER


app = FastAPI(title="ClipFactory AI Director API")

VERSION = "2.4.0-PRO-STRATEGY"
safe_print(f"🚀 ClipFactory AI Director Backend {VERSION} starting...")

class TimeoutMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        try:
            return await asyncio.wait_for(call_next(request), timeout=300.0)
        except asyncio.TimeoutError:
            return JSONResponse({'detail': 'Request timeout after 300s'}, status_code=504)

app.add_middleware(TimeoutMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    ui_logger.error(f"Unhandled error: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={'detail': str(exc), 'type': type(exc).__name__}
    )

# Serve rendered clips as static media
os.makedirs(OUTPUT_DIR, exist_ok=True)
app.mount("/media", StaticFiles(directory=OUTPUT_DIR), name="media")

THUMB_DIR = os.path.join(WORK_DIR, "thumbnails")
os.makedirs(THUMB_DIR, exist_ok=True)
app.mount("/thumbs", StaticFiles(directory=THUMB_DIR), name="thumbs")

# ── Bundled CC0 Background Music (direct download, no API key) ───────────
BGM_CATALOG = {
    "Lofi":      "lofi hip hop no copyright background music chill beats",
    "Upbeat":    "upbeat background music no copyright royalty free energetic",
    "Cinematic": "cinematic background music no copyright epic instrumental",
    "Chill":     "chill background music no copyright calm relaxing",
}
BGM_DIR = os.path.join(WORK_DIR, "bgm")

def _get_bgm(genre: str) -> str:
    """
    Download a royalty-free BGM track for the given genre using yt-dlp
    YouTube search. Caches the result at WORK_DIR/bgm_{genre}.mp3.
    Returns the file path on success, empty string on any failure.
    """
    import subprocess, re

    query = BGM_CATALOG.get(genre, "")
    if not query:
        return ""

    safe_genre = re.sub(r"[^a-zA-Z0-9_]", "_", genre.lower())
    out_path = str(WORK_DIR / f"bgm_{safe_genre}.mp3")

    # Return cached file if already downloaded this session
    if os.path.exists(out_path) and os.path.getsize(out_path) > 10_000:
        ui_logger.log(f"🎵 BGM cache hit: {safe_genre}")
        return out_path

    ui_logger.log(f"🎵 Fetching BGM for genre: {genre}")
    try:
        cmd = [
            "yt-dlp",
            f"ytsearch1:{query}",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "5",
            "--no-playlist",
            "--quiet",
            "--no-warnings",
            "-o", out_path.replace(".mp3", ".%(ext)s"),
        ]
        result = subprocess.run(
            cmd,
            timeout=90,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            ui_logger.log(f"⚠️ BGM download failed (yt-dlp exit {result.returncode})")
            return ""
        if os.path.exists(out_path) and os.path.getsize(out_path) > 10_000:
            ui_logger.log(f"✅ BGM downloaded: {safe_genre}")
            return out_path
        ui_logger.log("⚠️ BGM file missing after download")
        return ""
    except subprocess.TimeoutExpired:
        ui_logger.log("⚠️ BGM download timed out (90s)")
        return ""
    except Exception as e:
        ui_logger.log(f"⚠️ BGM fetch error: {e}")
        return ""

# In-memory state for the active project
# Highlight Dict Schema:
# - title: str
# - ideal_transcript: str
# - segments: list
# - start_time: float
# - end_time: float
# - score: int (composite)
# - virality_score: int
# - energy_score: int
# - hook_score: int (0-25)
# - engagement_score: int (0-25)
# - value_score: int (0-25)
# - shareability_score: int (0-25)
# - hook_sentence: str
# - hook_text: str
# - hook_type: str
# - virality_reason: str
# - theme: str
# - music_query: str
# - broll_keywords: list
# - emoji_moments: list
# - source_topic: str
_state = {
    "clips": [], 
    "word_timestamps": [], 
    "current_url": None, 
    "persona": {},
    "topics": [],
    "estimated_clips": 0,
    "video_duration": 0,
    "video_title": "",
    "is_strategizing": False,
    "is_rendering": False,
    "is_cancelled": False,
    "energy_peaks": []
}

class StrategizeRequest(BaseModel):
    url: str
    llm_label: Optional[str] = "🦙 LLaMA 3.1 8B Instruct Q4"
    whisper_label: Optional[str] = "Medium (Fast/Accurate)"
    angle: Optional[str] = "standard"
    session_id: Optional[str] = "global"

# Render tracking
_render_status = {} # { task_id: { status: "running"|"done"|"error", filename: str } }

class RenderRequest(BaseModel):
    clip_id: int # index in _state["clips"]
    face_center: bool = True
    magic_hook: bool = True
    remove_silence: bool = True
    caption_style: str = "Classic"
    caption_pos: str = "Bottom"
    bg_music_genre: str = "None"
    broll_intensity: str = "None"
    excluded_sentences: List[str] = []
    title: Optional[str] = None
    bg_style: str = "black"
    hook_position: str = "top"
    hook_display: str = "full"  # "full" | "3s" | "off"
    show_outro: bool = False
    title_style: str = "Impact"
    hook_style: str = "BlackOnWhiteBox"
    layout_mode: str = "box"
    header_font: Optional[str] = "bebas"
    caption_font: Optional[str] = "bebas"
    hook_font: Optional[str] = "bebas"
    header_style: str = "card"
    session_id: Optional[str] = "global"

class BulkRenderRequest(BaseModel):
    face_center: bool = True
    magic_hook: bool = True
    remove_silence: bool = True
    caption_style: str = "Classic"
    caption_pos: str = "Bottom"
    bg_music_genre: str = "None"
    broll_intensity: str = "None"
    clip_ids: Optional[List[int]] = None
    titles: Optional[dict] = None
    clip_settings: Optional[dict] = None
    bg_style: str = "black"
    hook_position: str = "top"
    hook_display: str = "full"  # "full" | "3s" | "off"
    show_outro: bool = False
    title_style: str = "Impact"
    hook_style: str = "BlackOnWhiteBox"
    layout_mode: str = "box"
    header_font: Optional[str] = "bebas"
    caption_font: Optional[str] = "bebas"
    hook_font: Optional[str] = "bebas"
    header_style: str = "card"
    session_id: Optional[str] = "global"

class SessionRequest(BaseModel):
    url: str

_GEMINI_KEY_VALID_CACHE = {}

def _is_gemini_key_valid() -> bool:
    import os, urllib.request, json
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return False

    if api_key in _GEMINI_KEY_VALID_CACHE:
        return _GEMINI_KEY_VALID_CACHE[api_key]

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": "ping"}]}],
        "generationConfig": {"maxOutputTokens": 5}
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status == 200:
                _GEMINI_KEY_VALID_CACHE[api_key] = True
                return True
    except Exception:
        pass
    _GEMINI_KEY_VALID_CACHE[api_key] = False
    return False


@app.get("/api/config")
async def get_config():
    return {
        "llm_catalog": [{"label": e["label"]} for e in LLM_CATALOG],
        "whisper_catalog": [{"label": e["label"]} for e in WHISPER_CATALOG],
        "bgm_genres": list(BGM_CATALOG.keys()),
        "gemini_active": _is_gemini_key_valid(),
    }

# ── Health Check ──
@app.get('/health')
async def health_check():
    return {'status': 'ok', 'timestamp': _dt.datetime.utcnow().isoformat() + 'Z', 'version': '2.5-pro'}

# ── Fonts Endpoint ──
@app.get('/api/fonts')
async def list_fonts():
    from shorts_generator.config import AVAILABLE_FONTS
    return {
        name: {'exists': path.exists(), 'path': str(path)}
        for name, path in AVAILABLE_FONTS.items()
    }

# ── Log Endpoints ──
@app.get('/api/logs/{session_id}')
async def get_logs(session_id: str, type: Optional[str] = Query(None), limit: int = 200):
    logger = get_logger(session_id)
    return {'entries': logger.get_entries(log_type=type, limit=limit)}

@app.get('/api/logs/{session_id}/stream')
async def stream_logs(session_id: str):
    logger = get_logger(session_id)
    last_idx = 0
    
    async def event_generator():
        nonlocal last_idx
        while True:
            current = logger.get_entries(limit=9999)
            if len(current) > last_idx:
                for entry in current[last_idx:]:
                    yield f'data: {json.dumps(entry)}\n\n'
                last_idx = len(current)
            await asyncio.sleep(0.5)
    
    return StreamingResponse(event_generator(), media_type='text/event-stream')

@app.get('/api/logs')
async def list_sessions():
    sessions = list(set(
        f.stem.replace('session_', '').split('_')[0]
        for f in LOG_DIR.glob('session_*.log')
    ))
    return {'sessions': sessions}

@app.get("/api/heartbeat")
async def heartbeat():
    return {
        "status": "online",
        "version": VERSION,
        "ts": time.time()
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
    last_idx = 0
    try:
        while True:
            entries = ui_logger._entries
            # Handle clear() scenario where _entries shrinks
            if last_idx > len(entries):
                last_idx = 0
            
            if last_idx < len(entries):
                new_entries = entries[last_idx:]
                last_idx = len(entries)
                import json as _json
                for entry in new_entries:
                    await websocket.send_text(_json.dumps(entry))
            await asyncio.sleep(0.4)
    except Exception:
        pass

def _save_session(url: str):
    import json
    try:
        video_id = cache.video_id(url)
        session_dir = os.path.join(SESSIONS_DIR, video_id)
        os.makedirs(session_dir, exist_ok=True)
        session_file = os.path.join(session_dir, "state.json")
        
        session_data = {
            "clips": _state.get("clips", []),
            "word_timestamps": _state.get("word_timestamps", []),
            "current_url": _state.get("current_url"),
            "persona": _state.get("persona", {}),
            "topics": _state.get("topics", []),
            "estimated_clips": _state.get("estimated_clips", 0),
            "video_duration": _state.get("video_duration", 0),
            "energy_peaks": _state.get("energy_peaks", [])
        }
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)
        ui_logger.log(f"💾 Session saved to Google Drive: sessions/{video_id}")
    except Exception as e:
        ui_logger.log(f"⚠️ Failed to save session to Google Drive: {e}")

def _run_strategize(url: str, llm_label: str, whisper_label: str, angle: str = "standard"):
    try:

        # Clear stale thumbnails from previous run
        import glob as _glob
        for _old in _glob.glob(os.path.join(THUMB_DIR, "thumb_*.jpg")):
            try:
                os.remove(_old)
            except OSError:
                pass
                
        strategy_start = time.time()
        def log_progress(pct: int, msg: str):
            if pct > 0:
                elapsed = time.time() - strategy_start
                eta = int(elapsed * (100 - pct) / pct)
                ui_logger.log(f"PROGRESS|{pct}|{msg}|{eta}")
            else:
                ui_logger.log(f"PROGRESS|{pct}|{msg}")

        log_progress(0, "Initializing AI strategy phase...")

        llm_entry = LLM_CATALOG[0]
        for entry in LLM_CATALOG:
            if entry["label"] == llm_label:
                llm_entry = entry
                break
                
        # Find Whisper
        wsp_size = "medium"
        for entry in WHISPER_CATALOG:
            if entry["label"] == whisper_label:
                wsp_size = entry["size"]
                break

        is_api_main = llm_entry["filename"].startswith("api:")

        llm_path = llm_entry["filename"] if is_api_main else os.path.join(LLM_DIR, llm_entry["filename"])

        if not is_api_main and not os.path.exists(llm_path):
            log_progress(5, "Downloading main LLM...")
            hf_hub_download(repo_id=llm_entry["repo"], filename=llm_entry["filename"], local_dir=LLM_DIR, local_dir_use_symlinks=False)

        source_mp4 = os.path.join(WORK_DIR, "source.mp4")
        _state["current_url"] = url.strip()

        if _state["is_cancelled"]: return

        if not os.path.exists(source_mp4) or cache.load_transcript(url.strip()) is None:
            log_progress(15, "Downloading video...")
            ui_logger.log(f"Looking for cookies at: {COOKIE_PATH}, Exists: {os.path.exists(COOKIE_PATH)}")
            if not os.path.exists(COOKIE_PATH):
                ui_logger._entries.append({
                    "type": "error",
                    "message": "Cookies file not found. Please upload cookies.txt to your workspace.",
                    "ts": _dt.datetime.now().strftime("%H:%M:%S")
                })
                log_progress(0, "Failed.")
                return

            try:
                download_video(url.strip(), WORK_DIR, cookie_path=COOKIE_PATH)
            except RuntimeError as e:
                ui_logger.error(str(e))
                log_progress(0, "Failed.")
                return

            # Fetch human-readable title from yt-dlp (fast, skip-download call)
            _state["video_title"] = get_video_title(url.strip(), cookie_path=COOKIE_PATH)

            if _state["is_cancelled"]: return
            log = ui_logger.log

            # SRT fast-path disabled due to rolling subtitle duplicates and mojibake.
            # We strictly use Faster-Whisper to guarantee clean word-level timestamps.
            word_timestamps = []
            log("🎙 Running Faster-Whisper transcription...")
            full_text, word_timestamps = transcribe_audio(source_mp4, model_size=wsp_size, whisper_dir=WHISPER_DIR)
            cache.save_transcript(url.strip(), full_text, word_timestamps)

            _state["word_timestamps"] = word_timestamps
        else:
            log_progress(25, "Transcript loaded from cache.")
            cached_t = cache.load_transcript(url.strip())
            _state["word_timestamps"] = cached_t[1]

        if _state["is_cancelled"]: return

        # Audio Energy Analysis
        log_progress(38, "Analyzing audio energy peaks...")
        energy_wav = os.path.join(WORK_DIR, "energy_temp.wav")
        try:
            import subprocess as _sp
            _sp.run(
                ["ffmpeg", "-y", "-i", source_mp4,
                 "-ar", "16000", "-ac", "1", energy_wav],
                capture_output=True, check=True
            )
            _state["energy_peaks"] = analyze_audio_energy(energy_wav)
            ui_logger.log(f"Found {len(_state['energy_peaks'])} high-energy audio moments.")
        except Exception as _e:
            ui_logger.log(f"Audio energy analysis skipped: {_e}")
            _state["energy_peaks"] = []
        finally:
            try:
                os.remove(energy_wav)
            except OSError:
                pass

        # Phase 0: Persona Detection
        log_progress(40, f"Phase 0/3: Analyzing Video Persona with {llm_entry['label']}...")
        persona = detect_video_persona(_state["word_timestamps"], llm_path=llm_path, gpu_layers=llm_entry["gpu_layers"])
        log_progress(45, f"Detected Genre: {persona.get('genre', 'Unknown')} | Tone: {persona.get('tone', 'Unknown')}")
        _state["persona"] = persona

        # Calculate estimated clip potential
        estimated = estimate_clip_potential(_state["word_timestamps"])
        _state["estimated_clips"] = estimated
        
        # Calculate video duration
        if _state["word_timestamps"]:
            wts = _state["word_timestamps"]
            _state["video_duration"] = wts[-1].get("end", 0) - wts[0].get("start", 0)
        
        log_progress(48, f"Video duration: {_state['video_duration']/60:.0f} min | Estimated clip potential: ~{estimated} clips")

        if _state["is_cancelled"]: return

        # Phase 1: Topic Indexing
        log_progress(55, "Phase 1/3: Mapping video topics...")
        topics = get_topic_index(_state["word_timestamps"], llm_path=llm_path, gpu_layers=llm_entry["gpu_layers"])
        _state["topics"] = topics
        log_progress(65, f"Found {len(topics)} distinct topics in the video.")

        if _state["is_cancelled"]: return

        # Phase 2: Per-Topic Clip Extraction
        log_progress(70, f"Phase 2/3: Extracting clips per topic with {llm_entry['label']}...")
        result = get_highlights(
            _state["word_timestamps"],
            num_clips=estimated,
            llm_path=llm_path,
            gpu_layers=llm_entry["gpu_layers"],
            max_clips=30,
            angle=angle,
            topics=topics,
            energy_peaks=_state["energy_peaks"],
            persona=_state["persona"],
        )

        clips = result.get("highlights", [])

        # Hard-reject clips that start in the opening segment (intros/outros)
        if clips and _state["word_timestamps"]:
            video_start = float(_state["word_timestamps"][0].get("start", 0))
            video_dur = float(_state.get("video_duration", 0))
            intro_threshold = min(15.0, max(5.0, video_dur * 0.02))
            clips = [c for c in clips if (float(c.get("start_time", 0)) - video_start) >= intro_threshold]

        if not clips:
            ui_logger.log(f"ERROR: No viral moments found in this video.")
            _state["clips"] = []
            cache.save_highlights(url.strip(), _state["clips"])
            cache.save_metadata(url.strip(), title=_state.get("video_title", ""),
                                duration=_state.get("video_duration", 0))
            log_progress(100, "Strategy Complete. No clips found.")
            return

        # Process durations and badges
        for i, c in enumerate(clips):
            dur = float(c.get("duration", 0))
            if dur == 0:
                dur = float(c.get("end_time", 0)) - float(c.get("start_time", 0))
            c["duration"] = dur
            c["badge"] = "🎬 Single"
            c["hook_type"] = c.get("hook_type", "curiosity_gap")

        # Extract thumbnails for each clip
        import subprocess as _sp
        for i, c in enumerate(clips):
            try:
                thumb_path = os.path.join(THUMB_DIR, f"thumb_{i}.jpg")
                start_time = float(c.get("start_time", 0))
                end_time = float(c.get("end_time", 0))
                peaks_in_clip = [p for p in _state.get("energy_peaks", []) if start_time <= p["time"] <= end_time]
                if peaks_in_clip:
                    highest_energy_peak = max(peaks_in_clip, key=lambda x: x["energy"])
                    seek_time = highest_energy_peak["time"]
                else:
                    seek_time = start_time + 2.0
                _sp.run(
                    ["ffmpeg", "-y", "-ss", str(seek_time), "-i", source_mp4,
                     "-vframes", "1", "-q:v", "3",
                     "-vf", "scale=540:960:force_original_aspect_ratio=increase,crop=540:960",
                     thumb_path],
                    capture_output=True, timeout=15
                )
                if os.path.exists(thumb_path):
                    c["thumbnail_url"] = f"/thumbs/thumb_{i}.jpg"
                else:
                    c["thumbnail_url"] = ""
            except Exception:
                c["thumbnail_url"] = ""

        _state["clips"] = clips
        cache.save_highlights(url.strip(), _state["clips"])
        cache.save_metadata(url.strip(), title=_state.get("video_title", ""),
                            duration=_state.get("video_duration", 0))
        _save_session(url.strip())
        log_progress(100, f"Strategy Complete. Found {len(clips)} clips (estimated potential: ~{_state['estimated_clips']}).")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        if not _state.get("is_cancelled"):
            ui_logger.log(f"ERROR: {str(e)}")
    finally:
        _state["is_strategizing"] = False
        if _state.get("is_cancelled"):
            log_progress(0, "Analysis was stopped by the user.")
            _state["is_cancelled"] = False

@app.post("/api/strategize")
async def strategize(req: StrategizeRequest, background_tasks: BackgroundTasks):
    if _state["is_strategizing"] or _state["is_rendering"]:
        raise HTTPException(status_code=400, detail="A task is already running.")
    _state["is_strategizing"] = True
    _state["is_cancelled"] = False
    ui_logger.clear()
    background_tasks.add_task(_run_strategize, req.url, req.llm_label, req.whisper_label, req.angle)
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
    _state["video_title"] = ""
    _state["energy_peaks"] = []
    _state["is_strategizing"] = False
    _state["is_rendering"] = False
    _state["is_cancelled"] = False
    ui_logger.clear()
    return {"message": "State reset."}

@app.get("/api/results")
async def get_results():
    if _state["is_strategizing"]:
        return {"status": "running"}
    video_id = ""
    url = _state.get("current_url")
    if url:
        video_id = cache.video_id(url)
    return {
        "status": "done",
        "current_url": url,
        "video_id": video_id,
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
        ui_logger.log(f"RENDER_STATUS|{req.clip_id}|rendering")
        ui_logger.log(f"Initializing render for clip index {req.clip_id}...")
        
        # Update client-edited title if provided
        if req.title:
            _state["clips"][req.clip_id]["title"] = req.title
            if _state.get("current_url"):
                _save_session(_state["current_url"])
        
        clip = _state["clips"][req.clip_id].copy() # Copy to avoid mutating global state
        
        # Defer BGM entirely to the user's bg_music_genre selection
        clip["music_query"] = ""
            
        input_mp4 = os.path.join(WORK_DIR, "source.mp4")
        if not os.path.exists(input_mp4):
            url = _state.get("current_url")
            if url:
                ui_logger.log(f"📥 Source video missing from session storage. Auto-downloading from: {url}...")
                download_video(url, WORK_DIR, cookie_path=COOKIE_PATH)
                ui_logger.log("✅ Source video downloaded successfully.")
            else:
                raise FileNotFoundError("Source video file is missing and no current URL is available in session state.")

        clips_dir = cache.get_clips_dir(_state["current_url"]) if _state["current_url"] else OUTPUT_DIR
        theme = clip.get("theme", "Storytime")
        
        all_sentences = [] # We would need to rebuild this from word_timestamps if needed, but for now we pass empty or rebuild.
        
        url = _state.get("current_url")
        video_id = cache.video_id(url) if url else ""

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
            all_sentences=all_sentences,
            bg_style=req.bg_style,
            hook_position=req.hook_position,
            hook_display=req.hook_display,
            show_outro=req.show_outro,
            title_style=req.title_style,
            layout_mode=req.layout_mode,
            hook_style=req.hook_style,
            header_font=req.header_font,
            caption_font=req.caption_font,
            hook_font=req.hook_font,
            header_style=getattr(req, "header_style", "card"),
            session_id=req.session_id
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
        session_output_dir = os.path.join(OUTPUT_DIR, video_id) if video_id else OUTPUT_DIR
        os.makedirs(session_output_dir, exist_ok=True)
        # Write a human-readable info file so this folder is identifiable on Drive
        _info_txt = os.path.join(session_output_dir, "_INFO.txt")
        if not os.path.exists(_info_txt) and _state.get("video_title"):
            with open(_info_txt, "w", encoding="utf-8") as _f:
                _f.write(f"Video: {_state['video_title']}\nURL:   {_state.get('current_url','')}\n")
        dst = os.path.join(session_output_dir, os.path.basename(out))
        if out != dst: shutil.copy2(out, dst)
        ui_logger.log(f"Rendered successfully: {os.path.basename(out)}")
        
        rel_fn = f"{video_id}/{os.path.basename(dst)}" if video_id else os.path.basename(dst)
        _render_status[task_id]["filename"] = rel_fn
        _render_status[task_id]["status"] = "done"
        ui_logger.log(f"RENDER_STATUS|{req.clip_id}|done")
        
        # Store rendered filename in the clip state to support CSV export and UI references
        _state["clips"][req.clip_id]["rendered_filename"] = rel_fn
        if _state.get("current_url"):
            _save_session(_state["current_url"])
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        ui_logger.log(f"ERROR: {str(e)}")
        _render_status[task_id] = {"status": "error", "error": str(e)}
        ui_logger.log(f"RENDER_STATUS|{req.clip_id}|error")
    finally:
        _state["is_rendering"] = False
        if _render_status.get(task_id, {}).get("status") != "error":
            _render_status[task_id]["status"] = "done"

def _run_bulk_render(req: BulkRenderRequest):
    try:
        
        num_clips = len(_state["clips"])
        target_ids = req.clip_ids if (req.clip_ids is not None) else list(range(num_clips))
        
        # Update any edited titles
        if req.titles:
            for idx_str, new_title in req.titles.items():
                try:
                    idx = int(idx_str)
                    if 0 <= idx < num_clips:
                        _state["clips"][idx]["title"] = new_title
                except ValueError:
                    continue
            if _state.get("current_url"):
                _save_session(_state["current_url"])
                
        ui_logger.log(f"Starting bulk render for {len(target_ids)} clips sequentially...")
        
        # Mark target clips as queued initially
        for idx in target_ids:
            if 0 <= idx < num_clips:
                ui_logger.log(f"RENDER_STATUS|{idx}|queued")
            
        input_mp4 = os.path.join(WORK_DIR, "source.mp4")
        if not os.path.exists(input_mp4):
            url = _state.get("current_url")
            if url:
                ui_logger.log(f"📥 Source video missing from session storage. Auto-downloading from: {url}...")
                download_video(url, WORK_DIR, cookie_path=COOKIE_PATH)
                ui_logger.log("✅ Source video downloaded successfully.")
            else:
                raise FileNotFoundError("Source video file is missing and no current URL is available in session state.")

        url = _state.get("current_url")
        video_id = cache.video_id(url) if url else ""

        clips_dir = cache.get_clips_dir(_state["current_url"]) if _state["current_url"] else OUTPUT_DIR
        
        for idx in target_ids:
            if idx < 0 or idx >= num_clips:
                continue
            if _state["is_cancelled"]:
                ui_logger.log("Bulk render cancelled by user.")
                break
                
            ui_logger.log(f"RENDER_STATUS|{idx}|rendering")
            clip = _state["clips"][idx].copy()
            
            # Defer BGM entirely to the user's bg_music_genre selection
            clip["music_query"] = ""
                
            theme = clip.get("theme", "Storytime")
            
            try:
                # Resolve per-clip settings
                settings = req.dict()
                idx_str = str(idx)
                if req.clip_settings and idx_str in req.clip_settings:
                    per_clip = req.clip_settings[idx_str]
                    if per_clip:
                        for k, v in per_clip.items():
                            if v is not None:
                                settings[k] = v

                c_pos = settings.get("caption_pos", "Bottom")
                if isinstance(c_pos, str):
                    c_pos = c_pos.capitalize()

                out = render_short(
                    input_video=input_mp4, clip_data=clip,
                    word_timestamps=_state["word_timestamps"],
                    output_dir=clips_dir, work_dir=WORK_DIR,
                    face_center=settings.get("face_center", True),
                    add_subs=(settings.get("caption_style", "Classic") != "None"),
                    theme=theme,
                    caption_style=settings.get("caption_style", "Classic"),
                    caption_pos=c_pos,
                    override_start=None, override_end=None,
                    excluded_sentences=[],
                    magic_hook=settings.get("magic_hook", True),
                    remove_silence=settings.get("remove_silence", True),
                    broll_intensity=settings.get("broll_intensity", "None"),
                    all_sentences=[],
                    bg_style=settings.get("bg_style", "black"),
                    hook_position=settings.get("hook_position", "top"),
                    hook_display=settings.get("hook_display", "full"),
                    show_outro=settings.get("show_outro", False),
                    title_style=settings.get("title_style", "Impact"),
                    layout_mode=settings.get("layout_mode", "box"),
                    hook_style=settings.get("hook_style", "BlackOnWhiteBox"),
                    header_font=settings.get("header_font", "bebas"),
                    caption_font=settings.get("caption_font", "bebas"),
                    hook_font=settings.get("hook_font", "bebas"),
                    header_style=settings.get("header_style", "card"),
                    session_id=settings.get("session_id", "global")
                )

                # BGM mixing
                bg_music_genre = settings.get("bg_music_genre", "None")
                if bg_music_genre and bg_music_genre != "None":
                    music_path = _get_bgm(bg_music_genre)
                    if music_path:
                        ui_logger.log(f"Mixing BGM ({bg_music_genre}) with dynamic peak swell for clip {idx}...")
                        try:
                            enhance_clip(out, clip, music_path=music_path)
                        except Exception as bgm_err:
                            ui_logger.log(f"BGM mixing failed ({bgm_err}) for clip {idx} — saved without music.")
                            
                import shutil
                session_output_dir = os.path.join(OUTPUT_DIR, video_id) if video_id else OUTPUT_DIR
                os.makedirs(session_output_dir, exist_ok=True)
                _info_txt = os.path.join(session_output_dir, "_INFO.txt")
                if not os.path.exists(_info_txt) and _state.get("video_title"):
                    with open(_info_txt, "w", encoding="utf-8") as _f:
                        _f.write(f"Video: {_state['video_title']}\nURL:   {_state.get('current_url','')}\n")
                dst = os.path.join(session_output_dir, os.path.basename(out))
                if out != dst:
                    shutil.copy2(out, dst)
                ui_logger.log(f"Rendered clip {idx} successfully: {os.path.basename(out)}")
                ui_logger.log(f"RENDER_STATUS|{idx}|done")
                
                # Store rendered filename in the clip state to support CSV export and UI references
                rel_fn = f"{video_id}/{os.path.basename(dst)}" if video_id else os.path.basename(dst)
                _state["clips"][idx]["rendered_filename"] = rel_fn
                if _state.get("current_url"):
                    _save_session(_state["current_url"])
                
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                traceback.print_exc()
                # Persist the failure to the on-disk logs (not just stdout/WebSocket)
                # so a crashed render can be diagnosed from the Drive logs afterward.
                try:
                    sid = locals().get("settings", {}).get("session_id", "global") if "settings" in locals() else "global"
                    get_logger(sid).log_app_event(
                        "render_clip", "failed", {"clip_index": idx}, error=tb[-1500:]
                    )
                except Exception:
                    pass
                ui_logger.log(f"ERROR rendering clip {idx}: {str(e)}")
                ui_logger.log(f"RENDER_STATUS|{idx}|error")
                
    except Exception as e:
        ui_logger.log(f"Bulk render error: {str(e)}")
    finally:
        _state["is_rendering"] = False

@app.post("/api/render")
async def render(req: RenderRequest, background_tasks: BackgroundTasks):
    if _state["is_rendering"] or _state["is_strategizing"]:
        raise HTTPException(status_code=400, detail="A task is already running.")
    if req.clip_id < 0 or req.clip_id >= len(_state["clips"]):
        raise HTTPException(status_code=404, detail="Clip not found.")
        
    # Validate all font selections before rendering
    for element in ['header_font', 'caption_font', 'hook_font']:
        font = getattr(req, element, 'bebas')
        font_key = font.lower().strip() if font else 'bebas'
        path = AVAILABLE_FONTS.get(font_key)
        if not path or not os.path.exists(path):
            raise HTTPException(status_code=400, detail=f"Missing font file for {element}: {font}. Add to work/fonts/")
    
    _state["is_rendering"] = True
    ui_logger.clear()
    
    task_id = f"render_{req.clip_id}_{int(time.time())}"
    _render_status[task_id] = {"status": "running"}
    
    background_tasks.add_task(_run_render, req, task_id)
    return {"message": "Render started.", "task_id": task_id}

@app.post("/api/render_all")
async def render_all(req: BulkRenderRequest, background_tasks: BackgroundTasks):
    if _state["is_rendering"] or _state["is_strategizing"]:
        raise HTTPException(status_code=400, detail="A task is already running.")
    if not _state["clips"]:
        raise HTTPException(status_code=400, detail="No clips available to render.")
        
    # Validate all global font selections before rendering
    for element in ['header_font', 'caption_font', 'hook_font']:
        font = getattr(req, element, 'bebas')
        font_key = font.lower().strip() if font else 'bebas'
        path = AVAILABLE_FONTS.get(font_key)
        if not path or not os.path.exists(path):
            raise HTTPException(status_code=400, detail=f"Missing global font file for {element}: {font}. Add to work/fonts/")
            
    # Validate per-clip font selections if provided
    if req.clip_settings:
        for idx_str, per_clip in req.clip_settings.items():
            if per_clip:
                for element in ['header_font', 'caption_font', 'hook_font']:
                    font = per_clip.get(element)
                    if font:
                        font_key = font.lower().strip()
                        path = AVAILABLE_FONTS.get(font_key)
                        if not path or not os.path.exists(path):
                            raise HTTPException(status_code=400, detail=f"Missing font file for {element} in clip {idx_str}: {font}. Add to work/fonts/")
    
    _state["is_rendering"] = True
    ui_logger.clear()
    
    background_tasks.add_task(_run_bulk_render, req)
    return {"message": "Bulk render started."}

@app.get("/api/download_single")
async def download_single(background_tasks: BackgroundTasks, filename: str):
    import zipfile
    import json
    
    mp4_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(mp4_path):
        raise HTTPException(status_code=404, detail="Clip not found.")
        
    clip_data = next((c for c in _state.get("clips", []) if c.get("rendered_filename") == filename), None)
    
    zip_path = os.path.join(WORK_DIR, f"clip_{int(time.time())}.zip")
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(mp4_path, filename)
            if clip_data:
                metadata = {
                    "title": clip_data.get("title", "Clip"),
                    "rationale": clip_data.get("rationale", ""),
                    "transcript": clip_data.get("transcript", ""),
                    "score": clip_data.get("score", 0),
                    "duration": clip_data.get("duration", 0),
                    "persona": clip_data.get("persona", ""),
                }
                meta_filename = f"{os.path.splitext(filename)[0]}_metadata.json"
                zipf.writestr(meta_filename, json.dumps(metadata, indent=4))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create ZIP: {str(e)}")
        
    def remove_file(path: str):
        try:
            os.remove(path)
        except OSError:
            pass

    background_tasks.add_task(remove_file, zip_path)
    return FileResponse(zip_path, media_type="application/zip", filename=f"clip_{os.path.splitext(filename)[0]}.zip")

@app.get("/api/download_all")
async def download_all(background_tasks: BackgroundTasks, project_only: bool = False, video_id: Optional[str] = None):
    import glob
    import zipfile
    import json

    if project_only:
        clips_to_download = [clip for clip in _state.get("clips", []) if clip.get("rendered_filename")]
        files = []
        curr_url = _state.get("current_url")
        curr_video_id = cache.video_id(curr_url) if curr_url else ""
        for clip in clips_to_download:
            fn = clip.get("rendered_filename")
            p1 = os.path.join(OUTPUT_DIR, fn)
            p2 = os.path.join(OUTPUT_DIR, curr_video_id, fn) if curr_video_id else p1
            if os.path.exists(p1):
                files.append(p1)
            elif os.path.exists(p2):
                files.append(p2)
    elif video_id:
        files = glob.glob(os.path.join(OUTPUT_DIR, video_id, "*.mp4"))
        clips_to_download = []
    else:
        files = glob.glob(os.path.join(OUTPUT_DIR, "**", "*.mp4"), recursive=True)
        clips_to_download = []
        
    if not files:
        raise HTTPException(status_code=404, detail="No matching rendered clips found to download.")
        
    zip_path = os.path.join(WORK_DIR, f"all_clips_{int(time.time())}.zip")
    
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file in files:
                zipf.write(file, os.path.basename(file))
            if project_only:
                for idx, clip in enumerate(clips_to_download):
                    filename = clip.get("rendered_filename")
                    if filename:
                        base_filename = os.path.basename(filename)
                        metadata = {
                            "title": clip.get("title", f"Clip {idx+1}"),
                            "rationale": clip.get("rationale", ""),
                            "transcript": clip.get("transcript", ""),
                            "score": clip.get("score", 0),
                            "duration": clip.get("duration", 0),
                            "persona": clip.get("persona", ""),
                        }
                        meta_filename = f"{os.path.splitext(base_filename)[0]}_metadata.json"
                        zipf.writestr(meta_filename, json.dumps(metadata, indent=4))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create ZIP: {str(e)}")
        
    def remove_file(path: str):
        try:
            os.remove(path)
        except OSError:
            pass
            
    background_tasks.add_task(remove_file, zip_path)
    
    filename = "clipfactory_project_clips.zip" if project_only else "clipfactory_all_clips.zip"
    if video_id:
        filename = f"clipfactory_session_{video_id[:8]}_clips.zip"
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=filename
    )


@app.post("/api/check_session")
async def check_session(req: SessionRequest):
    url = req.url.strip()
    video_id = cache.video_id(url)
    session_file = os.path.join(SESSIONS_DIR, video_id, "state.json")
    exists = os.path.exists(session_file)
    return {"exists": exists, "video_id": video_id}

@app.post("/api/restore_session")
async def restore_session(req: SessionRequest):
    import json
    url = req.url.strip()
    video_id = cache.video_id(url)
    session_file = os.path.join(SESSIONS_DIR, video_id, "state.json")
    if not os.path.exists(session_file):
        raise HTTPException(status_code=404, detail="No session found for this URL.")
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        _state["clips"] = data.get("clips", [])
        _state["word_timestamps"] = data.get("word_timestamps", [])
        _state["current_url"] = data.get("current_url", url)
        _state["persona"] = data.get("persona", {})
        _state["topics"] = data.get("topics", [])
        _state["estimated_clips"] = data.get("estimated_clips", 0)
        _state["video_duration"] = data.get("video_duration", 0)
        _state["energy_peaks"] = data.get("energy_peaks", [])
        _state["is_strategizing"] = False
        _state["is_rendering"] = False
        _state["is_cancelled"] = False
        
        ui_logger.clear()
        ui_logger.log(f"✅ Session successfully restored from Google Drive: {video_id}")
        return {"status": "success", "message": "Session restored."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to restore session: {str(e)}")

def _get_video_duration_ffprobe(filepath: str) -> float:
    import subprocess, json
    try:
        cmd = [
            "ffprobe", "-v", "quiet", 
            "-print_format", "json", 
            "-show_streams", 
            "-select_streams", "v:0", 
            filepath
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            streams = data.get("streams", [])
            if streams and "duration" in streams[0]:
                return float(streams[0]["duration"])
    except Exception as e:
        print(f"Error probing duration for {filepath}: {e}")
    return 0.0

@app.get("/api/gallery")
async def get_gallery(video_id: Optional[str] = None):
    import glob
    if video_id:
        files = glob.glob(os.path.join(OUTPUT_DIR, video_id, "*.mp4"))
    else:
        files = glob.glob(os.path.join(OUTPUT_DIR, "**", "*.mp4"), recursive=True)
        
    files.sort(key=os.path.getmtime, reverse=True)
    result = []
    for f in files:
        try:
            stat = os.stat(f)
            duration = _get_video_duration_ffprobe(f)
            rel_path = os.path.relpath(f, OUTPUT_DIR).replace("\\", "/")
            result.append({
                "filename": os.path.basename(f),
                "url": f"/media/{rel_path}",
                "size_mb": round(stat.st_size / (1024 * 1024), 1),
                "created_at": _dt.datetime.fromtimestamp(stat.st_mtime).strftime("%b %d, %H:%M"),
                "created_at_ts": float(stat.st_mtime),
                "duration": duration,
                "rel_path": rel_path
            })
        except OSError:
            continue
    return result

@app.get("/api/export_csv")
async def export_csv():
    import csv
    import io
    from fastapi.responses import StreamingResponse

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["filename", "clip title", "hook sentence", "virality score", "duration"])

    curr_url = _state.get("current_url")
    curr_video_id = cache.video_id(curr_url) if curr_url else ""
    
    for clip in _state.get("clips", []):
        fn = clip.get("rendered_filename")
        if fn:
            p1 = os.path.join(OUTPUT_DIR, fn)
            p2 = os.path.join(OUTPUT_DIR, curr_video_id, fn) if curr_video_id else p1
            if os.path.exists(p1) or os.path.exists(p2):
                writer.writerow([
                    os.path.basename(fn),
                    clip.get("title", ""),
                    clip.get("hook_sentence", ""),
                    clip.get("score", ""),
                    clip.get("duration", "")
                ])
            
    output.seek(0)
    return StreamingResponse(
        io.StringIO(output.getvalue()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=clipfactory_metadata.csv"}
    )

@app.post("/api/clear_gallery")
async def clear_gallery(project_only: bool = False, video_id: Optional[str] = None):
    import glob
    import shutil

    if project_only:
        current_filenames = {clip.get("rendered_filename") for clip in _state.get("clips", []) if clip.get("rendered_filename")}
        files = []
        curr_url = _state.get("current_url")
        curr_video_id = cache.video_id(curr_url) if curr_url else ""
        for fn in current_filenames:
            p1 = os.path.join(OUTPUT_DIR, fn)
            p2 = os.path.join(OUTPUT_DIR, curr_video_id, fn) if curr_video_id else p1
            if os.path.exists(p1):
                files.append(p1)
            elif os.path.exists(p2):
                files.append(p2)
        
        # Clear rendered_filename inside the _state so they are no longer marked as rendered
        for clip in _state.get("clips", []):
            if "rendered_filename" in clip:
                del clip["rendered_filename"]
        if _state.get("current_url"):
            _save_session(_state["current_url"])
    elif video_id:
        files = glob.glob(os.path.join(OUTPUT_DIR, video_id, "*.mp4"))
    else:
        files = glob.glob(os.path.join(OUTPUT_DIR, "**", "*.mp4"), recursive=True)
        
    deleted_count = 0
    for f in files:
        try:
            os.remove(f)
            deleted_count += 1
        except OSError:
            continue
            
    # Clean up empty subdirectories
    if not project_only and not video_id:
        for item in os.listdir(OUTPUT_DIR):
            item_path = os.path.join(OUTPUT_DIR, item)
            if os.path.isdir(item_path):
                try:
                    if not os.listdir(item_path):
                        os.rmdir(item_path)
                except OSError:
                    pass
    elif video_id:
        session_dir = os.path.join(OUTPUT_DIR, video_id)
        if os.path.exists(session_dir) and os.path.isdir(session_dir):
            try:
                if not os.listdir(session_dir):
                    os.rmdir(session_dir)
            except OSError:
                pass
                
    return {"status": "success", "message": f"Deleted {deleted_count} rendered clips."}

@app.get("/api/settings")
async def get_settings():
    env_file = os.path.join(BASE_DIR, ".env")
    env_vars = {}
    if os.path.exists(env_file):
        with open(env_file, "r") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    env_vars[k] = v.strip()
    return {
        "api_keys": {
            "GEMINI_API_KEY": env_vars.get("GEMINI_API_KEY", ""),
            "GROQ_API_KEY": env_vars.get("GROQ_API_KEY", ""),
            "OPENROUTER_API_KEY": env_vars.get("OPENROUTER_API_KEY", ""),
            "GLM_API_KEY": env_vars.get("GLM_API_KEY", ""),
        }
    }

class SettingsRequest(BaseModel):
    api_keys: dict

@app.post("/api/settings")
async def update_settings(req: SettingsRequest):
    env_file = os.path.join(BASE_DIR, ".env")
    env_vars = {}
    if os.path.exists(env_file):
        with open(env_file, "r") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    env_vars[k] = v
                    
    for k, v in req.api_keys.items():
        env_vars[k] = v.strip()
        os.environ[k] = v.strip()
            
    os.makedirs(BASE_DIR, exist_ok=True)
    with open(env_file, "w") as f:
        for k, v in env_vars.items():
            f.write(f"{k}={v}\n")
            
    return {"status": "success", "message": "Settings saved"}

@app.delete("/api/models/{filename:path}")
async def delete_model(filename: str):
    file_path = os.path.join(LLM_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Model not found")
    try:
        os.remove(file_path)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/sessions/{video_id}")
async def delete_session(video_id: str):
    import shutil
    session_dir = os.path.join(SESSIONS_DIR, video_id)
    if not os.path.exists(session_dir):
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        shutil.rmtree(session_dir)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/storage")
async def get_storage_info():
    import json
    models = []
    if os.path.exists(LLM_DIR):
        for f in os.listdir(LLM_DIR):
            path = os.path.join(LLM_DIR, f)
            if os.path.isfile(path) and f.endswith(".gguf"):
                models.append({
                    "filename": f,
                    "size_mb": round(os.path.getsize(path) / (1024 * 1024), 1)
                })
                
    sessions = []
    sessions_dir = SESSIONS_DIR
    if os.path.exists(sessions_dir):
        for f in os.listdir(sessions_dir):
            path = os.path.join(sessions_dir, f)
            if os.path.isdir(path):
                # Count files inside
                size = sum(os.path.getsize(os.path.join(path, f2)) for f2 in os.listdir(path) if os.path.isfile(os.path.join(path, f2)))
                state_file = os.path.join(path, "state.json")
                url = ""
                clips_count = 0
                duration = 0
                if os.path.exists(state_file):
                    try:
                        with open(state_file, "r", encoding="utf-8") as sf:
                            sdata = json.load(sf)
                            url = sdata.get("current_url", "")
                            clips_count = len(sdata.get("clips", []))
                            duration = sdata.get("video_duration", 0)
                    except:
                        pass
                sessions.append({
                    "video_id": f,
                    "size_mb": round(size / (1024 * 1024), 1),
                    "url": url,
                    "clips_count": clips_count,
                    "duration": duration
                })
                
    return {"models": models, "sessions": sessions}

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
