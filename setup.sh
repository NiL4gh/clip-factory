#!/usr/bin/env bash
# ============================================================
# setup.sh — One-command installer for Colab (T4 GPU)
# Run once per session: bash setup.sh
# ============================================================
set -e

echo "[1/4] Installing system dependencies..."
apt-get install -qq ffmpeg > /dev/null 2>&1

echo "[2/4] Installing Python packages..."
pip install -q \
    requests>=2.31 \
    python-dotenv>=1.0 \
    "yt-dlp>=2024.1.0" \
    "huggingface-hub>=0.20" \
    "gradio>=4.0" \
    "opencv-python-headless>=4.8" \
    "moviepy>=1.0.3" \
    "faster-whisper>=1.0"

echo "[3/4] Installing llama-cpp-python with CUDA 12.1 support..."
pip install -q \
    "llama-cpp-python==0.2.90" \
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121

echo "[4/4] Verifying GPU..."
python - <<'EOF'
import torch
if torch.cuda.is_available():
    name = torch.cuda.get_device_name(0)
    vram = torch.cuda.get_device_properties(0).total_memory / 1e9
    print(f"  GPU  : {name}")
    print(f"  VRAM : {vram:.1f} GB")
else:
    print("  WARNING: No GPU detected. Go to Runtime > Change runtime type > T4 GPU")
EOF

echo ""
echo "Setup complete. Run the next cell to launch the app."
