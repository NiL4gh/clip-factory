import json
import os

with open('colab_launcher.ipynb', 'r', encoding='utf-8') as f:
    nb = json.load(f)

# --- Cell 0: Header (v2.0.0) ---
nb['cells'][0]['source'] = [
    "# 🧠 ClipFactory AI Director — v2.0.0-PRO-STRATEGY\n",
    "> **VERIFIED BUILD:** Topic-based extraction, Deno-hardened, Montserrat pre-cached.\n",
    "\n",
    "**Runtime:** Make sure you're on **T4 GPU** (Runtime > Change runtime type > T4 GPU).\n",
    "\n",
    "### Why can't I see changes?\n",
    "1. **Browser Cache:** Your browser may have cached the old dashboard. **Press Ctrl+F5** on the Dashboard URL.\n",
    "2. **Old Projects:** If using the same URL, old results might be loaded. Use the 'Reset' button in the UI.\n",
    "3. **Ghost Processes:** This launcher now force-kills ghost Python processes on every launch.\n"
]

# --- Cell 2: Setup (Force Clean) ---
source2 = nb['cells'][2]['source']
# Add a line to clear cache if needed
# Finding the git pull part
for i, line in enumerate(source2):
    if 'git reset --hard' in line:
        source2.insert(i+1, "    !rm -rf /content/clip_factory/projects/* # FORCE: Clear old project cache\n")
        break
nb['cells'][2]['source'] = source2

# --- Cell 3: Launch (Force Kill) ---
source3 = nb['cells'][3]['source']
# Add force kill at start
new_launch_start = [
    "# ─── CELL 2: Launch ClipFactory.ai ─────────────────────────────────────────────\n",
    "!pkill -9 python\n",
    "!pkill -9 uvicorn\n",
    "!pkill -9 ngrok\n",
    "import time\n",
    "time.sleep(2)\n"
]
# Replace the first few lines
source3[0:5] = new_launch_start
nb['cells'][3]['source'] = source3

with open('colab_launcher.ipynb', 'w', encoding='utf-8') as f:
    json.dump(nb, f, indent=1, ensure_ascii=False)

print('SUCCESS: Hard-reset logic injected into colab_launcher.ipynb.')
