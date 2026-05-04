#!/bin/bash
set -e

echo "=> Setting up ClipFactory.ai environment..."

pip install -q yt-dlp faster-whisper gradio opencv-python-headless
pip install -q duckduckgo-search python-dotenv huggingface-hub torch requests

# Install llama-cpp-python with CUDA if available
if ! python -c "import llama_cpp" &> /dev/null; then
    echo "=> Installing llama-cpp-python with CUDA support..."
    pip install llama-cpp-python --prefer-binary --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124 2>/dev/null \
        || CMAKE_ARGS="-DGGML_CUDA=on" FORCE_CMAKE=1 pip install -q llama-cpp-python --no-cache-dir
fi

# Install Deno for yt-dlp JS challenge solver (fixes YouTube bot-check)
if ! command -v deno &> /dev/null; then
    echo "=> Installing Deno for YouTube challenge solver..."
    curl -fsSL https://deno.land/install.sh | sh
    export PATH="$HOME/.deno/bin:$PATH"
fi

# Install fonts for captions
apt-get install -q -y fonts-liberation 2>/dev/null || true

echo "=> Setup complete. Run 'python app.py' to launch."
