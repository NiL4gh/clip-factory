"""Pillow-rendered header / magic-hook overlays (transparent PNGs).

Replaces the old ASS-drawn header so we get real design (cards, bars, scrims)
and never hit libass font-name fallback (Pillow loads the .ttf file directly).
"""
from PIL import Image, ImageDraw, ImageFont

ZONE_W = 1080          # top-zone width  (clipper LAYOUT_VIDEO_SIZE)
ZONE_H = 320           # top-zone height (clipper LAYOUT_TOP_ZONE_H)
SAFE_W = 960           # horizontal safe width (keeps text off the edges / UI)
MAX_FONT = 110
MIN_FONT = 44

def fit_lines(draw, text, font_path, max_w=SAFE_W, max_h=240, max_lines=2,
              stroke=12, max_font_size=MAX_FONT):
    """Return (lines, font) that fit text into max_w x max_h in <= max_lines,
    shrinking the font until it fits. All-caps, greedy word wrap."""
    text = " ".join(text.upper().split())
    words = text.split(" ")
    for size in range(min(max_font_size, MAX_FONT), MIN_FONT - 1, -2):
        font = ImageFont.truetype(font_path, size)
        lines, cur = [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            tw = draw.textbbox((0, 0), trial, font=font, stroke_width=stroke)[2]
            if tw <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur); cur = w
        if cur:
            lines.append(cur)
        # check fit
        if len(lines) <= max_lines:
            widest = max(draw.textbbox((0, 0), ln, font=font, stroke_width=stroke)[2] for ln in lines)
            line_h = font.size + 14
            if widest <= max_w and line_h * len(lines) <= max_h:
                return lines, font
    # smallest font fallback
    font = ImageFont.truetype(font_path, MIN_FONT)
    return ([text] if len(words) == 1 else [" ".join(words[:len(words)//2]),
            " ".join(words[len(words)//2:])]), font


# colors are RGB tuples
HEADER_PRESETS = {
    # white rounded card, dark text, red keyword — default, readable on any bg
    "card":   {"container": "card",  "card_fill": (255, 255, 255),
               "text": (17, 17, 17), "keyword": (214, 38, 38), "stroke": 0},
    # no box, white text + thick black stroke + faint top scrim, yellow keyword
    "stroke": {"container": "scrim", "text": (255, 255, 255),
               "keyword": (255, 209, 0), "stroke": 12},
}

# trigger words worth accenting (mirrors clipper._is_header_highlight_target intent)
_TRIGGERS = {"SECRET", "SECRETS", "MISTAKE", "SHOCKING", "TRUTH", "LIE", "LIES",
             "MONEY", "CRAZY", "INSANE", "NEVER", "ALWAYS", "FIRE", "DANGER",
             "DEAD", "DEADLY", "RICH", "POOR", "FREE", "FAST", "HUGE", "ONLY"}

def pick_keyword(words):
    """Index of the word to accent: first trigger word, else the last word."""
    clean = ["".join(c for c in w if c.isalnum()).upper() for w in words]
    for i, c in enumerate(clean):
        if c in _TRIGGERS or any(ch.isdigit() for ch in c):
            return i
    return len(words) - 1 if words else None


def _draw_centered(draw, lines, font, cx, top_y, fill, keyword_idx, keyword_fill,
                   stroke=0, stroke_fill=(0, 0, 0)):
    line_h = font.size + 14
    idx = 0
    y = top_y
    for ln in lines:
        words = ln.split(" ")
        widths = [draw.textbbox((0, 0), w, font=font, stroke_width=stroke)[2] for w in words]
        space = draw.textbbox((0, 0), " ", font=font, stroke_width=stroke)[2]
        total = sum(widths) + space * (len(words) - 1)
        x = cx - total / 2
        for w, wdt in zip(words, widths):
            col = keyword_fill if idx == keyword_idx else fill
            draw.text((x, y), w, font=font, fill=col, stroke_width=stroke, stroke_fill=stroke_fill)
            x += wdt + space
            idx += 1
        y += line_h

def render_overlay_png(text, preset="card", font_path=None, width=ZONE_W,
                       height=ZONE_H, out_path="overlay.png",
                       max_font_size=MAX_FONT, opacity=1.0):
    """Render a transparent PNG of the header/hook in the given preset.
    opacity: 0.0–1.0, applied to the whole layer (use <1.0 for the magic hook)."""
    spec = HEADER_PRESETS.get(preset, HEADER_PRESETS["card"])
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    stroke = spec.get("stroke", 0)
    lines, font = fit_lines(d, text, font_path, max_w=SAFE_W, max_h=height - 80,
                            stroke=stroke, max_font_size=max_font_size)
    kw = pick_keyword(" ".join(lines).split(" "))
    block_h = (font.size + 14) * len(lines)
    cx = width // 2

    if spec["container"] == "card":
        pad_x, pad_y = 48, 28
        widest = max(d.textbbox((0, 0), ln, font=font)[2] for ln in lines)
        cw = min(width - 40, widest + pad_x * 2)
        ch = block_h + pad_y * 2
        x0 = cx - cw / 2; y0 = (height - ch) / 2
        d.rounded_rectangle([x0, y0, x0 + cw, y0 + ch], radius=34, fill=spec["card_fill"])
        _draw_centered(d, lines, font, cx, y0 + pad_y, spec["text"], kw, spec["keyword"])
    else:  # scrim (stroke style): faint dark fade behind text for legibility
        scrim = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        sd = ImageDraw.Draw(scrim)
        for yy in range(height):
            a = int(150 * max(0, 1 - yy / height))   # darkest at top, fades down
            sd.line([(0, yy), (width, yy)], fill=(0, 0, 0, a))
        img = Image.alpha_composite(img, scrim)
        d = ImageDraw.Draw(img)
        _draw_centered(d, lines, font, cx, (height - block_h) / 2, spec["text"], kw,
                       spec["keyword"], stroke=stroke, stroke_fill=(0, 0, 0))

    if opacity < 1.0:
        r, g, b, a = img.split()
        a = a.point(lambda x: int(x * opacity))
        img = Image.merge("RGBA", (r, g, b, a))
    img.save(out_path)
    return out_path
