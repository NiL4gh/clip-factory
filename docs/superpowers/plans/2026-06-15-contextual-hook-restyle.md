# Contextual Magic-Hook Restyle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the magic hook a solid white, Title-Case box whose text gives the viewer the full context of the clip, and shrink the top header back to a short 3–5 word topic tag so the two elements have distinct jobs.

**Architecture:** Four surgical edits across three files. One is pure-Python (Pillow Title-Case support in `overlays.py`) and is verified locally with `pytest`. The other three are a one-line FFmpeg opacity flip and two LLM-prompt string changes that can only be eyeballed on a real Colab GPU run — each has an explicit Colab verification step instead of a unit test. No core pipeline is rewritten; the header element stays, only its word-count shrinks.

**Tech Stack:** Python 3.9, Pillow (PIL), FFmpeg filtergraph, pytest. Local LLaMA-cpp 8B emits the JSON the prompt strings describe.

---

## Owner decisions baked into this plan (do not re-litigate)
- **Both elements stay.** The clip is rendered into a frame that is NOT full-screen, so a top topic header + a centered hook can coexist (owner's call). This is NOT a meme caption — the white box "wraps the text" and the text "gives the viewer all the context they need."
- **Hook box:** solid white (opacity 1.0, reverses the 2026-06-15 `opacity=0.5` change), **Title Case** (reverses the forced ALL-CAPS), keep one red accent word, NO emoji yet (deferred fast-follow).
- **Hook text:** a short contextual premise (~6–12 words) that frames the clip — not a vague 2–5 word teaser.
- **Header:** revert to a **short 3–5 word topic tag** (was widened to 5–8 words on 2026-06-15). The hook now carries the context, so the header steps back to a label.
- **Emoji:** explicitly out of scope. Do not add an emoji font or per-glyph rendering in this plan.

## Files touched
- `clip-factory/shorts_generator/overlays.py` — add a `casing` param to `fit_lines` + `render_overlay_png` and an `_apply_casing` helper (Task 1).
- `clip-factory/tests/test_overlays.py` — Title-Case tests (Task 1).
- `clip-factory/shorts_generator/clipper.py` — hook render call: `opacity=0.5` → `opacity=1.0`, add `casing="title"` (Task 2).
- `clip-factory/shorts_generator/highlights.py` — `hook_text` schema instruction → contextual premise; self-check checklist word cap updated; `title` schema 5–8 → 3–5 words (Tasks 3, 4).

## How to run the tests
From `clip-factory/`:
```bash
pytest tests/test_overlays.py -v
```
The FFmpeg opacity flip (Task 2) and the two prompt edits (Tasks 3, 4) have NO local test — they are verified on the next Colab run using the checklist in "Colab verification" at the bottom. Do NOT write a fake test that asserts a prompt string contains a substring.

---

## Task 0: Branch off main

The repo's only branch is `main` (default). Do not commit feature work directly to it.

- [ ] **Step 1: Create and switch to a feature branch**

Run:
```bash
git checkout -b feature/contextual-hook
```
Expected: `Switched to a new branch 'feature/contextual-hook'`.

---

## Task 1: Add Title-Case support to `overlays.py`

`fit_lines` currently hard-codes `text.upper()`, so every overlay is ALL CAPS. Add a `casing` option so the hook can render Title Case while the header keeps its default ALL-CAPS behavior unchanged.

**Files:**
- Modify: `clip-factory/shorts_generator/overlays.py`
- Test: `clip-factory/tests/test_overlays.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_overlays.py`:
```python
def test_fit_lines_defaults_to_upper():
    img = Image.new("RGBA", (1080, 320))
    draw = ImageDraw.Draw(img)
    lines, _font = overlays.fit_lines(draw, "stay hungry", FONT)
    assert " ".join(lines) == "STAY HUNGRY"


def test_fit_lines_title_case():
    img = Image.new("RGBA", (1080, 320))
    draw = ImageDraw.Draw(img)
    lines, _font = overlays.fit_lines(draw, "when you surprise your girlfriend",
                                      FONT, casing="title")
    assert " ".join(lines) == "When You Surprise Your Girlfriend"


def test_fit_lines_title_case_keeps_apostrophes():
    img = Image.new("RGBA", (1080, 320))
    draw = ImageDraw.Draw(img)
    lines, _font = overlays.fit_lines(draw, "don't quit your job", FONT,
                                      casing="title")
    assert " ".join(lines) == "Don't Quit Your Job"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_overlays.py::test_fit_lines_title_case -v`
Expected: FAIL with `TypeError: fit_lines() got an unexpected keyword argument 'casing'`.

- [ ] **Step 3: Add the `_apply_casing` helper**

In `overlays.py`, add this function immediately **above** `def fit_lines` (i.e. before line 14):
```python
def _apply_casing(text, casing):
    """Collapse whitespace and apply the requested casing.
    'upper' -> ALL CAPS (default; the top header uses this).
    'title' -> Title Case, first letter of each word capitalised, rest lower.
               Implemented per-word (not str.title()) so "don't" stays "Don't".
    'none'  -> leave the text as-is (only whitespace collapsed)."""
    text = " ".join(text.split())
    if casing == "upper":
        return text.upper()
    if casing == "title":
        return " ".join(w[:1].upper() + w[1:].lower() if w else w
                        for w in text.split(" "))
    return text
```

- [ ] **Step 4: Thread `casing` through `fit_lines`**

In `overlays.py`, change the `fit_lines` signature (currently line 14-15) from:
```python
def fit_lines(draw, text, font_path, max_w=SAFE_W, max_h=240, max_lines=2,
              stroke=12, max_font_size=MAX_FONT, min_font_size=MIN_FONT):
```
to:
```python
def fit_lines(draw, text, font_path, max_w=SAFE_W, max_h=240, max_lines=2,
              stroke=12, max_font_size=MAX_FONT, min_font_size=MIN_FONT,
              casing="upper"):
```

Then change the casing line inside `fit_lines` (currently line 19) from:
```python
    text = " ".join(text.upper().split())
```
to:
```python
    text = _apply_casing(text, casing)
```

- [ ] **Step 5: Thread `casing` through `render_overlay_png`**

In `overlays.py`, change the `render_overlay_png` signature (currently lines 88-90) from:
```python
def render_overlay_png(text, preset="card", font_path=None, width=ZONE_W,
                       height=ZONE_H, out_path="overlay.png",
                       max_font_size=MAX_FONT, min_font_size=MIN_FONT, opacity=1.0):
```
to:
```python
def render_overlay_png(text, preset="card", font_path=None, width=ZONE_W,
                       height=ZONE_H, out_path="overlay.png",
                       max_font_size=MAX_FONT, min_font_size=MIN_FONT, opacity=1.0,
                       casing="upper"):
```

Then change the `fit_lines` call inside `render_overlay_png` (currently lines 98-100) from:
```python
    lines, font = fit_lines(d, text, font_path, max_w=SAFE_W, max_h=height - 80,
                            stroke=stroke, max_font_size=max_font_size,
                            min_font_size=min_font_size)
```
to:
```python
    lines, font = fit_lines(d, text, font_path, max_w=SAFE_W, max_h=height - 80,
                            stroke=stroke, max_font_size=max_font_size,
                            min_font_size=min_font_size, casing=casing)
```

- [ ] **Step 6: Run the whole suite to verify green**

Run: `pytest tests/test_overlays.py -v`
Expected: all tests PASS (the 3 new casing tests plus the existing ones).

- [ ] **Step 7: Commit**

```bash
git add shorts_generator/overlays.py tests/test_overlays.py
git commit -m "feat(overlays): add casing option (Title Case) to fit_lines/render_overlay_png"
```

---

## Task 2: Make the hook a solid white Title-Case box

Flip the hook from 50%-transparent ALL-CAPS to solid Title Case. The header call is untouched (stays ALL CAPS, opacity 1.0 by default).

**Files:**
- Modify: `clip-factory/shorts_generator/clipper.py:978-979`

- [ ] **Step 1: Update the hook render call**

In `clipper.py`, change (currently lines 978-979):
```python
            _overlays.render_overlay_png(clip_data["hook_text"], header_style, hook_path,
                                         out_path=hk_png, max_font_size=72, opacity=0.5)
```
to:
```python
            _overlays.render_overlay_png(clip_data["hook_text"], header_style, hook_path,
                                         out_path=hk_png, max_font_size=72, opacity=1.0,
                                         casing="title")
```

- [ ] **Step 2: Verify Python still compiles**

Run: `python -m py_compile shorts_generator/clipper.py`
Expected: no output (success).

- [ ] **Step 3: Commit**

```bash
git add shorts_generator/clipper.py
git commit -m "feat(clipper): hook is now solid white + Title Case (was 50% caps)"
```

- [ ] **Step 4: Colab verification (next run)** — see checklist at bottom, items B and C.

---

## Task 3: Hook text becomes a contextual premise line

Rewrite the `hook_text` LLM instruction so the model writes a short line that frames what the clip is about (full context for a scroller), not a vague 2–5 word teaser. Also update the prompt's self-check checklist, which currently tells the model to trim `hook_text` to 8 words.

**Files:**
- Modify: `clip-factory/shorts_generator/highlights.py:839` (the `"hook_text"` schema line)
- Modify: `clip-factory/shorts_generator/highlights.py:902` (the self-check checklist line)

- [ ] **Step 1: Update the `"hook_text"` schema instruction**

In `highlights.py`, change line 839 from:
```python
        '    "hook_text": "Write 3-8 words: a punchy headline that ACCURATELY reflects the clip\'s core point. Example for a clip about first jobs: YOUR FIRST JOB WAS A LIE. Example for a friendship clip: MEN NEED BETTER FRIENDS. Must match what the clip actually says — do not invent stakes or overstate the content.",\n'
```
to:
```python
        '    "hook_text": "Write a SHORT CONTEXTUAL SETUP LINE (about 6-12 words) that instantly tells a scroller what is happening in this clip, the way a relatable caption frames a scene. Give the full premise, not a vague tease. Examples: \\"When a millionaire explains why saving money is a trap\\", \\"How this guy turned one bad job into a business\\". Must accurately reflect what the clip actually says — do not invent stakes or overstate the content.",\n'
```

- [ ] **Step 2: Update the self-check checklist line**

In `highlights.py`, change line 902 from:
```python
        '□ hook_text is 8 words or fewer — if longer, trim it\n'
```
to:
```python
        '□ hook_text is a contextual setup line of roughly 6-12 words — if it is a bare 1-3 word tag, expand it to give the full premise; if it rambles past ~14 words, tighten it\n'
```
> Note: confirm the exact source text of line 902 before editing — match it verbatim including the leading `'□ ` and trailing `\n'`. The surrounding lines are other `□` checklist entries inside the same prompt string.

- [ ] **Step 3: Verify Python still compiles**

Run: `python -m py_compile shorts_generator/highlights.py`
Expected: no output (success).

- [ ] **Step 4: Commit**

```bash
git add shorts_generator/highlights.py
git commit -m "feat(highlights): hook_text is a contextual setup line (~6-12 words)"
```

- [ ] **Step 5: Colab verification (next run)** — see checklist at bottom, item C.

---

## Task 4: Header back to a short 3–5 word topic tag

Now that the hook carries the context, shrink the header schema from a 5–8 word curiosity sentence back to a short topic tag so the top banner reads as a quick label, not a competing sentence.

**Files:**
- Modify: `clip-factory/shorts_generator/highlights.py:822` (the `"title"` schema line)

- [ ] **Step 1: Update the `"title"` schema instruction**

In `highlights.py`, change line 822 from:
```python
        '    "title": "SHORT CURIOSITY HEADLINE (5-8 words). A punchy, curiosity-inducing phrase or question that teases the clip WITHOUT giving away the payoff (e.g. \\"THE MONEY RULE NOBODY TELLS YOU\\", \\"WHY YOUR FIRST JOB WAS A LIE\\"). ONE line of thought only — no two sentences, no rambling.",\n'
```
to:
```python
        '    "title": "SHORT TOPIC TAG (3-5 words max). A punchy label for the clip topic that reads as a quick banner, NOT a full sentence (e.g. \\"THE MONEY TRAP\\", \\"FIRST JOB MISTAKES\\", \\"BETTER MALE FRIENDSHIPS\\"). Keep it extremely short — the contextual setup lives in hook_text, not here.",\n'
```

- [ ] **Step 2: Verify Python still compiles**

Run: `python -m py_compile shorts_generator/highlights.py`
Expected: no output (success).

- [ ] **Step 3: Commit**

```bash
git add shorts_generator/highlights.py
git commit -m "feat(highlights): header back to a short 3-5 word topic tag"
```

- [ ] **Step 4: Colab verification (next run)** — see checklist at bottom, item H.

---

## Task 5: Update the docs (STATUS + BACKLOG)

Per `CLAUDE.md` honesty mandate: record what changed as "Done (code), NOT Colab-verified."

**Files:**
- Modify: `ClipFactory_Context/STATUS.md`
- Modify: `ClipFactory_Context/BACKLOG.md`

- [ ] **Step 1: Add a STATUS.md section**

Add under a new dated heading `## 2026-06-15 — contextual hook restyle (code-complete, NOT Colab-verified)`:
- Hook box now solid white (`opacity=1.0`, reverses the 0.5 change) + Title Case (`clipper.py`, `overlays.py`).
- `hook_text` is now a contextual setup line (~6-12 words) instead of a 2-5 word teaser (`highlights.py`).
- Header schema back to a short 3-5 word topic tag (`highlights.py`).
- `fit_lines`/`render_overlay_png` gained a `casing` option; default `"upper"` keeps the header unchanged.
- Mark every line NOT Colab-verified.

- [ ] **Step 2: Add BACKLOG.md rows**

Add rows (status `Done (code)`) for: hook solid+Title Case, contextual hook_text, header 3-5 word tag, `casing` option. Reference this plan file.

- [ ] **Step 3: Save the docs**

The root `ClipFactory_Context/` is not a git repo, so there is nothing to commit there; just save the files. (Only `clip-factory/` is versioned.)

---

## Task 6: Finish the branch

- [ ] **Step 1: Run the full test suite once more**

Run: `pytest tests/test_overlays.py -v`
Expected: all PASS.

- [ ] **Step 2: Use the finishing-a-development-branch skill**

REQUIRED SUB-SKILL: `superpowers:finishing-a-development-branch` — present merge/PR/cleanup options to the owner. Default expectation (matches prior workflow): merge `feature/contextual-hook` → `main`, push, delete the feature branch.

---

## Colab verification checklist (run on the next real GPU pass)

These replace unit tests for the FFmpeg/prompt changes. Eyeball one rendered clip (clip 0, first ~5 seconds):

- **B (box):** The hook's white box is **solid** (not see-through) and wraps snugly around the wrapped text block.
- **C (case + context):** The hook text is **Title Case** and reads as a contextual setup line that tells you what the clip is about — not a 2-3 word tag. One word may be red-accented.
- **H (header):** The top banner is a **short 3-5 word topic tag**, clearly shorter than the hook, sitting quietly up top and not competing with the hook.
- **Coexistence:** Header (top) and hook (center, first few seconds) read as two distinct elements, not two near-identical boxes.

Promote each item from 🟡 to ✅ in `STATUS.md` only after it is seen working in a real clip.

---

## Self-review notes (for the executor)
- Task 1 is fully test-covered locally (`pytest tests/test_overlays.py`). Run it first; it should go green before you touch the FFmpeg/prompt tasks.
- Tasks 2-4 cannot be honestly unit-tested (one ffmpeg arg + two LLM-prompt strings). Verify on Colab per the checklist; do NOT assert prompt substrings in a test.
- Line numbers (`clipper.py:978-979`, `highlights.py:822/839/902`) are from the 2026-06-15 state of `main`. If they have drifted, match the quoted source text verbatim instead of trusting the line number.
- Do NOT add emoji rendering — explicitly deferred by the owner.
- Do NOT change the header's font, position, or the hook's fade-in/out — only the items listed above.
