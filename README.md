# ClipFactory.ai — v2.5-PRO-STRATEGY AI Video Director

> Turn long-form YouTube videos into viral 9:16 Shorts, Reels & TikToks — **Free, Local or Cloud AI, no watermarks, no subscription fees.**

ClipFactory.ai is a production-grade, self-hosted AI video repurposing platform custom-built for high-volume creator clipping. It features a dual-server architecture with a **FastAPI** backend and a premium **Next.js** dashboard dashboard interface.

---

## ✨ Features

| Feature | Description |
|---|---|
| ♊ **Gemini & Local LLM** | Google Gemini 2.5 Flash as preferred director with active API key validation, falling back to local LLaMA 3 & Gemma 2 to prevent any failure. |
| 📊 **Sub-Score Decomposition** | Decomposes clip potential into Hook (H), Engagement (En), Value (Va), and Shareability (Sh) sub-scores in prompt and UI. |
| 🗂️ **Hook-Strength Sorting** | Sort results instantly by composite Virality Score, Energy Score, Duration, or Hook Score. |
| 🎨 **1:1 Center-Cropped Layout** | Center-crops horizontal videos to 1:1 and displays them over beautiful customizable backgrounds (Black, Brand Slate-900, Blur, or dark smooth Gradient). |
| 🪝 **Opaque Magic Hooks** | Top-center aligned, opaque gold CapCut-style scroll-stopper hooks wrapped tightly to 18 characters. |
| ⏱️ **Zero-Collision Timing** | Mutual exclusivity timing: Magic Hook displays for the first 3s (fading out), then hands off to the Header title at 3.5s to prevent any overlaps. |
| 📝 **Transcript Cuts Editor** | Precise word-level cutting UI — click sentence chips to exclude words or phrases from the final rendering pass. |
| ⚡ **Librosa Energy Peaks** | Audio amplitude energy scoring combining RMS peak analysis (40%) and LLM virality (60%) into a composite score. |
| 🎚️ **Dynamic Silence Cuts** | Dynamically evaluates relative RMS sound energy to compute the perfect noise threshold decibel value in FFmpeg `silencedetect` for jump-cuts. |
| 🚀 **Hardware GPU Acceleration** | Automatic startup probes to prioritize NVENC, AMF, or QSV GPU rendering with quality rate parameters matching libx264 CRF 16 parity. |
| 💾 **Drive Auto-Detect** | Launcher auto-detects Drive native browser mount or defaults to ephemeral storage without Python popup authorization popups. |

---

## 🚀 Quick Start (Google Colab)

1. Open `colab_launcher.ipynb` in Google Colab.
2. Set Runtime to **T4 GPU** (Runtime > Change runtime type > T4 GPU).
3. **CELL 0 (Drive Mount)**: Mount Google Drive securely inside the Colab browser UI (click the Folder icon on the far left, then click the Google Drive logo) to avoid python authorization popup prompts. 
4. **CELL 1 (Setup)**: Click to execute. Installs JS runtime, Montserrat fonts, Python dependencies, and builds the static Next.js export (~3 min).
5. **CELL 2 (Launch)**: Starts the backend and dashboard, maps the ngrok tunnel automatically using a fresh burner token, and prints your dashboard URL.
6. Open the printed **Dashboard URL** and start clipping!

---

## 🛠️ Architecture

```
server/
  main.py                       ← FastAPI backend (WebSocket logging, Media serving, GPU probes)
frontend/
  src/app/page.tsx              ← Next.js Dashboard UI (Workspace + Netflix Gallery)
shorts_generator/
  highlights.py                 ← Three-pass extraction, persona detection, sub-scores
  clipper.py                    ← FFmpeg engine (1:1 crop, ASS dynamic subtitles, SFX, BGM)
  enhancer.py                   ← royalty-free background music sidechain swelling
  audio_analyzer.py             ← Librosa-based RMS sound energy extraction
  config.py                     ← Global paths and model catalogs
```

---

## ⚠️ Requirements

- **Python 3.9+** (Fully compatible with Python 3.9.5)
- **Node.js 20+** (for building the dashboard)
- **FFmpeg** (installed by default in Colab)
- **ngrok burner token** (hardcoded in launcher, zero-setup required)

---

## 🤝 Acknowledgements

Designed for creators who need high-volume, professional-grade output without the monthly SaaS subscription fees. Built with ❤️ using Next.js, FastAPI, Llama 3, Whisper, and Gemini.
