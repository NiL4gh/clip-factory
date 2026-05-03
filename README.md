# Clip Factory

A fully automated, local-first AI YouTube Shorts generator designed for high-volume clipping (perfect for Whop Content Rewards and similar programs).

Built to run entirely inside a Google Colab T4 GPU instance, it uses open-source LLMs and Whisper to find viral moments and render them into vertical short-form content.

## Features

- **Whop-Ready Clip Durations:** Automatically detects hooks and extracts 15-60 second clips, the optimal length for TikTok, Reels, and Shorts algorithms.
- **Smart Caching:** Never waste time re-processing. Transcripts and highlights are cached to your Google Drive. If you reconnect or reload a video, it skips straight to the results.
- **Opus Clip-style UI:** A professional, dark-mode, card-based interface.
- **Enhancements:** Add background music and custom watermarks directly from the UI before rendering.
- **AI Auto-Framing:** Detects faces and keeps the subject centered in the 9:16 vertical frame.
- **Dynamic Captions:** Burns Hormozi-style highlighted captions into the video.

## How to Run in Google Colab

1. Create a new Google Colab notebook.
2. Go to **Runtime > Change runtime type** and select **T4 GPU**.
3. Create a cell with the following code and run it:

```python
import os, sys, subprocess

REPO_DIR = '/content/AI-Shorts-Generator-opus'

# Clone if it doesn't exist
if not os.path.exists(REPO_DIR):
    subprocess.run(['git', 'clone', 'https://github.com/NiL4gh/AI-Shorts-Generator-opus.git', REPO_DIR], check=True)

os.chdir(REPO_DIR)

# Pull latest fixes
subprocess.run(['git', 'pull'], check=True)

# Run setup (mounts Drive, installs dependencies, compiles llama-cpp-python)
subprocess.run(['bash', 'setup.sh'], check=True)
```

4. Create a second cell to launch the UI:

```python
import os, sys
REPO_DIR = '/content/AI-Shorts-Generator-opus'
os.chdir(REPO_DIR)
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

# Launch the Gradio app
exec(open('app.py').read())
```

Click the public Gradio link that appears to open your Clip Factory dashboard.

## Folder Structure (Google Drive)

When run in Colab, the app mounts your Google Drive to save data between sessions.

```
/content/drive/MyDrive/clip_factory/
├── models/             # Cached LLM and Whisper models (~4GB, only downloads once)
├── projects/           # Cached transcripts and highlights for each video processed
└── output/             # Your final rendered MP4 clips
```
