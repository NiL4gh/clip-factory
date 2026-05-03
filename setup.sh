#!/bin/bash
set -e

echo "=> Setting up Clip Factory v2 environment..."

pip install -q yt-dlp faster-whisper gradio ffmpeg-python opencv-python-headless
pip install -q duckduckgo-search

if ! python -c "import llama_cpp" &> /dev/null; then
    echo "=> Installing llama-cpp-python with CUDA support..."
    CMAKE_ARGS="-DGGML_CUDA=on" FORCE_CMAKE=1 pip install -q llama-cpp-python --no-cache-dir
fi

echo "=> Setup complete. Run 'python app.py'."
