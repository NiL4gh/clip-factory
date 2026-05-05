# Clip Factory — SaaS Video Director

> Turn long-form YouTube videos into viral 9:16 Shorts, Reels & TikToks — **Free, Local AI, no watermarks, no credits.**

Clip Factory is a production-grade, self-hosted SaaS platform designed to automate the video repurposing pipeline. It uses a dual-server architecture with a **FastAPI** backend and a premium **Next.js** dashboard.

---

## ✨ Features

| Feature | Description |
|---|---|
| 🧠 **AI Video Intelligence** | Llama 3 8B auto-detects video persona, genre, and tone to assign perfect Brand Kits and BGM. |
| 📊 **Strategize-as-Generate** | AI Director scans transcripts to find the 3-5 best viral angles, scoring them by Hook, Body, and Payoff. |
| 📝 **Transcript Editor** | Interactive word-processor UI — click to strike-through/cut any sentence from the final render. |
| 🎞️ **Netflix-style Gallery** | Dedicated library view for all rendered clips with hover-to-play video previews and downloads. |
| 🎨 **Production Brand Kits** | Automated styling modeled after *Hormozi*, *Ali Abdaal*, and *MrBeast* (Montserrat Black typography). |
| ✂️ **AI Stitched Stories** | Cross-timestamp narrative stitching — the AI can merge separate moments into one cohesive story. |
| 🎯 **Auto Face Framing** | OpenCV-based framing dynamically centers the 9:16 crop on the active speaker. |
| 🖼️ **Dynamic B-Roll** | Visual keyword extraction → DDG fetch → Ken Burns animated overlays. |
| 💾 **Drive Persistence** | Full project caching (transcripts, strategies, renders) via Google Drive. |

---

## 🚀 Quick Start (Google Colab)

1. Open `colab_launcher.ipynb` in Google Colab.
2. Set Runtime to **T4 GPU**.
3. **Cell 1 (Setup)**: Installs Python deps, Node.js, and builds the Next.js static dashboard (~4 min).
4. **Cell 2 (Launch)**: 
   - Starts the FastAPI backend (Port 8000).
   - Starts the Dashboard server (Port 3000).
   - Prompts for your **ngrok auth token** to create public tunnels.
5. Open the **Dashboard URL** provided in the output.

---

## 🛠️ Architecture

```
server/
  main.py                       ← FastAPI backend (WebSocket logging, Media serving)
frontend/
  src/app/page.tsx              ← Next.js Dashboard UI (Workspace + Gallery)
shorts_generator/
  highlights.py                 ← Llama 3 Strategic extraction & persona detection
  clipper.py                    ← FFmpeg engine (Crop, Captions, B-Roll, SFX)
  transcriber.py                ← faster-whisper transcription engine
  config.py                     ← Global paths and model catalogs
```

---

## ⚠️ Requirements

- **Python 3.10+**
- **Node.js 20+** (for building the dashboard)
- **FFmpeg** (installed by default in Colab)
- **ngrok account** (for remote access to the local/Colab UI)

---

## 🤝 Acknowledgements

Designed for creators who need high-volume, professional-grade output without the monthly SaaS subscription fees. Built with ❤️ using Next.js, FastAPI, Llama 3, and Whisper.
