"""Render every header preset onto real frames so the owner approves the LOOK
before any Colab run. Usage:
  python scripts/preview_headers.py <frame1.png> [frame2.png ...]
Writes <frame>_<preset>.png next to each input and prints the paths.
"""
import sys, os
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shorts_generator import overlays

FONT = os.path.join(os.path.dirname(__file__), "..", "shorts_generator", "assets", "BebasNeue-Regular.ttf")
SAMPLES = {
    "card":   "PARENTS ARE CRAZY",
    "stroke": "YOUR FRIEND'S FIRE IS OUT OF CONTROL",
    "bar":    "RCMP CALL",
}

def main(frames):
    for f in frames:
        base = Image.open(f).convert("RGBA")
        for preset, text in SAMPLES.items():
            ov_path = os.path.join(os.path.dirname(f), f"_ov_{preset}.png")
            overlays.render_overlay_png(text, preset, FONT, out_path=ov_path)
            comp = base.copy()
            comp.alpha_composite(Image.open(ov_path), (0, 0))
            out = f.rsplit(".", 1)[0] + f"_{preset}.png"
            comp.convert("RGB").save(out)
            print(out)

if __name__ == "__main__":
    main(sys.argv[1:])
