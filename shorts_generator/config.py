import os
from dotenv import load_dotenv

load_dotenv()

# ── Drive detection ──────────────────────────────────────────────
DRIVE_ROOT = "/content/drive/MyDrive"
IN_COLAB = os.path.exists("/content")
DRIVE_MOUNTED = os.path.exists(DRIVE_ROOT)

# ── Paths ── Drive-first if available, fallback to /content ──────
if DRIVE_MOUNTED:
    BASE_DIR = os.getenv("BASE_DIR", f"{DRIVE_ROOT}/clip_factory")
else:
    BASE_DIR = os.getenv("BASE_DIR", "/content/clip_factory")

WORK_DIR     = os.getenv("WORK_DIR",     "/content/work")
OUTPUT_DIR   = os.getenv("OUTPUT_DIR",   f"{BASE_DIR}/output")
LLM_DIR      = os.getenv("LLM_DIR",      f"{BASE_DIR}/models/llm")
WHISPER_DIR  = os.getenv("WHISPER_DIR",  f"{BASE_DIR}/models/whisper")
PROJECTS_DIR = os.getenv("PROJECTS_DIR", f"{BASE_DIR}/projects")
COOKIE_PATH  = os.getenv("COOKIE_PATH",  f"{BASE_DIR}/cookies.txt")

# ── MuAPI (optional cloud fallback) ─────────────────────────────
MUAPI_API_KEY  = os.getenv("MUAPI_API_KEY", "").strip()
MUAPI_BASE_URL = os.getenv("MUAPI_BASE_URL", "https://api.muapi.ai/api/v1").rstrip("/")
POLL_INTERVAL_SECONDS = float(os.getenv("MUAPI_POLL_INTERVAL", "5"))
POLL_TIMEOUT_SECONDS  = float(os.getenv("MUAPI_POLL_TIMEOUT",  "600"))

# ── Local LLM catalog ────────────────────────────────────────────
LLM_CATALOG = [
    {"label": "🦙 LLaMA 3 8B Instruct Q4",
     "filename": "Meta-Llama-3-8B-Instruct-Q4_K_M.gguf",
     "repo": "bartowski/Meta-Llama-3-8B-Instruct-GGUF",
     "gpu_layers": 33},
    {"label": "⭐ Mistral 7B Instruct Q4",
     "filename": "mistral-7b-instruct-v0.2.Q4_K_M.gguf",
     "repo": "TheBloke/Mistral-7B-Instruct-v0.2-GGUF",
     "gpu_layers": 35},
    {"label": "🌟 Qwen2 7B Instruct Q4",
     "filename": "qwen2-7b-instruct-q4_k_m.gguf",
     "repo": "Qwen/Qwen2-7B-Instruct-GGUF",
     "gpu_layers": 35},
    {"label": "⚡ Phi-3 Mini Q4 (low VRAM)",
     "filename": "Phi-3-mini-4k-instruct-q4.gguf",
     "repo": "microsoft/Phi-3-mini-4k-instruct-gguf",
     "gpu_layers": 40},
    {"label": "💎 Gemma 2 2B Q4 (fastest)",
     "filename": "gemma-2-2b-it-Q4_K_M.gguf",
     "repo": "bartowski/gemma-2-2b-it-GGUF",
     "gpu_layers": 40},
]

WHISPER_CATALOG = [
    {"label": "🐢 tiny",     "size": "tiny"},
    {"label": "🐇 base",     "size": "base"},
    {"label": "🏃 small",    "size": "small"},
    {"label": "⭐ medium",   "size": "medium"},
    {"label": "🌟 large-v2", "size": "large-v2"},
    {"label": "💎 large-v3", "size": "large-v3"},
]
