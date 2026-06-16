# Handoff Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 6 issues from the 2026-06-16 handoff — LLM hook diversity, layout bug, font corruption, log folder structure, hook duration, per-clip delete.

**Architecture:** Backend FastAPI (`server/main.py`), LLM extraction in `shorts_generator/highlights.py`, render in `shorts_generator/clipper.py`, logger in `shorts_generator/logger.py`, frontend single-file component `frontend/src/app/page.tsx`. All Colab paths from `shorts_generator/config.py`.

**Tech Stack:** Python 3.9, FastAPI, Pillow, ffmpeg subprocess, Next.js 14, Tailwind CSS, TypeScript

---

## Handoff Audit (corrections to what the Gemini CLI claimed)

- **Clip naming** — claimed it needed fixing. **Already done.** `clipper.py:754` produces `{date}_{safe_title}_{id}.mp4` using the clip's header title. No work needed.
- **Font fix** — claimed it was committed. **It was not.** `colab_launcher.ipynb` still uses `getsize == 0`. Task 3 fixes it.
- **Temperature 0.70 blanket** — the handoff suggested 0.7 OR a split. **0.70 blanket is wrong** — the same LLM call produces both creative hook text (benefits from higher temp) and precise timestamps + JSON schema (breaks at high temp). Fix: address the root cause (verbatim examples) and bump moderately to 0.55 only. A true temperature split (separate LLM call for hooks) is Phase 2 quality work.
- **Anti-fingerprinting** — handoff suggested building now. **Do not build.** Explicitly deferred to Phase 3 (BACKLOG #44) until core pipeline is verified.
- **Portrait seeds** — the original style-randomization spec (docs/superpowers/specs/2026-06-16-style-randomization-design.md) intentionally included `layout_mode: "portrait"` for Punch and Cinematic. Owner does not want this — overriding the spec in Task 2.

---

## Files Touched

| File | Task | Change |
|---|---|---|
| `shorts_generator/highlights.py` | 1 | Replace verbatim hook examples; bump temperature 0.40 → 0.55 |
| `frontend/src/app/page.tsx` | 2 | Fix portrait seeds → box; bump 3s hook_display → 5s on 3 seeds |
| `colab_launcher.ipynb` | 3 | Font size check: `== 0` → `< 50000` |
| `shorts_generator/logger.py` | 4 | Group logs under `LOGS_DIR/{video_title}/`; rename files to `session log {title}.jsonl` + `llm log {title}.log` |
| `server/main.py` | 4 | Pass `video_title` to `get_logger()` calls |
| `shorts_generator/clipper.py` | 5 | Bump `hook_until` "full" mode: 5s → 7s |
| `server/main.py` | 6 | Add `DELETE /api/clips/{video_id}/{filename}` endpoint |
| `frontend/src/app/page.tsx` | 6 | Add trash button to rendered clip cards |

---

## Task 1: LLM Hook Quality — Example Cleanup + Temperature Nudge

**Why 0.70 is wrong:** The clip extraction call produces timestamps, segment quotes, JSON arrays, and virality scores alongside the hook text — all in one response. Temperature 0.70 causes drift on structured fields. Root cause of repetitive hooks is that the self-check at line 902 gives "Nobody talks about this" as a model answer, so the 8B model treats it as a correct output to copy.

**Fix:** Remove verbatim hook phrases from both example sites. Bump temperature from 0.40 → 0.55 as a moderate diversity nudge that keeps JSON coherent. A full temperature split (separate creative call for hooks at 0.65) is Phase 2.

**Files:**
- Modify: `shorts_generator/highlights.py` (lines ~104, ~191, ~222, ~234, ~248, ~261, ~277, ~902)

- [ ] **Step 1: Read lines 100-110 and confirm the curiosity_gap example**
  ```
  grep -n "Nobody talks" clip-factory/shorts_generator/highlights.py
  ```
  Expected: hits at ~line 104 and ~line 902.

- [ ] **Step 2: Replace the curiosity_gap example (line ~104)**

  Find:
  ```python
  '1. "curiosity_gap" — Information asymmetry. Imply knowledge the viewer\n'
  '   lacks. Example hook: "Nobody talks about this, but it explains\n'
  '   everything."\n'
  ```
  Replace with:
  ```python
  '1. "curiosity_gap" — Information asymmetry. Imply knowledge the viewer\n'
  '   lacks. Template: "The hidden cost of [SPECIFIC TOPIC]" or "Why [COMMON BELIEF] is wrong about [TOPIC]"\n'
  ```

- [ ] **Step 3: Replace the self-check example (line ~902)**

  Find:
  ```python
  '□ hook_text is a 3-7 word VIEWER HOOK (reaction/revelation/tease) — NOT a description of what happens; if it describes the clip content instead of psychologically hooking the viewer, rewrite it as a short punchy trigger (e.g. "Nobody talks about this", "This changed everything")\n'
  ```
  Replace with:
  ```python
  '□ hook_text is a 3-7 word VIEWER HOOK specific to THIS clip\'s subject. Generic filler ("Nobody talks about this", "This changed everything", "Wait, seriously?") is BANNED — these exact phrases are forbidden output. The hook must be a phrase only someone who watched THIS specific clip would recognize as true. If it could apply to any clip, rewrite it.\n'
  ```

- [ ] **Step 4: Bump temperature from 0.40 to 0.55 across all provider branches**

  Run to find all sites:
  ```bash
  grep -n "temperature" clip-factory/shorts_generator/highlights.py
  ```
  Change each `0.4` / `0.40` inside `_call_llm` (not elsewhere) to `0.55`:

  Local llama-cpp (~line 191):
  ```python
  temperature=0.55,
  ```

  Gemini (~line 222):
  ```python
  "generationConfig": {"responseMimeType": "application/json", "temperature": 0.55, "maxOutputTokens": mx}
  ```

  Groq, OpenRouter, GLM, Nvidia (~lines 234, 248, 261):
  ```python
  "temperature": 0.55,
  ```

  Ollama (~line 277):
  ```python
  "options": {"temperature": 0.55, "num_predict": mx}
  ```

- [ ] **Step 5: Verify no stale 0.4 values remain inside _call_llm**
  ```bash
  grep -n "temperature" clip-factory/shorts_generator/highlights.py
  ```
  Expected: all temperature values show 0.55.

- [ ] **Step 6: Compile-check**
  ```bash
  python -m py_compile clip-factory/shorts_generator/highlights.py && echo "OK"
  ```
  Expected: `OK`

- [ ] **Step 7: Commit**
  ```bash
  cd clip-factory && git add shorts_generator/highlights.py
  git commit -m "fix: remove verbatim hook examples; bump LLM temp 0.40→0.55 for hook diversity"
  ```

---

## Task 2: Fix Style Seeds — Portrait Layout + Hook Duration

**Two problems in the same file:**
1. Seeds `blur_punch` and `cinematic` have `layout_mode: "portrait"` which renders full-screen instead of boxed — the original spec included this intentionally but the owner doesn't want it.
2. Seeds `viral_stroke`, `brand_minimal`, and `blur_punch` have `hook_display: "3s"` which is too short — bump to `"5s"`.

**Files:**
- Modify: `frontend/src/app/page.tsx` (STYLE_SEEDS constant, lines 135–172)

- [ ] **Step 1: Read the current seeds**

  Open `frontend/src/app/page.tsx` lines 135–172 and confirm these exact values:
  - `blur_punch`: `layout_mode: "portrait"`, `hook_display: "3s"`
  - `cinematic`: `layout_mode: "portrait"`, `hook_display: "off"`
  - `viral_stroke`: `hook_display: "3s"`
  - `brand_minimal`: `hook_display: "3s"`

- [ ] **Step 2: Apply all seed corrections**

  Replace the entire `STYLE_SEEDS` block (lines 135–172) with:
  ```ts
  const STYLE_SEEDS: StyleSeed[] = [
    {
      id: "viral_stroke",
      label: "🔥 Viral",
      badgeColor: "bg-orange-100 text-orange-700 border-orange-200",
      changes: { layout_mode: "box", bg_style: "brand", caption_style: "Pop", title_style: "Impact", hook_display: "5s", header_style: "stroke", header_font: "bebas", caption_font: "montserrat", hook_font: "montserrat" },
    },
    {
      id: "viral_dark",
      label: "🌑 Dark Pop",
      badgeColor: "bg-slate-800 text-slate-100 border-slate-700",
      changes: { layout_mode: "box", bg_style: "black", caption_style: "Pop", title_style: "Impact", hook_display: "5s", header_style: "card", header_font: "bebas", caption_font: "montserrat", hook_font: "montserrat" },
    },
    {
      id: "clean_white",
      label: "✨ Clean",
      badgeColor: "bg-slate-100 text-slate-700 border-slate-300",
      changes: { layout_mode: "box", bg_style: "white", caption_style: "Classic", title_style: "Box", hook_display: "off", header_style: "card", header_font: "montserrat-black", caption_font: "poppins", hook_font: "poppins" },
    },
    {
      id: "brand_minimal",
      label: "🎯 Minimal",
      badgeColor: "bg-blue-100 text-blue-700 border-blue-200",
      changes: { layout_mode: "box", bg_style: "brand", caption_style: "Classic", title_style: "None", hook_display: "5s", header_style: "card", header_font: "inter", caption_font: "roboto", hook_font: "roboto" },
    },
    {
      id: "blur_punch",
      label: "💥 Punch",
      badgeColor: "bg-purple-100 text-purple-700 border-purple-200",
      changes: { layout_mode: "box", bg_style: "blur", caption_style: "Pop", title_style: "Impact", hook_display: "5s", header_style: "stroke", header_font: "bebas", caption_font: "montserrat", hook_font: "montserrat" },
    },
    {
      id: "cinematic",
      label: "🎬 Cinematic",
      badgeColor: "bg-rose-100 text-rose-700 border-rose-200",
      changes: { layout_mode: "box", bg_style: "blur", caption_style: "CinematicSlate", title_style: "None", hook_display: "off", header_style: "card", header_font: "inter", caption_font: "poppins", hook_font: "poppins" },
    },
  ];
  ```

  Changes made vs. original:
  - `viral_stroke`: `hook_display` 3s → 5s
  - `viral_dark`: `hook_display` stays 5s (already correct)
  - `brand_minimal`: `hook_display` 3s → 5s
  - `blur_punch`: `layout_mode` portrait → box; `hook_display` 3s → 5s
  - `cinematic`: `layout_mode` portrait → box

- [ ] **Step 3: TypeScript build check**
  ```bash
  cd clip-factory/frontend && npm run build 2>&1 | tail -10
  ```
  Expected: `✓ Compiled successfully`

- [ ] **Step 4: Commit**
  ```bash
  cd clip-factory && git add frontend/src/app/page.tsx
  git commit -m "fix: remove portrait layout from seeds; bump 3s hook_display → 5s"
  ```

---

## Task 3: Fix Corrupted Font Detection in Colab Launcher

**Problem:** When GitHub rate-limits a font download, `urllib` saves an HTML error page (~8 KB) with a `.ttf` extension. The check `getsize == 0` only catches empty files. The HTML page is ~8–15 KB so it passes the check and gets cached, causing `OSError: unknown file format` on every subsequent render without re-running setup. **The handoff claimed this was fixed — it was not committed.**

**Files:**
- Modify: `colab_launcher.ipynb` (font download loop in the setup cell)

- [ ] **Step 1: Verify the bug is still present**
  ```bash
  python -c "
  import json, sys
  src = ''.join(json.load(open('clip-factory/colab_launcher.ipynb'))['cells'][2]['source'])
  print('BUG PRESENT' if 'getsize(path) == 0' in src else 'ALREADY FIXED')
  "
  ```
  Expected: `BUG PRESENT`

- [ ] **Step 2: Patch the font download loop**

  The notebook is JSON. Edit it as a Python script to avoid manually writing JSON-escaped strings:
  ```bash
  python -c "
  import json, re

  path = 'clip-factory/colab_launcher.ipynb'
  nb = json.load(open(path, encoding='utf-8'))

  # Find cell with font download loop
  for cell in nb['cells']:
      src = ''.join(cell['source'])
      if 'font_urls' in src and 'getsize' in src:
          new_src = src.replace(
              'if not os.path.exists(path) or os.path.getsize(path) == 0:',
              'if not os.path.exists(path) or os.path.getsize(path) < 50000:'
          )
          # Also patch the download block to raise on small files
          old_block = (
              '            urllib.request.urlretrieve(url, path)\n'
              \"            print(f'✓ Downloaded: {filename}')\"
          )
          new_block = (
              '            urllib.request.urlretrieve(url, path)\n'
              '            size = os.path.getsize(path)\n'
              '            if size < 50000:\n'
              '                os.remove(path)\n'
              \"                raise Exception(f'File too small ({size}B) — GitHub may have rate-limited; re-run setup.')\n\"
              \"            print(f'✓ Downloaded: {filename} ({size//1024}KB)')\"
          )
          new_src = new_src.replace(old_block, new_block)
          cell['source'] = list(new_src)  # notebook stores source as char list or line list
          break

  json.dump(nb, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
  print('Patched')
  "
  ```

  **Note:** Notebook cells store `source` as either a single string or a list of strings. Verify the patch worked:
  ```bash
  python -c "
  import json
  src = ''.join(json.load(open('clip-factory/colab_launcher.ipynb'))['cells'][2]['source'])
  print('FIXED' if '< 50000' in src else 'NOT FIXED')
  "
  ```

- [ ] **Step 3: Verify the notebook JSON is still valid**
  ```bash
  python -c "import json; json.load(open('clip-factory/colab_launcher.ipynb')); print('Valid JSON')"
  ```
  Expected: `Valid JSON`

- [ ] **Step 4: Commit**
  ```bash
  cd clip-factory && git add colab_launcher.ipynb
  git commit -m "fix: detect corrupted font files by size (<50KB), not just zero-byte check"
  ```

  **Owner note:** After this is pushed, re-run the Colab setup cell. It will detect any cached HTML error pages and replace them.

---

## Task 4: Log Files Grouped by Video Title with Clear Names

**Problem:** All log files land flat in `LOGS_DIR/` with names like `session_abc123_20260616.jsonl`. There is no way to find the logs for a specific video. The owner wants:
```
logs/
└── Jay Shetty Kendall Jenner/
    ├── session log Jay Shetty Kendall Jenner.jsonl   ← structured events (LLM calls, ffmpeg, app)
    └── llm log Jay Shetty Kendall Jenner.log         ← human-readable text summary
```

**Files:**
- Modify: `shorts_generator/logger.py` (AppLogger `__init__`, `get_logger`)
- Modify: `server/main.py` (pass `video_title` to `get_logger` at each call site)

- [ ] **Step 1: Update `AppLogger.__init__` in `logger.py`**

  Find (lines ~121–130):
  ```python
  def __init__(self, session_id: str):
      self.session_id = session_id
      self.logger = logging.getLogger(f"AppLogger.{session_id}")
      self.ts = datetime.now().strftime('%Y%m%d_%H%M%S')
      self.jsonl_path = LOG_DIR / f'session_{session_id}_{self.ts}.jsonl'
      self.text_path = LOG_DIR / f'session_{session_id}.log'
      
      self._file = open(self.text_path, 'a', encoding='utf-8')
  ```
  Replace with:
  ```python
  def __init__(self, session_id: str, video_title: str = ""):
      self.session_id = session_id
      self.logger = logging.getLogger(f"AppLogger.{session_id}")
      self.ts = datetime.now().strftime('%Y%m%d_%H%M%S')
      if video_title:
          safe = "".join(c for c in video_title if c.isalnum() or c in " _-")[:60].strip()
          log_subdir = LOG_DIR / safe
      else:
          log_subdir = LOG_DIR / session_id
      log_subdir.mkdir(parents=True, exist_ok=True)
      label = safe if video_title else session_id
      self.jsonl_path = log_subdir / f'session log {label}.jsonl'
      self.text_path  = log_subdir / f'llm log {label}.log'
      
      self._file = open(self.text_path, 'a', encoding='utf-8')
  ```

- [ ] **Step 2: Update `get_logger` to accept and forward `video_title`**

  Find:
  ```python
  def get_logger(session_id: str) -> AppLogger:
      if session_id not in _loggers:
          _loggers[session_id] = AppLogger(session_id)
      return _loggers[session_id]
  ```
  Replace with:
  ```python
  def get_logger(session_id: str, video_title: str = "") -> AppLogger:
      if session_id not in _loggers:
          _loggers[session_id] = AppLogger(session_id, video_title=video_title)
      return _loggers[session_id]
  ```

- [ ] **Step 3: Find all `get_logger` call sites in `main.py`**
  ```bash
  grep -n "get_logger" clip-factory/server/main.py
  ```
  Expected: multiple lines. Note each line number.

- [ ] **Step 4: Update each call site to pass `video_title`**

  At every site where `get_logger(session_id)` is called, change to:
  ```python
  get_logger(session_id, video_title=_state.get("video_title", ""))
  ```
  The `_state["video_title"]` is populated after the download step. Calls during strategize and render will have this value; calls before download will fall back to session_id (which is fine).

- [ ] **Step 5: Compile-check both files**
  ```bash
  python -m py_compile clip-factory/shorts_generator/logger.py && \
  python -m py_compile clip-factory/server/main.py && echo "OK"
  ```
  Expected: `OK`

- [ ] **Step 6: Commit**
  ```bash
  cd clip-factory && git add shorts_generator/logger.py server/main.py
  git commit -m "feat: group logs under LOGS_DIR/{video_title}/; rename to 'session log' and 'llm log'"
  ```

---

## Task 5: Increase Hook Display Duration

**Problem:** "Full" hook mode shows the hook for 5s, but 0.3s fade-in + 0.4s fade-out means it's only fully opaque for 4.3s. Users find it disappears before they can read it. Also, seeds with "3s" (bumped to "5s" in Task 2) should now match the new backend ceiling.

**Fix:** Bump `hook_until` for "full" mode from 5.0s to 7.0s. The fallback (when hook_display is not "3s" or "full") also bumps to 7.0s.

**Files:**
- Modify: `shorts_generator/clipper.py` (line ~976)

- [ ] **Step 1: Find and confirm the current hook_until line**
  ```bash
  grep -n "hook_until" clip-factory/shorts_generator/clipper.py
  ```
  Expected: one line reading `hook_until = 5.0 if hook_display == "full" else (3.0 if hook_display == "3s" else 5.0)`

- [ ] **Step 2: Bump "full" duration to 7s**

  Find:
  ```python
  hook_until = 5.0 if hook_display == "full" else (3.0 if hook_display == "3s" else 5.0)
  ```
  Replace with:
  ```python
  hook_until = 7.0 if hook_display == "full" else (5.0 if hook_display == "5s" else (3.0 if hook_display == "3s" else 7.0))
  ```
  This maps: `full`→7s, `5s`→5s, `3s`→3s, anything else→7s.

- [ ] **Step 3: Compile-check**
  ```bash
  python -m py_compile clip-factory/shorts_generator/clipper.py && echo "OK"
  ```
  Expected: `OK`

- [ ] **Step 4: Commit**
  ```bash
  cd clip-factory && git add shorts_generator/clipper.py
  git commit -m "fix: hook display 'full' mode 5s→7s; add explicit 5s branch for seeds"
  ```

---

## Task 6: Per-Clip Delete (Backend + Frontend)

**Problem:** The only way to free Drive space is to wipe the entire batch. The owner wants to delete individual clips from the UI.

**Backend:** Add `DELETE /api/clips/{video_id}/{filename}` that safely removes one file.
**Frontend:** Add a trash button to each clip card when a rendered file exists. Use the `Trash2` icon already available from `lucide-react`.

**Files:**
- Modify: `server/main.py`
- Modify: `frontend/src/app/page.tsx`

- [ ] **Step 1: Add the delete endpoint to `main.py`**

  Find `@app.get("/api/settings")` (around line 1305). Insert just before it:
  ```python
  @app.delete("/api/clips/{video_id}/{filename}")
  async def delete_clip(video_id: str, filename: str):
      import re
      if not re.match(r'^[\w\-. ]+\.mp4$', filename):
          raise HTTPException(status_code=400, detail="Invalid filename")
      file_path = os.path.join(OUTPUT_DIR, video_id, filename)
      if not os.path.exists(file_path):
          raise HTTPException(status_code=404, detail="Clip not found")
      try:
          os.remove(file_path)
          for clip in _state.get("clips", []):
              rf = clip.get("rendered_filename", "")
              if rf and rf.endswith(filename):
                  clip.pop("rendered_filename", None)
          if _state.get("current_url"):
              _save_session(_state["current_url"])
          return {"status": "deleted", "filename": filename}
      except Exception as e:
          raise HTTPException(status_code=500, detail=str(e))
  ```

- [ ] **Step 2: Compile-check backend**
  ```bash
  python -m py_compile clip-factory/server/main.py && echo "OK"
  ```
  Expected: `OK`

- [ ] **Step 3: Check that `Trash2` is already imported in `page.tsx`**
  ```bash
  grep -n "Trash2\|lucide-react" clip-factory/frontend/src/app/page.tsx | head -5
  ```
  If `Trash2` is NOT in the import, add it to the `lucide-react` import line.

- [ ] **Step 4: Add `deleteRenderedClip` handler to `page.tsx`**

  Find the `randomizeClipSeed` function (around line 784). Add after it:
  ```ts
  const deleteRenderedClip = async (clipIdx: number, e: React.MouseEvent) => {
    e.stopPropagation();
    const clip = results?.clips?.[clipIdx];
    if (!clip?.rendered_filename) return;
    const parts = (clip.rendered_filename as string).split("/");
    if (parts.length < 2) return;
    const videoId = parts[parts.length - 2];
    const filename = parts[parts.length - 1];
    if (!confirm(`Delete "${filename}"?\nThis removes it from Drive and cannot be undone.`)) return;
    try {
      const res = await fetch(`${apiBase}/api/clips/${videoId}/${encodeURIComponent(filename)}`, { method: "DELETE" });
      if (!res.ok) { alert("Delete failed — check Drive connection."); return; }
      setResults((prev: any) => {
        if (!prev) return prev;
        const clips = prev.clips.map((c: any, i: number) =>
          i === clipIdx ? { ...c, rendered_filename: undefined } : c
        );
        return { ...prev, clips };
      });
    } catch {
      alert("Delete failed — check Drive connection.");
    }
  };
  ```

- [ ] **Step 5: Add trash button to the clip card**

  In `page.tsx`, find the per-clip dice button block (around line 1179):
  ```tsx
  {/* PER-CLIP DICE — re-roll this clip's style */}
  <button
    onClick={(e) => randomizeClipSeed(clipIdx, e)}
    ...
  ```
  Add a trash button immediately after the dice button closing tag:
  ```tsx
  {/* DELETE RENDERED CLIP */}
  {results?.clips?.[clipIdx]?.rendered_filename && (
    <button
      onClick={(e) => deleteRenderedClip(clipIdx, e)}
      className="p-1.5 hover:bg-rose-50 rounded-lg border border-slate-200 text-slate-400 hover:text-rose-600 transition-colors shrink-0"
      title="Delete this rendered clip from Drive"
    >
      <Trash2 className="w-3.5 h-3.5" />
    </button>
  )}
  ```

- [ ] **Step 6: TypeScript build check**
  ```bash
  cd clip-factory/frontend && npm run build 2>&1 | tail -10
  ```
  Expected: `✓ Compiled successfully`

- [ ] **Step 7: Commit**
  ```bash
  cd clip-factory && git add server/main.py frontend/src/app/page.tsx
  git commit -m "feat: add per-clip delete endpoint + trash button in clip card UI"
  ```

---

## Self-Review

**Spec coverage:**
- ✅ Hook repetition fix (handoff #6) → Task 1 (examples + temperature)
- ✅ Temperature concern (handoff #8, owner objection to 0.70) → Task 1 (0.55 not 0.70; rationale documented)
- ✅ Layout full-screen bug (handoff #5) → Task 2 (portrait → box)
- ✅ Hook duration too short (handoff #4, seeds at 3s) → Tasks 2 + 5
- ✅ Font corruption fix (handoff item 2, incorrectly claimed done) → Task 3
- ✅ Log directory by video title with correct file names (handoff #1: "session log [title]", "llm log [title]") → Task 4
- ✅ Delete clips from UI (handoff #3) → Task 6
- ✅ Clip naming → confirmed already done at `clipper.py:754`, excluded correctly
- ✅ Anti-fingerprinting → correctly deferred (Phase 3)
- ✅ White background preference → `clean_white` seed already exists; no code change needed (aesthetic choice, not a bug)
- ✅ Nvidia API note (handoff #9) → informational only, no code change

**Placeholder scan:** None — all steps contain concrete code.

**Type consistency:** `video_title: str = ""` consistent across Task 4. `rendered_filename` field access in Task 6 matches `main.py:797` pattern. `Trash2` used from lucide-react (verify import in Step 3).
