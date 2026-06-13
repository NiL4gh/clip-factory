# Round 1 — "The Look" (header / fonts / background / magic hook)

*Design spec. Date: 2026-06-13. Branch: `feature/round1-look`.*
*Owner-approved direction. Implementation plan to follow.*

## Why
The 2026-06-13 test run (`X0ZvX_Sm0cI`, clips in `Downloads/clipfactory_project_clips`) rendered
successfully, but the owner's verdict: the **header is invisible and amateur**, **one font was broken**
(fell back to an ugly default on the "RCMP CALL" clip), the **background control disappeared**, and the
**font picker is one dropdown for all three text elements**. The **caption is good and must not change.**

Verified by inspecting the actual rendered frames (cv2 frame-grabs) and the render code:
- Header is drawn through the same libass/ASS engine as captions → no real design (no cards/bars), and
  libass resolves fonts by **family name**, silently substituting a default when the name doesn't match
  → that is the "broken font."
- `_build_layout_filtergraph` (clipper.py) still supports `black/white/blur/gradient/brand` backgrounds;
  the UI control was removed in the last panel cleanup, so everything defaults to black bars.

## Goal
Make a clip's **header** look like a designed, professional title — switchable per clip — while keeping
the caption exactly as-is. Fix fonts, restore background control, and give the magic hook a matching look.

## The core architectural decision
**Render the header and the magic hook as a transparent PNG image layer composited over the video**
(generated with Pillow, which is already a dependency), instead of drawing them with ASS/libass.

Captions **stay in the ASS pipeline** (word-by-word highlight depends on it; the owner likes it).

Why this approach:
1. **Real design** — rounded cards, full-width bars, exact keyword colors, precise contrast. ASS cannot
   do rounded boxes; PNG overlay can.
2. **Permanently fixes the broken-font bug for the header** — Pillow loads the `.ttf` file directly; there
   is no name-resolution step to fail.
3. **Cheap** — the header is static for its display window, so it's one PNG per clip looped as an ffmpeg
   input, not per-word animation.

Tradeoff considered and rejected: keeping the header in ASS (simpler, no new module) — rejected because it
cannot produce the designed look the owner asked for and keeps the font fragility.

## Components

### 1. New module: `shorts_generator/overlays.py`
Pure-Pillow, no ffmpeg, independently testable.

```
render_header_png(text: str, preset: str, font_path: str, video_w: int,
                  out_path: str, keyword: str | None = None) -> str
render_hook_png(text: str, preset: str, font_path: str, video_w: int,
                out_path: str) -> str   # may share impl with header
```
- All-caps. **Auto-fit:** wrap to a **max of 2 lines** and shrink the font size until the text fits the
  top zone width — so long titles/hooks are never cut off (the test run chopped "...OUT OF CONTROL" to
  "CONTRO") and never spill onto faces.
- **Safe zones:** keep the text within horizontal safe margins and clear of the top-right corner (where
  TikTok/Reels overlay the profile + action buttons).
- Auto-detects the keyword to accent (reuse the existing `_is_header_highlight_target` trigger-word logic,
  or last salient word) and colors it per preset.
- Renders onto a transparent RGBA canvas sized `video_w` × (top zone height), returns the PNG path.
- Loads the font straight from `font_path` (no name lookup), which is *why* the header can never hit the
  broken-font fallback.

### 2. Header presets (data, in `overlays.py`)
A dict; each preset fully specifies the look. Initial set:

| Preset  | Container                    | Text fill | Keyword     | Notes |
|---------|------------------------------|-----------|-------------|-------|
| `card`  | white rounded rect, ~64px margin | near-black (#111) | red (#D62626) | **default** — readable on any bg |
| `stroke`| **faint dark top scrim** (gradient) | white | yellow (#FFD100) | thick black stroke (~14px); scrim guarantees legibility on bright/busy shots |
| `bar`   | full-width accent bar (#FFC400) | near-black | (same as fill) | loud / broadcast |

Font weight: heavy/display (Bebas Neue, Montserrat Black, or Impact-class). Default header font = Bebas Neue
(already shipped) unless owner picks another.

Each preset also ships a **baked-in example thumbnail PNG** (generated once) for the UI picker — see §5.

### 3. `clipper.py` composition changes
- Generate `header.png` (from `clip_data["title"]`) and, for `idx == 0` with magic hook on, `hook.png`
  (from `clip_data["hook_text"]`).
- **The magic hook is a first-class element, not an afterthought.** Confirmed from the test run: the big
  top text for the first ~2–3s *is* the hook (e.g. "PARENTS ARE CRAZY"), i.e. the **opening frame** — the
  most important frame for stopping the scroll. It gets the **same design quality** as the header (same
  presets, auto-fit, scrim, safe zones).
- Add each as `-loop 1 -t <clip_duration> -i <png>` and `overlay` at the top zone with `enable=` timing:
  - Preserve current timing rules: if hook shows 3s/5s, header starts after (3.5s/5.5s); if hook is "full",
    header is hidden; otherwise header shows the whole clip.
- **Stop emitting the `Header` style + dialogue (and the `MagicHook` style + dialogue) from `_generate_ass`.**
  Keep `Main`/`Highlight` caption styles unchanged.

### 4. Caption font fix (still ASS)
Make libass always use the chosen caption font:
- Set the ASS `Fontname` to the font's **actual internal family name**, read at runtime via
  `PIL.ImageFont.truetype(path).getname()[0]`, instead of the hand-maintained `get_font_family` map.
- Keep passing `fontsdir`. Add the missing `'montserrat black'` (space) key parity in the lookup.

### 5. Fonts split (frontend `page.tsx` + backend already supports it)
Backend already accepts separate `header_font` / `caption_font` / `hook_font`. Change the UI:
- **Header**: a "Header Style" picker (card/stroke/bar) that shows a **baked-in example thumbnail next to
  each option** (owner's choice — picks by sight, no render wait) **+** a "Header Font" dropdown (expressive set).
- **Caption font**: dropdown limited to the readable set (Montserrat / Poppins / Roboto).
- **Hook**: uses the same font as the caption (no separate picker). Keep it simple.

### 6. Background control (frontend `page.tsx`)
Re-add a visible "Background" control sending `bg_style` ∈ {`black`, `white`, `blur`, `gradient`, `brand`}.
Backend path already exists (`_build_layout_filtergraph`); no backend change expected.

## Future hooks (noted, not built now — YAGNI)
- Per-campaign **brand color / creator handle / logo** on the header — useful later for Whop clipping.
- Additional header presets — trivial to add once the first 3 are proven on real renders.

## Out of scope (parked, logged in BACKLOG)
- Double-ZIP on "download session zip" (clip-only + clip+transcript) — bug round.
- Full app walkthrough / audit — separate track after this ships.
- Clip-strategy quality (fake sub-scores, energy=0, repeat hooks — BACKLOG #25–29) — Round 2.
- Progress bar still missing, video sharpness, confusing Drive folders — bug round.

## Testing / verification (honesty mandate)
- **Local, before Colab — owner sign-off gate:** generate a **contact sheet** of every preset × a couple of
  the owner's real frames and show it to the owner. The owner approves the *look* with **zero GPU time spent**
  before anything is wired into the app (the PNG *is* exactly what gets composited).
- **Local:** `py_compile` clipper.py + overlays.py; `next build` for the frontend.
- **Colab (owner run):** confirm a real clip shows the designed header, the chosen background, split fonts,
  and no font fallback. Only then mark Verified in STATUS/BACKLOG. Do **not** write "works" before this.

## Success criteria
1. Header is clearly legible on a dark background and reads as a designed title (not bare text).
2. Header style is switchable per clip; default = `card`.
3. No clip ever falls back to the default ugly font (header or caption).
4. Background control is visible and changes the rendered background.
5. Header font is independent; caption/hook use the readable set.
6. Caption rendering is unchanged from the version the owner already approved.
7. Header/hook text is never cut off and never covers a face or the platform UI corners.
8. The magic hook (opening 2–3s) is designed to the same standard as the header.
