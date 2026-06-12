# ClipFactory.ai

Turn long-form YouTube videos (podcasts, interviews, debates) into vertical 9:16 short-form
clips for TikTok, Reels, and YouTube Shorts. It downloads a video, transcribes it, finds the most
engaging moments with an LLM, and renders captioned clips — designed to run on **Google Colab**
with a GPU.

> **Status:** personal single-operator tool, actively being stabilized. It is not a polished SaaS;
> expect rough edges. The honest, code-verified status notes live in the project's context folder
> (`AUDIT.md`), not in this repo.

---

## How it works (pipeline)

1. **Download** — `yt-dlp` pulls the source video (uses `cookies.txt` for authenticated access).
2. **Transcribe** — `faster-whisper` produces word-level timestamps.
3. **Energy analysis** — `librosa` finds high-energy audio peaks (laughter, excitement).
4. **Extract (3 passes)** — an LLM detects persona → topics → clips. Uses **Google Gemini** by
   default and automatically **falls back to a local LLM** (LLaMA via `llama-cpp-python`) when no
   API key is set. Other providers (Groq, OpenRouter, GLM, Ollama) are supported as fallbacks.
5. **Render** — `ffmpeg` center-crops to a 1:1 frame on a styled background, burns in ASS captions
   and a hook header, removes dead-air silences, and mixes optional royalty-free background music.

The frontend is a **Next.js dashboard** exported as static files and served by the FastAPI backend.

---

## Quick start (Google Colab)

1. Open **`colab_launcher.ipynb`** in Google Colab.
2. Set the runtime to a **GPU** (Runtime → Change runtime type → T4 GPU).
3. **Cell 0** — mount Google Drive (for persistent models/projects).
4. **Cell 1** — setup: installs Node + Deno, clones this repo (`main` branch), downloads fonts,
   installs Python deps and `llama-cpp-python`, and builds the dashboard (~3 min).
5. **Cell 2** — launch: starts the FastAPI backend and opens a public **Localtunnel** URL.
6. Open the printed **Dashboard URL** and paste a YouTube link.

**API keys are optional.** Add `GEMINI_API_KEY` (or others) as a Colab Secret or in Cell 2 for the
best extraction quality; otherwise the local LLM is used.

---

## Project structure

```
clip-factory/
├── colab_launcher.ipynb     # Entry point: sets up and launches the app on Colab
├── requirements.txt         # Python dependencies (ffmpeg is a system dep, not pip)
├── .env.example             # Copy to .env; all vars optional
├── cookies.txt              # YouTube cookies for yt-dlp (throwaway account)
│
├── server/
│   └── main.py              # FastAPI backend: API routes, WebSocket logs, serves frontend
│
├── shorts_generator/        # The pipeline (imported by server/main.py)
│   ├── config.py            # Paths, model catalog, font map
│   ├── downloader.py        # yt-dlp video/subtitle download
│   ├── transcriber.py       # faster-whisper transcription
│   ├── audio_analyzer.py    # librosa RMS energy peaks
│   ├── highlights.py        # 3-pass LLM extraction (persona → topics → clips)
│   ├── clipper.py           # ffmpeg render: crop, captions, silence removal
│   ├── enhancer.py          # background-music mixing
│   ├── music_fetcher.py     # royalty-free BGM fetch
│   ├── media.py             # optional B-roll image fetch
│   ├── cache.py             # per-video JSON cache
│   └── logger.py            # WebSocket + file logging
│
└── frontend/                # Next.js dashboard (static export -> served by FastAPI)
    └── src/app/page.tsx     # Main dashboard UI
```

---

## Requirements

- **Python 3.9+**
- **Node.js 20+** (to build the dashboard)
- **ffmpeg** (pre-installed on Colab; required for all rendering)
- A **GPU** is strongly recommended (Whisper + local LLM + encoding are slow on CPU)

## Local development (not the primary path)

The app targets Colab, but you can import-check it locally:

```bash
cd clip-factory
pip install -r requirements.txt        # heavy GPU deps may be skipped locally
cd frontend && npm install && npm run build   # builds the dashboard
cd .. && uvicorn server.main:app --port 8000  # starts the backend
```

---

## Configuration

Copy `.env.example` to `.env` and fill in any LLM API keys you have (all optional). See that file
for the full list. On Colab, prefer Colab Secrets — the launcher wires `GEMINI_API_KEY` into `.env`
for you.
