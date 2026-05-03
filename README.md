# ClipFactory.ai — Premium Shorts Engine

> Turn long-form YouTube videos into viral 9:16 Shorts, Reels & TikToks — **free, local AI, no watermarks, no credits.**

A fully open-source, self-hosted alternative to **OpusClip** and **Vizard.ai**, running entirely inside Google Colab with a premium SaaS-grade Gradio UI.

---

## ✨ Features

| Feature | Description |
|---|---|
| 🧠 **AI Virality Scoring** | Local LLM (Mistral / Llama 3 / Qwen2) scans the transcript and extracts top story arcs scored by Hook → Body → Payoff |
| ✂️ **Smart Silence Removal** | Auto-slices dead air >0.8s using Whisper word timestamps for aggressive TikTok pacing |
| 🎯 **Auto Face Framing** | OpenCV detects the active speaker and dynamically centers the 9:16 crop |
| 🖼️ **Ken Burns B-Roll** | LLM identifies visual keywords → DuckDuckGo fetches an image → FFmpeg applies a smooth zoom/pan motion effect |
| 😂 **Slide-Up Emojis** | LLM picks Twemojis → downloaded as PNG → animated with a mathematical slide-up pop effect |
| 📝 **Transcript Editor** | Uncheck any sentence in the UI → FFmpeg slices it out of the final video timeline |
| 🔥 **Hormozi Captions** | Dynamic ASS subtitles with per-word active highlighting and theme-based color palettes |
| 🎵 **Smart BGM Mixing** | Background music auto-ducks and swells at the clip's peak moment |
| 💾 **Drive Persistence** | Models and project cache save to Google Drive — skip re-downloading on every session |

---

## 🚀 Quick Start (Google Colab)

> **Requirement:** Set runtime to **T4 GPU** (`Runtime → Change runtime type → T4 GPU`)

### Cell 0 — Mount Google Drive *(run first, once)*
```python
from google.colab import drive
drive.mount('/content/drive')
print("✅ Drive mounted.")
```

### Cell 1 — Setup *(run once per session, ~2 min)*
```python
import os, sys

REPO_DIR = '/content/AI-Shorts-Generator-opus'

# Clone or update
if not os.path.exists(REPO_DIR):
    !git clone --depth 1 https://github.com/NiL4gh/AI-Shorts-Generator-opus {REPO_DIR}
else:
    !git -C {REPO_DIR} pull
    print('Repo up to date.')

# Install dependencies
!pip install -q -r {REPO_DIR}/requirements.txt

# Install llama-cpp-python from prebuilt CUDA wheel (skips 10-min compile)
!pip install llama-cpp-python --prefer-binary --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124

# Install Deno for yt-dlp JS extraction (fixes YouTube bot-check)
!curl -fsSL https://deno.land/install.sh | sh
os.environ["PATH"] = os.path.expanduser("~/.deno/bin") + ":" + os.environ["PATH"]

# Install Arial Black font for Hormozi captions
!apt-get install -q -y fonts-liberation msttcorefonts 2>/dev/null || true

sys.path.insert(0, REPO_DIR)
print('✅ Ready to launch.')
```

### Cell 2 — Launch the App
```python
import os, sys

REPO_DIR = '/content/AI-Shorts-Generator-opus'
os.chdir(REPO_DIR)
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

# Point models and output to Google Drive for persistence across sessions
os.environ['LLM_DIR']      = '/content/drive/MyDrive/clip_factory/models/llm'
os.environ['WHISPER_DIR']  = '/content/drive/MyDrive/clip_factory/models/whisper'
os.environ['OUTPUT_DIR']   = '/content/drive/MyDrive/clip_factory/output'
os.environ['PROJECTS_DIR'] = '/content/drive/MyDrive/clip_factory/projects'

# Create dirs if they don't exist
for d in [os.environ['LLM_DIR'], os.environ['WHISPER_DIR'],
          os.environ['OUTPUT_DIR'], os.environ['PROJECTS_DIR']]:
    os.makedirs(d, exist_ok=True)

!python app.py
```

> Open the **`gradio.live`** public URL that is printed. The first run downloads the LLM (~4GB) and Whisper model to your Drive — subsequent sessions load instantly from cache.

---

## 🛠️ Architecture

```
app.py                          ← Gradio SaaS dashboard (sidebar + card grid UI)
shorts_generator/
  config.py                     ← Paths, LLM catalog, Whisper catalog
  downloader.py                 ← yt-dlp YouTube download
  transcriber.py                ← faster-whisper transcription + word timestamps
  highlights.py                 ← Local LLM virality scoring + JSON schema extraction
  clipper.py                    ← FFmpeg rendering engine (crop, B-Roll, emojis, captions, SFX)
  enhancer.py                   ← BGM mixing with dynamic peak swell
  media.py                      ← DuckDuckGo B-Roll, Twemoji PNG, SFX fetcher
  cache.py                      ← Drive-backed project cache (transcript + highlights)
  pipeline.py                   ← Standalone pipeline class for non-UI usage
```

**Local models used (auto-downloaded from HuggingFace):**

| Model | Size | Purpose |
|---|---|---|
| Mistral 7B Instruct Q4_K_M | 4.4 GB | Default LLM for virality scoring |
| Llama 3 8B Instruct Q4_K_M | 4.7 GB | Optional higher-quality LLM |
| Whisper Medium | ~1.5 GB | Speech-to-text with word timestamps |

---

## ⚠️ Known Limitations

- **B-Roll zoompan is CPU-rendered** — can take a few extra minutes per clip if many B-Roll segments are detected. Disable by unchecking "Auto Face Tracking & B-Roll" in the UI.
- **DuckDuckGo B-Roll** — uses an unofficial image search API. May be rate-limited on shared Colab IPs; if B-Roll fails silently, it degrades gracefully (no image overlay, no crash).
- **YouTube cookies** — Age-restricted or login-required videos need a `cookies.txt` file. Export using the [EditThisCookie](https://chrome.google.com/webstore/detail/editthiscookie/fngmhnnpilhplaeedifhccceomclgfbg) browser extension and upload to `/content/drive/MyDrive/clip_factory/cookies.txt`.
- **Gradio share link** — expires after 1 week. Re-run Cell 2 to get a fresh link.

---

## 🤝 Acknowledgements

This project takes conceptual inspiration from the open-source YouTube shorts clipping community. The architecture, rendering engine, LLM prompting strategy, Gradio UI design, and all feature implementations were built independently.

---

## 📄 License

This project is released for personal and educational use. Commercial use is at your own discretion.
