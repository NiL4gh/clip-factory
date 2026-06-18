import os
from dotenv import load_dotenv

load_dotenv()

# ── Drive detection ──────────────────────────────────────────────
DRIVE_ROOT = "/content/drive/MyDrive"
IN_COLAB = os.path.exists("/content")
DRIVE_MOUNTED = os.path.exists(DRIVE_ROOT)

# Calculate Repo root dynamically
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Storage layout ────────────────────────────────────────────────
# Everything persistent lives under BASE_DIR (on Google Drive when mounted, so it
# survives the Colab runtime being recycled). One clean, navigable tree:
#
#   {BASE_DIR}/                         (Drive: MyDrive/clip_factory)
#   ├── models/llm/                     large GGUF model files — KEEP, never auto-clean
#   ├── models/whisper/                 cached Whisper weights
#   ├── projects/<video_id>/            per-video working data (transcript, highlights, clips)
#   ├── output/<video_id>/              final rendered clips shown in the gallery
#   ├── sessions/<video_id>/            resumable strategy state (state.json)
#   ├── logs/                           AI-debug logs (JSONL + text) — persisted for diagnosis
#   └── cookies.txt / .env              YouTube cookies + optional API keys
#
# <video_id> is the same readable key everywhere (the YouTube id, e.g. ru44DngJYoA;
# see cache.video_id). WORK_DIR stays INSIDE the cloned repo because the launcher
# downloads fonts there (work/fonts) — a mismatch makes every caption font "missing".
if IN_COLAB:
    if DRIVE_MOUNTED:
        BASE_DIR = os.getenv("BASE_DIR", f"{DRIVE_ROOT}/clip_factory")
    else:
        BASE_DIR = os.getenv("BASE_DIR", "/content/clip_factory")
    WORK_DIR = os.getenv("WORK_DIR", os.path.join(REPO_ROOT, "work"))
else:
    BASE_DIR = os.getenv("BASE_DIR", REPO_ROOT)
    WORK_DIR = os.getenv("WORK_DIR", os.path.join(REPO_ROOT, "work"))

# Create a hidden system directory for internal data
SYSTEM_DIR = os.getenv("SYSTEM_DIR", os.path.join(BASE_DIR, ".system"))

# Persistent, large — must NOT move or models re-download (slow). Keep these paths stable.
LLM_DIR      = os.getenv("LLM_DIR",      os.path.join(SYSTEM_DIR, "models", "llm"))
WHISPER_DIR  = os.getenv("WHISPER_DIR",  os.path.join(SYSTEM_DIR, "models", "whisper"))
# Per-video data, outputs, resumable sessions, and diagnosis logs.
PROJECTS_DIR = os.getenv("PROJECTS_DIR", os.path.join(SYSTEM_DIR, "projects"))
SESSIONS_DIR = os.getenv("SESSIONS_DIR", os.path.join(SYSTEM_DIR, "sessions"))
OUTPUT_DIR   = os.getenv("OUTPUT_DIR",   os.path.join(BASE_DIR, "output"))
LOGS_DIR     = os.getenv("LOGS_DIR",     os.path.join(BASE_DIR, "logs"))
COOKIE_PATH  = os.getenv("COOKIE_PATH",  os.path.join(BASE_DIR, "cookies.txt"))

# Load .env file from BASE_DIR if it exists, otherwise default load_dotenv
env_path = os.path.join(BASE_DIR, ".env")
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    load_dotenv()

# ── Zero-Setup Cookies ───────────────────────────────────────────
YT_COOKIES_DATA = """# Netscape HTTP Cookie File
# https://curl.haxx.se/rfc/cookie_spec.html
# This is a generated file! Do not edit.

.youtube.com	TRUE	/	FALSE	1812296175	HSID	A5HnZ5Kn0P9L4PKxw
.youtube.com	TRUE	/	TRUE	1812296175	SSID	AVGQl_8rbYa8EseNU
.youtube.com	TRUE	/	FALSE	1812296175	APISID	6Cdh_xdaJGTb63sd/AiqEylFjrLiynumS4
.youtube.com	TRUE	/	TRUE	1812296175	SAPISID	lHVyG-M-TvP21gIQ/AfoKBM6sVMT4f8o_G
.youtube.com	TRUE	/	TRUE	1812296175	__Secure-1PAPISID	lHVyG-M-TvP21gIQ/AfoKBM6sVMT4f8o_G
.youtube.com	TRUE	/	TRUE	1812296175	__Secure-3PAPISID	lHVyG-M-TvP21gIQ/AfoKBM6sVMT4f8o_G
.youtube.com	TRUE	/	FALSE	1812296175	SID	g.a0009giS1byKGQjHCZCvw1M91LzOj47Q1wjRbNEmr6acuHugviC7q8G3TQYlAqT2vvgxDivZbgACgYKAQESARYSFQHGX2Mi-XRc9mRriUfvQJEMGcmNXhoVAUF8yKoEFudS9UZhw2pTWOn1MRyJ0076
.youtube.com	TRUE	/	TRUE	1812296175	__Secure-1PSID	g.a0009giS1byKGQjHCZCvw1M91LzOj47Q1wjRbNEmr6acuHugviC7v-A7pYZwnskV2O9LmCfmEAACgYKAdoSARYSFQHGX2MiEC3fG8VXLlvMWF9pbrGGJxoVAUF8yKqI30QXop-LIsb0gsXL9fcy0076
.youtube.com	TRUE	/	TRUE	1812296175	__Secure-3PSID	g.a0009giS1byKGQjHCZCvw1M91LzOj47Q1wjRbNEmr6acuHugviC7Gs3n6K_nJShvrHg_PD2B_AACgYKAZcSARYSFQHGX2MitpNK9jcc-rwzbCN9si-bshoVAUF8yKoRZWM6_PjawH-kEVRDSVF40076
.youtube.com	TRUE	/	TRUE	1812296176	LOGIN_INFO	AFmmF2swRAIgOk4dp2PPbOhj9rm-doXqBIPJaxo3JTQgG51k6UlOIFECIHbdBpsqJgzSXZcyfNpLpK8_2NaC1l9NtwQLaVRPYWUJ:QUQ3MjNmeEN1N2I4eEl4VE03QmhLUkNwWnE2alJNekFReUZlN3N0aW1pUlp3OHk4bDBBa0cxdjVET0hUU2l0aUNveWF4YVRLMk52cnZYQy1xX1RmdW1xdFFqSjZrcG15eVliUzhCdk9YbVlQd25CVTQyTnM5aEE4dmxtUmVjVEJESEhSbGJpVnZ0ZzE2bjg0TVh1R09tRFFpT19WUG91YTZn
.youtube.com	TRUE	/	TRUE	1812395980	PREF	f6=40000000&tz=Asia.Dhaka&f7=100
.youtube.com	TRUE	/	TRUE	1793647180	NID	531=DiMua0ZtIFJoTzSWG-IhJtZHwYXdPsVExUKFRMdaaeZ4AABo1iEqWda2vYxz4_UYWwzraaScHu3Y2VcXFczDY1jw_Pmrc0soMrcESYlRqcPZB-KpJyqtbFOSu2w92q5AZWs4eBR3cwfq1O_q-dHF1yZDGCZdq6QsT1_RSOejbY0f4_ZXjDw7nDq0PajMi656lhzPduyu_suXnrp6LxYh_RwXQQxemRDB2VlwE4_RFrAW8g
.youtube.com	TRUE	/	TRUE	1809371982	__Secure-1PSIDTS	sidts-CjUBhkeRd3kelMt2RODyb_6eY_Ixsp1J2X3P6LBMUs7ZXYdCV0wH4zhVnuj4hHzuf9of0VanSxAA
.youtube.com	TRUE	/	TRUE	1809371982	__Secure-3PSIDTS	sidts-CjUBhkeRd3kelMt2RODyb_6eY_Ixsp1J2X3P6LBMUs7ZXYdCV0wH4zhVnuj4hHzuf9of0VanSxAA
.youtube.com	TRUE	/	FALSE	1809371982	SIDCC	AKEyXzV3C4EvzxBd2TUGhJSW2Su0VBN-qhS_yb2eqa9lCm7QpZ67injDdAzWwiqSrlFgHVQ5CQ
.youtube.com	TRUE	/	TRUE	1809371982	__Secure-1PSIDCC	AKEyXzXleF-boI9klNvgiZnzyScCojXPeBzRnL1wRWLWuCsqR6hJj0ZgqXkk9KZ1Y3wH-5DmXzY
.youtube.com	TRUE	/	TRUE	1809371982	__Secure-3PSIDCC	AKEyXzWMrPEiGtO2kfy4gstr9c8f7fXzOF5PUYRbzhyHgGXf5YKSgt3QNnm1lUZDB3xfMtvu1Q
.youtube.com	TRUE	/	TRUE	1793387982	VISITOR_INFO1_LIVE	j0aLadtzWt0
.youtube.com	TRUE	/	TRUE	1793387982	VISITOR_PRIVACY_METADATA	CgJCRBIEGgAgUQ%3D%3D
.youtube.com	TRUE	/	TRUE	0	YSC	dE2ag721MdQ
.youtube.com	TRUE	/	TRUE	1793387978	__Secure-ROLLOUT_TOKEN	CK_bwu3BhYaGgAEQ0brkqPealAMYhZbljeudlAM%3D
"""

# Auto-write cookies to disk for yt-dlp if not exist
if not os.path.exists(COOKIE_PATH):
    os.makedirs(os.path.dirname(COOKIE_PATH), exist_ok=True)
    with open(COOKIE_PATH, "w") as f:
        f.write(YT_COOKIES_DATA)



# ── Font Configuration ───────────────────────────────────────────
from pathlib import Path
FONT_DIR = Path(WORK_DIR) / "fonts"
AVAILABLE_FONTS = {
    'montserrat': FONT_DIR / 'Montserrat-Bold.ttf',
    'montserrat bold': FONT_DIR / 'Montserrat-Bold.ttf',
    'montserrat semibold': FONT_DIR / 'Montserrat-SemiBold.ttf',
    'montserrat-semibold': FONT_DIR / 'Montserrat-SemiBold.ttf',
    'montserrat black': FONT_DIR / 'Montserrat-Black.ttf',
    'montserrat-black': FONT_DIR / 'Montserrat-Black.ttf',
    'bebas': FONT_DIR / 'BebasNeue-Regular.ttf',
    'bebas neue': FONT_DIR / 'BebasNeue-Regular.ttf',
    'inter': FONT_DIR / 'Inter-Bold.ttf',
    'roboto': FONT_DIR / 'Roboto-Bold.ttf',
    'poppins': FONT_DIR / 'Poppins-Bold.ttf',
}
# Retain original case keys for backwards-compatibility and references
AVAILABLE_FONTS.update({
    'Montserrat': AVAILABLE_FONTS['montserrat'],
    'Montserrat SemiBold': AVAILABLE_FONTS['montserrat semibold'],
    'Montserrat Black': AVAILABLE_FONTS['montserrat-black'],
    'Bebas Neue': AVAILABLE_FONTS['bebas neue'],
    'Inter': AVAILABLE_FONTS['inter'],
    'Roboto': AVAILABLE_FONTS['roboto'],
    'Poppins': AVAILABLE_FONTS['poppins'],
})
FONT_PATH = AVAILABLE_FONTS['Montserrat']

# Warn on import if fonts missing
for name, path in AVAILABLE_FONTS.items():
    if not path.exists():
        print(f'⚠️  Font missing: {name} at {path}')

# ── Local & API LLM catalog ───────────────────────────────────────
LLM_CATALOG = [
    {"label": "♊ Google Gemini 2.5 Flash (API)",
     "filename": "api:gemini:gemini-2.5-flash",
     "repo": "google",
     "gpu_layers": 0},
    {"label": "🟢 Nvidia Llama 3.1 70B (API)",
     "filename": "api:nvidia:meta/llama-3.1-70b-instruct",
     "repo": "nvidia",
     "gpu_layers": 0},
    {"label": "🟢 Nvidia Llama 3.1 405B (API)",
     "filename": "api:nvidia:meta/llama-3.1-405b-instruct",
     "repo": "nvidia",
     "gpu_layers": 0},
    {"label": "🟢 Nvidia Nemotron 70B (API)",
     "filename": "api:nvidia:nvidia/llama-3.1-nemotron-70b-instruct",
     "repo": "nvidia",
     "gpu_layers": 0},
    {"label": "⚡ Groq Llama 3.1 8B (API)",
     "filename": "api:groq:llama-3.1-8b-instant",
     "repo": "groq",
     "gpu_layers": 0},
    {"label": "🌐 OpenRouter Llama 3.1 (API)",
     "filename": "api:openrouter:meta-llama/llama-3.1-8b-instruct",
     "repo": "openrouter",
     "gpu_layers": 0},
    {"label": "🧠 GLM 4 Flash (API)",
     "filename": "api:glm:glm-4-flash",
     "repo": "zhipu",
     "gpu_layers": 0},
    {"label": "🦙 Ollama Llama 3.1 (Local API)",
     "filename": "api:ollama:llama3.1",
     "repo": "ollama",
     "gpu_layers": 0},
    {"label": "🦙 LLaMA 3.1 8B Instruct Q4",
     "filename": "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
     "repo": "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
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
    {"label": "🚀 Mistral NeMo 12B Q4 (16GB+ VRAM)",
     "filename": "Mistral-Nemo-Instruct-2407-Q4_K_M.gguf",
     "repo": "bartowski/Mistral-Nemo-Instruct-2407-GGUF",
     "gpu_layers": 40},
    {"label": "🧠 Qwen2.5 14B Instruct Q4 (16GB+ VRAM)",
     "filename": "qwen2.5-14b-instruct-q4_k_m.gguf",
     "repo": "Qwen/Qwen2.5-14B-Instruct-GGUF",
     "gpu_layers": 40},
    {"label": "✨ Gemma 2 9B Q4 (16GB+ VRAM)",
     "filename": "gemma-2-9b-it-Q4_K_M.gguf",
     "repo": "bartowski/gemma-2-9b-it-GGUF",
     "gpu_layers": 40},
    {"label": "💎 Gemma 2 27B Q4 (24GB+ VRAM)",
     "filename": "gemma-2-27b-it-Q4_K_M.gguf",
     "repo": "bartowski/gemma-2-27b-it-GGUF",
     "gpu_layers": 46},
    {"label": "🌌 Llama-3.1-70B Q2 (40GB VRAM / A100)",
     "filename": "Meta-Llama-3.1-70B-Instruct-Q2_K.gguf",
     "repo": "bartowski/Meta-Llama-3.1-70B-Instruct-GGUF",
     "gpu_layers": 81},
]

WHISPER_CATALOG = [
    {"label": "🐢 tiny",     "size": "tiny"},
    {"label": "🐇 base",     "size": "base"},
    {"label": "🏃 small",    "size": "small"},
    {"label": "⭐ medium",   "size": "medium"},
    {"label": "🌟 large-v2", "size": "large-v2"},
    {"label": "💎 large-v3", "size": "large-v3"},
]
