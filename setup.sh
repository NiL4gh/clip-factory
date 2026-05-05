#!/bin/bash
set -e

echo "=> Setting up ClipFactory.ai SaaS Environment..."

# Install core dependencies
pip install -q yt-dlp faster_whisper fastapi uvicorn opencv-python-headless
pip install -q duckduckgo-search python-dotenv huggingface-hub torch requests pyngrok

# Install llama-cpp-python with CUDA if available
if ! python -c "import llama_cpp" &> /dev/null; then
    echo "=> Installing llama-cpp-python with CUDA support..."
    pip install llama-cpp-python --prefer-binary --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124 2>/dev/null \
        || CMAKE_ARGS="-DGGML_CUDA=on" FORCE_CMAKE=1 pip install -q llama-cpp-python --no-cache-dir
fi

# Install Deno for yt-dlp JS challenge solver
if ! command -v deno &> /dev/null; then
    echo "=> Installing Deno for YouTube challenge solver..."
    curl -fsSL https://deno.land/install.sh | sh
    export PATH="$HOME/.deno/bin:$PATH"
fi

# Install fonts for captions
apt-get install -q -y fonts-liberation 2>/dev/null || true

# Setup frontend
echo "=> Preparing Next.js Dashboard..."
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -q && apt-get install -y -q nodejs 2>/dev/null
cd frontend && npm install --legacy-peer-deps 2>/dev/null && npm run build

echo ""
echo "=> Setup complete."
echo "=> 1. Start Backend:  python -m uvicorn server.main:app --port 8000"
echo "=> 2. Serve Frontend: cd frontend/out && python3 -m http.server 3000"
