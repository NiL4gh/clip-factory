#!/usr/bin/env bash
set -e

echo "========================================"
echo "  Clip Factory — Setup"
echo "========================================"

# 1. Mount Google Drive
echo "[1/5] Mounting Google Drive..."
python3 -c "
try:
    from google.colab import drive
    drive.mount('/content/drive', force_remount=False)
    print('  Drive mounted.')
except Exception as e:
    print(f'  Drive not available: {e}')
"

# 2. System deps
echo "[2/5] System packages..."
apt-get install -qq ffmpeg > /dev/null 2>&1 || true

# 3. Python deps
echo "[3/5] Python packages..."
pip install -q \
    requests>=2.31 \
    python-dotenv>=1.0 \
    "yt-dlp>=2024.1.0" \
    "huggingface-hub>=0.20" \
    "gradio>=4.0" \
    "opencv-python-headless>=4.8" \
    "moviepy>=1.0.3" \
    "faster-whisper>=1.0"

# 4. llama-cpp-python with CUDA
echo "[4/5] llama-cpp-python (CUDA)..."
pip install -q \
    "llama-cpp-python==0.2.90" \
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121 2>/dev/null || \
pip install -q llama-cpp-python

# 5. Verify
echo "[5/5] Verifying GPU..."
python3 -c "
import torch
if torch.cuda.is_available():
    n = torch.cuda.get_device_name(0)
    v = torch.cuda.get_device_properties(0).total_memory / 1e9
    print(f'  GPU: {n} ({v:.1f} GB VRAM)')
else:
    print('  WARNING: No GPU. Go to Runtime > Change runtime type > T4 GPU')
"

# Check if models already exist in Drive
DRIVE_LLM="/content/drive/MyDrive/clip_factory/models/llm"
if [ -d "$DRIVE_LLM" ] && [ "$(ls -A $DRIVE_LLM 2>/dev/null)" ]; then
    echo "  Models found in Drive (will skip download)."
else
    echo "  No cached models. First run will download (~4 GB)."
fi

echo ""
echo "Setup complete. Run the next cell to launch."
