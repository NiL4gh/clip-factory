# ClipFactory.ai (Premium Shorts Engine)

![ClipFactory UI Placeholder](https://via.placeholder.com/1000x500.png?text=ClipFactory.ai+-+Premium+SaaS+Dashboard)

Transform long-form YouTube videos into highly engaging, viral-ready TikToks, Reels, and Shorts completely automatically and for free entirely within Google Colab.

*This project was originally forked from the open-source `AI-Shorts-Generator`, but has been completely re-architected and transformed into a premium, SaaS-grade clipping engine designed to rival paid tools like OpusClip and Vizard.ai.*

## ✨ The Premium Parity Features

- **AI Virality Scoring:** Uses local LLMs (like Llama 3) to scan the transcript and extract the most engaging 30-90s continuous story arcs based on Hooks, Emotion, and Payoffs.
- **Smart Pacing (Silence Removal):** Automatically slices out dead air and pauses >0.8 seconds to maintain aggressive, TikTok-style pacing.
- **Auto-Framing (Face Tracking):** OpenCV-powered active speaker tracking to dynamically keep subjects centered in the 9:16 crop.
- **Dynamic B-Roll & Ken Burns:** The LLM identifies visual keywords and silently fetches images via DuckDuckGo, automatically applying a documentary-style "Ken Burns" zoom & pan via FFmpeg.
- **Slide-Up Emojis:** Auto-fetches high-res PNGs from Twemoji and overlays them onto the video with satisfying, mathematical slide-up "pop" animations.
- **"Hormozi" Style Captions:** Dynamic, color-themed ASS subtitles with active-word highlighting.
- **Transcript Text Editor:** Edit the video timeline simply by unchecking sentences in the UI transcript—the engine instantly slices them out of the final video.
- **Auto Audio Mix:** Automatically ducks background music and mathematically injects "Pop/Swoosh" SFX exactly when visual interrupts appear.

## 🚀 How to Run (Google Colab)

1. Open a new Google Colab notebook.
2. Ensure you have a GPU runtime enabled (`T4` or higher).
3. Run the following cell to setup the environment and launch the UI:

```python
# Mount Google Drive for caching
from google.colab import drive
drive.mount('/content/drive')

# Clone & Setup
!git clone https://github.com/NiL4gh/AI-Shorts-Generator-opus.git
%cd /content/AI-Shorts-Generator-opus
!chmod +x setup.sh
!./setup.sh

# Launch the SaaS Dashboard
import sys
if '/content/AI-Shorts-Generator-opus' not in sys.path:
    sys.path.insert(0, '/content/AI-Shorts-Generator-opus')
!python app.py
```

## 🛠️ Architecture

This project bypasses expensive API constraints (like Stock Footage or GPT-4 APIs) by utilizing clever open-source workarounds:
- **Transcription:** `faster-whisper`
- **Logic/Curation:** Local GGUF models via `llama-cpp-python`
- **Media Scraping:** `yt-dlp` and `duckduckgo-search`
- **Rendering Engine:** Advanced `ffmpeg-python` filtergraphs
- **Interface:** Custom-styled `Gradio` dashboard mimicking premium web apps.

## 🤝 Acknowledgements
Originally forked from standard clipping scripts, this repository represents a complete structural overhaul aimed at professional content-reward creators requiring high-volume output.
