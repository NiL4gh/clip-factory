# Premium Visual Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the rendered clips from "MVP" to "premium" by sharpening the image, pulling higher-resolution source, fixing the magic-hook opacity bug, making the hook fade in/out, and widening the header to a short curiosity line — without making the header or hook visually overwhelming.

**Architecture:** Five surgical edits across four files. Two are pure-Python (Pillow overlay rendering) and are verified locally with `pytest`. Three are FFmpeg/yt-dlp string changes that can only be verified on a real Colab GPU run — each has an explicit Colab verification step instead of a unit test. No core pipeline is rewritten; no B-roll/transitions are added (paused on purpose per `CLAUDE.md` rule #3); captions are left unchanged (owner deliberately chose the lighter Montserrat SemiBold on 2026-06-15).

**Tech Stack:** Python 3.9, Pillow (PIL), FFmpeg filtergraph, yt-dlp, pytest.

---

## Owner decisions baked into this plan (do not re-litigate)
- **Captions:** UNCHANGED. Stay Montserrat SemiBold. The audit's "go heavier/Black" was rejected — it reverses the owner's 2026-06-15 fix.
- **Source resolution cap:** **1440p**, not 4K. Chosen over 4K because the owner is fighting Colab disconnects/timeouts and 4K downloads are multi-GB/slow. If a future run shows 1440p is still soft on the full-bleed 9:16 layout, the one-line bump to 4K is noted in Task 5.
- **Header length:** widen to **5-8 words**, BUT render it compact (lower max font, modest floor) so it reads as a quiet curiosity line, not a giant tag.
- **"Not overwhelming" constraint:** header max font drops 90 → 80 with a 48px floor; hook keeps its 72px cap, stays background-only 50% transparent, and now fades in/out so it is transient.

## Files touched
- `clip-factory/shorts_generator/overlays.py` — add `min_font_size` param to `fit_lines`/`render_overlay_png`; fix opacity to apply to background only (Tasks 2, 3).
- `clip-factory/shorts_generator/clipper.py` — header render call (compact); hook render call + fade in/out; `unsharp` in the layout filtergraph (Tasks 4, 5, 6).
- `clip-factory/shorts_generator/downloader.py` — 1080 → 1440 source cap (Task 7).
- `clip-factory/shorts_generator/highlights.py` — header schema 2-5 → 5-8 words (Task 8).
- `clip-factory/tests/test_overlays.py` — fix stale `bar` assertions; add opacity + min-font tests (Tasks 1, 2, 3).

## How to run the tests
From `clip-factory/`:
```bash
pytest tests/test_overlays.py -v
```
The FFmpeg/yt-dlp tasks (4 source-side, 5, 7) have NO local test — they are verified on the next Colab run using the checklist in "Colab verification" at the bottom.

---

## Task 1: Fix the stale `bar` test (get a green baseline)

The `bar` preset was removed on 2026-06-14, but `tests/test_overlays.py` still asserts it exists, so the suite is currently red. Fix it before adding new tests.

**Files:**
- Modify: `clip-factory/tests/test_overlays.py:29` and `:44`

- [ ] **Step 1: Run the suite to confirm the red baseline**

Run: `pytest tests/test_overlays.py -v`
Expected: `test_presets_exist` FAILS (asserts `{"card","stroke","bar"}` but code has only `{"card","stroke"}`).

- [ ] **Step 2: Update the preset assertion**

In `tests/test_overlays.py`, change line 29 from:
```python
    assert set(overlays.HEADER_PRESETS) == {"card", "stroke", "bar"}
```
to:
```python
    assert set(overlays.HEADER_PRESETS) == {"card", "stroke"}
```

- [ ] **Step 3: Update the parametrize list**

Change line 44 from:
```python
@pytest.mark.parametrize("preset", ["card", "stroke", "bar"])
```
to:
```python
@pytest.mark.parametrize("preset", ["card", "stroke"])
```

- [ ] **Step 4: Run the suite to confirm green**

Run: `pytest tests/test_overlays.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_overlays.py
git commit -m "test: align overlay tests with card/stroke presets (bar removed)"
```

---

## Task 2: Add a `min_font_size` floor to `fit_lines`

So the header can be told "never shrink below 48px" while the hook keeps the default 44px. This is the readability floor that keeps a 5-8 word header legible.

**Files:**
- Modify: `clip-factory/shorts_generator/overlays.py:14-41` (`fit_lines`)
- Test: `clip-factory/tests/test_overlays.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_overlays.py`:
```python
def test_fit_lines_respects_min_font_floor():
    img = Image.new("RGBA", (1080, 320))
    draw = ImageDraw.Draw(img)
    # A long header that would normally shrink small; floor it at 52.
    text = "THE ONE MONEY RULE NOBODY EVER TELLS YOU ABOUT"
    lines, font = overlays.fit_lines(draw, text, FONT, max_w=960, max_h=240,
                                     min_font_size=52)
    assert font.size >= 52
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_overlays.py::test_fit_lines_respects_min_font_floor -v`
Expected: FAIL with `TypeError: fit_lines() got an unexpected keyword argument 'min_font_size'`.

- [ ] **Step 3: Add the parameter and use it**

In `overlays.py`, change the `fit_lines` signature (line 14-15) from:
```python
def fit_lines(draw, text, font_path, max_w=SAFE_W, max_h=240, max_lines=2,
              stroke=12, max_font_size=MAX_FONT):
```
to:
```python
def fit_lines(draw, text, font_path, max_w=SAFE_W, max_h=240, max_lines=2,
              stroke=12, max_font_size=MAX_FONT, min_font_size=MIN_FONT):
```

Change the loop bound (line 20) from:
```python
    for size in range(min(max_font_size, MAX_FONT), MIN_FONT - 1, -2):
```
to:
```python
    for size in range(min(max_font_size, MAX_FONT), max(min_font_size, MIN_FONT) - 1, -2):
```

Change the fallback (line 39) from:
```python
    font = ImageFont.truetype(font_path, MIN_FONT)
```
to:
```python
    font = ImageFont.truetype(font_path, max(min_font_size, MIN_FONT))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_overlays.py -v`
Expected: all tests PASS (the new floor test plus the existing ones).

- [ ] **Step 5: Commit**

```bash
git add shorts_generator/overlays.py tests/test_overlays.py
git commit -m "feat(overlays): add min_font_size floor to fit_lines"
```

---

## Task 3: Apply opacity to the background ONLY (fix the hook fade bug)

Right now `render_overlay_png` multiplies the whole image's alpha by `opacity`, so passing `opacity=0.5` for the hook also fades the TEXT to 50%. Refactor so the card/scrim background is built on its own layer, opacity is applied to that layer only, then text is drawn on top at full alpha.

**Files:**
- Modify: `clip-factory/shorts_generator/overlays.py:86-125` (`render_overlay_png`)
- Test: `clip-factory/tests/test_overlays.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_overlays.py`:
```python
def test_card_text_stays_opaque_when_background_is_transparent(tmp_path):
    # With opacity=0.5 the card box should be semi-transparent, but the
    # text must still reach full alpha (255). Before the fix the whole
    # layer was multiplied, so the max alpha capped near 127.
    out = str(tmp_path / "hook.png")
    overlays.render_overlay_png("PARENTS ARE CRAZY", "card", FONT,
                                out_path=out, opacity=0.5)
    im = Image.open(out)
    max_alpha = im.getextrema()[3][1]
    assert max_alpha == 255
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_overlays.py::test_card_text_stays_opaque_when_background_is_transparent -v`
Expected: FAIL — `max_alpha` is ~127, not 255 (whole layer was faded).

- [ ] **Step 3: Rewrite `render_overlay_png`**

Replace the entire function body (`overlays.py:86-125`) with:
```python
def render_overlay_png(text, preset="card", font_path=None, width=ZONE_W,
                       height=ZONE_H, out_path="overlay.png",
                       max_font_size=MAX_FONT, min_font_size=MIN_FONT, opacity=1.0):
    """Render a transparent PNG of the header/hook in the given preset.
    opacity: 0.0-1.0, applied to the BACKGROUND ONLY (card fill / scrim).
    The text always renders at full alpha so it stays crisp and readable."""
    spec = HEADER_PRESETS.get(preset, HEADER_PRESETS["card"])
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    stroke = spec.get("stroke", 0)
    lines, font = fit_lines(d, text, font_path, max_w=SAFE_W, max_h=height - 80,
                            stroke=stroke, max_font_size=max_font_size,
                            min_font_size=min_font_size)
    kw = pick_keyword(" ".join(lines).split(" "))
    block_h = (font.size + 14) * len(lines)
    cx = width // 2

    # Build the BACKGROUND on its own layer so opacity can apply to it alone.
    bg = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bg)
    if spec["container"] == "card":
        pad_x, pad_y = 48, 28
        widest = max(d.textbbox((0, 0), ln, font=font)[2] for ln in lines)
        cw = min(width - 40, widest + pad_x * 2)
        ch = block_h + pad_y * 2
        x0 = cx - cw / 2; y0 = (height - ch) / 2
        bd.rounded_rectangle([x0, y0, x0 + cw, y0 + ch], radius=34, fill=spec["card_fill"])
        text_top = y0 + pad_y
    else:  # scrim (stroke style): faint dark fade behind text for legibility
        for yy in range(height):
            a = int(150 * max(0, 1 - yy / height))   # darkest at top, fades down
            bd.line([(0, yy), (width, yy)], fill=(0, 0, 0, a))
        text_top = (height - block_h) / 2

    # Apply opacity to the BACKGROUND ONLY, then composite under the text.
    if opacity < 1.0:
        r, g, b, a = bg.split()
        a = a.point(lambda x: int(x * opacity))
        bg = Image.merge("RGBA", (r, g, b, a))
    img = Image.alpha_composite(img, bg)

    # Draw text on top at full alpha (crisp regardless of background opacity).
    d = ImageDraw.Draw(img)
    if spec["container"] == "card":
        _draw_centered(d, lines, font, cx, text_top, spec["text"], kw, spec["keyword"])
    else:
        _draw_centered(d, lines, font, cx, text_top, spec["text"], kw,
                       spec["keyword"], stroke=stroke, stroke_fill=(0, 0, 0))

    img.save(out_path)
    return out_path
```

- [ ] **Step 4: Run the suite to verify it passes**

Run: `pytest tests/test_overlays.py -v`
Expected: all tests PASS, including the new opacity test.

- [ ] **Step 5: Commit**

```bash
git add shorts_generator/overlays.py tests/test_overlays.py
git commit -m "fix(overlays): apply hook opacity to background only, keep text crisp"
```

---

## Task 4: Make the header compact (not overwhelming)

Lower the header's max font and give it the 48px floor so a 5-8 word header renders as a quiet, legible line.

**Files:**
- Modify: `clip-factory/shorts_generator/clipper.py:964-965`

- [ ] **Step 1: Update the header render call**

In `clipper.py`, change (lines 964-965):
```python
            _overlays.render_overlay_png(clip_data["title"], header_style, header_path,
                                         out_path=hdr_png, max_font_size=90)
```
to:
```python
            _overlays.render_overlay_png(clip_data["title"], header_style, header_path,
                                         out_path=hdr_png, max_font_size=80, min_font_size=48)
```

- [ ] **Step 2: Verify Python still compiles**

Run: `python -m py_compile shorts_generator/clipper.py`
Expected: no output (success).

- [ ] **Step 3: Commit**

```bash
git add shorts_generator/clipper.py
git commit -m "feat(clipper): render header compact (max 80, floor 48) so it doesn't dominate"
```

- [ ] **Step 4: Colab verification (next run)** — see checklist at bottom, item H.

---

## Task 5: Add `unsharp` sharpening + the hook fade in/out

Two FFmpeg filtergraph edits in `clipper.py`. The `unsharp` recovers edge detail lost when the source is scaled; the `fade` makes the magic hook appear/dissolve gently instead of popping on and off.

**Files:**
- Modify: `clip-factory/shorts_generator/clipper.py:187` and `:191` (unsharp, both layout branches)
- Modify: `clip-factory/shorts_generator/clipper.py:975-985` (hook fade)

- [ ] **Step 1: Add `unsharp` to the 1:1 ("box") layout**

In `clipper.py`, change line 187 from:
```python
            "[0:v]scale=1080:1080:flags=lanczos:force_original_aspect_ratio=increase,crop=1080:1080,setsar=1[video_graded]"
```
to:
```python
            "[0:v]scale=1080:1080:flags=lanczos:force_original_aspect_ratio=increase,crop=1080:1080,setsar=1,unsharp=5:5:0.6:5:5:0.0[video_graded]"
```

- [ ] **Step 2: Add `unsharp` to the full 9:16 layout**

Change line 191 from:
```python
            "[0:v]scale=1080:1920:flags=lanczos:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[video_graded]"
```
to:
```python
            "[0:v]scale=1080:1920:flags=lanczos:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,unsharp=5:5:0.6:5:5:0.0[video_graded]"
```
> Tuning note: `unsharp=5:5:0.6:5:5:0.0` = 5x5 luma kernel, amount 0.6, chroma amount 0.0 (luma-only to avoid color fringing on skin). If clips still look soft, raise the luma amount toward 0.8; if skin/edges look crunchy or haloed, drop toward 0.4.

- [ ] **Step 3: Add fade in/out to the magic hook**

In `clipper.py`, replace the hook block (lines 975-985):
```python
        if hook_on:
            hook_until = 5.0 if hook_display == "full" else (3.0 if hook_display == "3s" else 5.0)
            hk_png = os.path.join(work_dir, f"hook_{out_id}_{idx}.png")
            _overlays.render_overlay_png(clip_data["hook_text"], header_style, hook_path,
                                         out_path=hk_png, max_font_size=72, opacity=0.5)
            inputs.extend(["-loop", "1", "-t", str(clip_duration), "-i", hk_png])
            next_v = f"v{input_idx}_hook"
            filter_complex += (f"[{current_v}][{input_idx}:v]"
                               f"overlay=0:800:enable='lt(t,{hook_until})'[{next_v}];")
            current_v = next_v
            input_idx += 1
```
with:
```python
        if hook_on:
            hook_until = 5.0 if hook_display == "full" else (3.0 if hook_display == "3s" else 5.0)
            hk_png = os.path.join(work_dir, f"hook_{out_id}_{idx}.png")
            _overlays.render_overlay_png(clip_data["hook_text"], header_style, hook_path,
                                         out_path=hk_png, max_font_size=72, opacity=0.5)
            inputs.extend(["-loop", "1", "-t", str(clip_duration), "-i", hk_png])
            # Gentle 0.3s fade-in, 0.4s fade-out so the hook is transient, not a hard pop.
            # alpha=1 makes the fade act on the PNG's alpha channel only.
            fade_out_st = max(0.0, hook_until - 0.4)
            next_v = f"v{input_idx}_hook"
            filter_complex += (
                f"[{input_idx}:v]fade=t=in:st=0:d=0.3:alpha=1,"
                f"fade=t=out:st={fade_out_st}:d=0.4:alpha=1[hookfx{input_idx}];"
                f"[{current_v}][hookfx{input_idx}]"
                f"overlay=0:800:enable='lt(t,{hook_until})'[{next_v}];"
            )
            current_v = next_v
            input_idx += 1
```

- [ ] **Step 4: Verify Python still compiles**

Run: `python -m py_compile shorts_generator/clipper.py`
Expected: no output (success).

- [ ] **Step 5: Commit**

```bash
git add shorts_generator/clipper.py
git commit -m "feat(clipper): add unsharp sharpening + magic-hook fade in/out"
```

- [ ] **Step 6: Colab verification (next run)** — see checklist at bottom, items S and F.

---

## Task 6: Raise the source resolution cap to 1440p

A 1440p source downscaled into the 1080 canvas is sharper than a 1080 source scaled 1:1 or upscaled.

**Files:**
- Modify: `clip-factory/shorts_generator/downloader.py:18-19`

- [ ] **Step 1: Update the yt-dlp format string + sort**

In `downloader.py`, change lines 18-19 from:
```python
        '-f', 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
        '-S', 'res:1080,fps',
```
to:
```python
        '-f', 'bestvideo[height<=1440]+bestaudio/best[height<=1440]/best',
        '-S', 'res:1440,fps',
```
> If a future run shows the 9:16 full-bleed layout is still soft AND Colab download time is acceptable, bump both `1440` → `2160` for true 4K. Do NOT do this by default — 4K worsens the Colab disconnect/timeout problem the owner is already fighting.

- [ ] **Step 2: Verify Python still compiles**

Run: `python -m py_compile shorts_generator/downloader.py`
Expected: no output (success).

- [ ] **Step 3: Commit**

```bash
git add shorts_generator/downloader.py
git commit -m "feat(downloader): raise source cap to 1440p for a sharper downscale"
```

- [ ] **Step 4: Colab verification (next run)** — see checklist at bottom, item R.

---

## Task 7: Widen the header schema to a 5-8 word curiosity line

Change the LLM instruction so the header is a short curiosity phrase instead of a 2-5 word category tag — while keeping it ONE line of thought so it stays compact.

**Files:**
- Modify: `clip-factory/shorts_generator/highlights.py:822`

- [ ] **Step 1: Update the `"title"` schema instruction**

In `highlights.py`, change line 822 from:
```python
        '    "title": "ULTRA-SHORT TOPIC HOOK (2-5 words max). MUST be punchy, curiosity-inducing, and extremely short to fit on screen (e.g. \\"THE TRUTH ABOUT X\\", \\"STOP DOING THIS\\"). NO long sentences.",\n'
```
to:
```python
        '    "title": "SHORT CURIOSITY HEADLINE (5-8 words). A punchy, curiosity-inducing phrase or question that teases the clip WITHOUT giving away the payoff (e.g. \\"THE MONEY RULE NOBODY TELLS YOU\\", \\"WHY YOUR FIRST JOB WAS A LIE\\"). Keep it to ONE line of thought - no rambling, no two sentences.",\n'
```

- [ ] **Step 2: Verify Python still compiles**

Run: `python -m py_compile shorts_generator/highlights.py`
Expected: no output (success).

- [ ] **Step 3: Commit**

```bash
git add shorts_generator/highlights.py
git commit -m "feat(highlights): header is a 5-8 word curiosity line (was 2-5 word tag)"
```

- [ ] **Step 4: Colab verification (next run)** — see checklist at bottom, item H.

---

## Task 8: Update the docs (STATUS + BACKLOG)

Per `CLAUDE.md` honesty mandate: record what changed as "Done (code), NOT Colab-verified."

**Files:**
- Modify: `ClipFactory_Context/STATUS.md`
- Modify: `ClipFactory_Context/BACKLOG.md`

- [ ] **Step 1: Add a STATUS.md section**

Add under a new dated heading `## 2026-06-15 — premium visual polish (code-complete, NOT Colab-verified)`:
- unsharp sharpening added to both layout branches (`clipper.py`).
- Source cap raised 1080p → 1440p (`downloader.py`).
- Hook opacity bug fixed — background-only fade, text stays crisp (`overlays.py`).
- Hook now fades in (0.3s) / out (0.4s) (`clipper.py`).
- Header compact (max 80 / floor 48) + schema widened to 5-8 words (`clipper.py`, `highlights.py`).
- Mark every line NOT Colab-verified.

- [ ] **Step 2: Add BACKLOG.md rows**

Add rows (status `Done (code)`) for: unsharp sharpening, 1440p source, hook opacity background-only, hook fade in/out, compact header + 5-8 word schema. Reference this plan file.

- [ ] **Step 3: Commit (docs repo is the root context folder — NOT a git repo)**

The root `ClipFactory_Context/` is not a git repo, so there is nothing to commit there; just save the files. (Only `clip-factory/` is versioned.)

---

## Colab verification checklist (run on the next real GPU pass)

These replace unit tests for the FFmpeg/yt-dlp changes. Eyeball one rendered clip:

- **R (resolution):** `ffprobe source.mp4` — confirm height is now 1440 (or the best the source offers above 1080). If still 720/1080, the source genuinely had no higher rendition — note it, don't "fix" the code.
- **S (sharpness):** Compare a frame against a pre-change clip. Edges/text should look crisper, not haloed. If haloed, lower the `unsharp` luma amount (Task 5 note).
- **F (hook fade):** First 5s of clip 0 — the magic hook should fade IN gently (~0.3s), sit semi-transparent with crisp text, then fade OUT (~0.4s) instead of snapping off.
- **H (header):** The top banner should show a 5-8 word curiosity line, compact and legible, sitting quietly in the top zone — NOT a giant block dominating the frame, NOT overlapping the speaker.
- **O (opacity):** Confirm the hook's BOX is see-through but its TEXT is fully solid (the bug was both fading together).

Promote each item from 🟡 to ✅ in `STATUS.md` only after it is seen working in a real clip.

---

## Self-review notes (for the executor)
- Tasks 1-3 are fully test-covered locally (`pytest tests/test_overlays.py`). Run them first; they should go green before you touch the FFmpeg tasks.
- Tasks 4-7 are string edits to FFmpeg/yt-dlp commands — there is no honest way to unit-test them without a GPU. Do NOT write a fake test that just asserts the string contains `unsharp`; verify on Colab per the checklist.
- The hook in Task 5 depends on the opacity fix from Task 3 (background-only). Do Task 3 before Task 5, or the hook box will be solid.
- Do not add B-roll/transitions, and do not change caption fonts — both are explicit owner decisions recorded above.
