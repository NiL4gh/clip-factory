# Style Randomization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically assign a distinct visual style to each clip when results load, with a "Randomize All Styles" button to reshuffle the batch and a per-clip dice button to re-roll individual clips. Each clip card shows a colored badge with its assigned style name.

**Architecture:** Frontend-only. Six hand-curated `STYLE_SEEDS` are added to `page.tsx` alongside the existing `STYLE_PRESETS`. A pure helper `assignSeedsToClips()` builds a shuffled, no-adjacent-duplicate mapping of clip index → seed ID. On clip load the existing `useEffect` that initialises `renderSettings` also runs `assignSeedsToClips` and merges each seed's fields into the per-clip settings map — so the randomized style rides along in the render request exactly like a manual per-clip override. A `clipSeedIds` state record drives badge rendering and re-roll logic.

**Tech Stack:** React 19, TypeScript 5, Tailwind CSS 4, Next.js 16. No new dependencies.

---

## File map

| File | Change |
|---|---|
| `frontend/src/app/page.tsx` | All changes — 6 additions, all isolated |

---

## Task 1 — Add StyleSeed type, STYLE_SEEDS constant, and assignSeedsToClips helper

**Files:**
- Modify: `frontend/src/app/page.tsx` — insert after line 123 (the closing `}` of `FONT_MAP`)

- [ ] **Step 1: Insert the StyleSeed type, STYLE_SEEDS array, and helper function**

Find this exact line (end of FONT_MAP block, around line 123):
```ts
  'poppins': 'Poppins'
};
```

Insert immediately after it (before `export default function Dashboard`):
```ts
/* ------------------------------------------------------------------ */
/*  Style Seeds — curated combinations for per-clip randomisation     */
/* ------------------------------------------------------------------ */
type StyleSeed = {
  id: string;
  label: string;
  badgeColor: string; // Tailwind classes for badge background + text + border
  changes: Record<string, string>;
};

const STYLE_SEEDS: StyleSeed[] = [
  {
    id: "viral_stroke",
    label: "🔥 Viral",
    badgeColor: "bg-orange-100 text-orange-700 border-orange-200",
    changes: { layout_mode: "box", bg_style: "brand", caption_style: "Pop", title_style: "Impact", hook_display: "3s", header_style: "stroke", header_font: "bebas", caption_font: "montserrat", hook_font: "montserrat" },
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
    changes: { layout_mode: "box", bg_style: "brand", caption_style: "Classic", title_style: "None", hook_display: "3s", header_style: "card", header_font: "inter", caption_font: "roboto", hook_font: "roboto" },
  },
  {
    id: "blur_punch",
    label: "💥 Punch",
    badgeColor: "bg-purple-100 text-purple-700 border-purple-200",
    changes: { layout_mode: "portrait", bg_style: "blur", caption_style: "Pop", title_style: "Impact", hook_display: "3s", header_style: "stroke", header_font: "bebas", caption_font: "montserrat", hook_font: "montserrat" },
  },
  {
    id: "cinematic",
    label: "🎬 Cinematic",
    badgeColor: "bg-rose-100 text-rose-700 border-rose-200",
    changes: { layout_mode: "portrait", bg_style: "blur", caption_style: "CinematicSlate", title_style: "None", hook_display: "off", header_style: "card", header_font: "inter", caption_font: "poppins", hook_font: "poppins" },
  },
];

/** Shuffle 6 seeds into a no-adjacent-duplicate assignment for `count` clips. */
function assignSeedsToClips(count: number): Record<number, string> {
  const ids = STYLE_SEEDS.map(s => s.id);
  const shuffle = (arr: string[]) => {
    const a = [...arr];
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  };
  // Build pool: repeated shuffles, fixing seam duplicates between cycles
  let pool: string[] = [];
  while (pool.length < count) {
    let next = shuffle(ids);
    if (pool.length > 0 && next[0] === pool[pool.length - 1]) {
      [next[0], next[1]] = [next[1], next[0]];
    }
    pool = pool.concat(next);
  }
  const result: Record<number, string> = {};
  for (let i = 0; i < count; i++) result[i] = pool[i];
  return result;
}
```

- [ ] **Step 2: Build-check (TypeScript only)**

```bash
cd clip-factory/frontend && npm run build 2>&1 | tail -20
```

Expected: `✓ Compiled successfully` (or same errors as before this task — no new type errors).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/page.tsx
git commit -m "feat: add STYLE_SEEDS constant and assignSeedsToClips helper"
```

---

## Task 2 — Add clipSeedIds state inside Dashboard

**Files:**
- Modify: `frontend/src/app/page.tsx` — state declarations block inside `Dashboard`

- [ ] **Step 1: Add clipSeedIds state**

Find this line (around line 178, end of the state block):
```ts
  const [galleryFilter, setGalleryFilter] = useState<"all" | "today" | "over30" | "under30">("all");
```

Insert immediately after it:
```ts
  const [clipSeedIds, setClipSeedIds] = useState<Record<number, string>>({});
```

- [ ] **Step 2: Build-check**

```bash
cd clip-factory/frontend && npm run build 2>&1 | tail -10
```

Expected: `✓ Compiled successfully`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/page.tsx
git commit -m "feat: add clipSeedIds state for per-clip style tracking"
```

---

## Task 3 — Auto-assign seeds when clip list populates

**Files:**
- Modify: `frontend/src/app/page.tsx` — the `useEffect` that initialises `renderSettings` (around line 320)

- [ ] **Step 1: Modify the existing useEffect**

Find this block (lines ~320–343):
```ts
  useEffect(() => {
    if (results?.clips?.length && results?.persona) {
      const base = {
        ...globalSettings,
        bg_music_genre: results.persona.suggested_bgm || "None",
      };
      const init: Record<number, typeof DEFAULT_SETTINGS> = {};
      results.clips.forEach((_: any, idx: number) => { init[idx] = { ...base }; });
      setRenderSettings(init);

      // Pre-select top 5 clips by composite score (clip.score or clip.virality_score)
      const sortedIdxs = results.clips
```

Replace the two lines:
```ts
      results.clips.forEach((_: any, idx: number) => { init[idx] = { ...base }; });
      setRenderSettings(init);
```

With:
```ts
      results.clips.forEach((_: any, idx: number) => { init[idx] = { ...base }; });

      // Auto-assign a distinct seed style to every clip
      const seedAssignment = assignSeedsToClips(results.clips.length);
      results.clips.forEach((_: any, idx: number) => {
        const seed = STYLE_SEEDS.find(s => s.id === seedAssignment[idx]);
        if (seed) init[idx] = { ...init[idx], ...(seed.changes as any) };
      });
      setRenderSettings(init);
      setClipSeedIds(seedAssignment);
```

- [ ] **Step 2: Build-check**

```bash
cd clip-factory/frontend && npm run build 2>&1 | tail -10
```

Expected: `✓ Compiled successfully`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/page.tsx
git commit -m "feat: auto-assign seed styles to clips on load"
```

---

## Task 4 — Add randomizeAllSeeds and randomizeClipSeed handlers

**Files:**
- Modify: `frontend/src/app/page.tsx` — after `applyPreset` function (around line 685)

- [ ] **Step 1: Insert the two handler functions**

Find this block (around line 680–685):
```ts
  const applyPreset = (presetKey: string) => {
    applySetting("template", presetKey);
    const preset = STYLE_PRESETS[presetKey];
    if (!preset) return;
    Object.entries(preset.changes).forEach(([k, v]) => applySetting(k, v));
  };
```

Insert immediately after it:
```ts
  const randomizeAllSeeds = () => {
    if (!results?.clips?.length) return;
    const seedAssignment = assignSeedsToClips(results.clips.length);
    setClipSeedIds(seedAssignment);
    setRenderSettings(prev => {
      const updated = { ...prev };
      results.clips.forEach((_: any, idx: number) => {
        const seed = STYLE_SEEDS.find(s => s.id === seedAssignment[idx]);
        if (seed) updated[idx] = { ...(updated[idx] || DEFAULT_SETTINGS), ...(seed.changes as any) };
      });
      return updated;
    });
  };

  const randomizeClipSeed = (clipIdx: number, e: React.MouseEvent) => {
    e.stopPropagation();
    const currentId = clipSeedIds[clipIdx];
    const others = STYLE_SEEDS.filter(s => s.id !== currentId);
    const newSeed = others[Math.floor(Math.random() * others.length)];
    setClipSeedIds(prev => ({ ...prev, [clipIdx]: newSeed.id }));
    setRenderSettings(prev => ({
      ...prev,
      [clipIdx]: { ...(prev[clipIdx] || DEFAULT_SETTINGS), ...(newSeed.changes as any) },
    }));
  };
```

- [ ] **Step 2: Build-check**

```bash
cd clip-factory/frontend && npm run build 2>&1 | tail -10
```

Expected: `✓ Compiled successfully`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/page.tsx
git commit -m "feat: add randomizeAllSeeds and randomizeClipSeed handlers"
```

---

## Task 5 — Add "Randomize All Styles" button to the controls bar

**Files:**
- Modify: `frontend/src/app/page.tsx` — clip controls bar, between the Sort dropdown and the Render All button (around line 868)

- [ ] **Step 1: Insert the Randomize All button**

Find this block (around line 868–878):
```tsx
                {/* BULK RENDER ALL BUTTON */}
                <button
                  onClick={renderAllClips}
```

Insert immediately before it:
```tsx
                {/* RANDOMIZE ALL STYLES BUTTON */}
                <button
                  onClick={randomizeAllSeeds}
                  disabled={!results?.clips?.length}
                  className="bg-white hover:bg-slate-50 disabled:opacity-40 border border-slate-200 text-slate-700 text-xs font-bold py-1.5 px-3 rounded-lg transition-all flex items-center gap-1.5 shadow-sm"
                  title="Shuffle a unique visual style onto every clip"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  Randomize Styles
                </button>
```

Note: `RefreshCw` is already imported at line 8 — no new import needed.

- [ ] **Step 2: Build-check**

```bash
cd clip-factory/frontend && npm run build 2>&1 | tail -10
```

Expected: `✓ Compiled successfully`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/page.tsx
git commit -m "feat: add Randomize All Styles button to controls bar"
```

---

## Task 6 — Add seed badge and per-clip dice button to clip cards

**Files:**
- Modify: `frontend/src/app/page.tsx` — inside the `sortedClips.map` block (around lines 957–1058)

This task has two sub-changes in the same clip card:
1. **Badge** on the right side of the title row
2. **Dice button** in the bottom actions row, to the left of the Render button

### 6a — Seed badge in the title row

- [ ] **Step 1: Add badge alongside the clip title**

Find this block (around lines 957–996) — the title row `div`:
```tsx
                          <div className="flex items-center justify-between gap-2">
                            {editingTitleIdx === clipIdx ? (
                              <input
```

The closing of this title row div ends with:
```tsx
                            )}
                          </div>
```

Replace the entire title row div with the version that adds the badge on the right:
```tsx
                          <div className="flex items-center justify-between gap-2">
                            {editingTitleIdx === clipIdx ? (
                              <input
                                type="text"
                                value={tempTitle}
                                onChange={(e) => setTempTitle(e.target.value)}
                                onBlur={() => {
                                  if (tempTitle.trim()) {
                                    setEditedTitles(prev => ({ ...prev, [clipIdx]: tempTitle.trim() }));
                                  }
                                  setEditingTitleIdx(null);
                                }}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') {
                                    if (tempTitle.trim()) {
                                      setEditedTitles(prev => ({ ...prev, [clipIdx]: tempTitle.trim() }));
                                    }
                                    setEditingTitleIdx(null);
                                  } else if (e.key === 'Escape') {
                                    setEditingTitleIdx(null);
                                  }
                                }}
                                onClick={(e) => e.stopPropagation()}
                                autoFocus
                                className="bg-slate-100 text-slate-900 text-xs font-bold px-2 py-0.5 rounded border border-indigo-500 w-full outline-none"
                              />
                            ) : (
                              <div
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setEditingTitleIdx(clipIdx);
                                  setTempTitle(editedTitles[clipIdx] || clip.title || "Untitled Clip");
                                }}
                                className="text-slate-800 font-bold text-xs hover:underline cursor-text hover:text-indigo-600 transition-colors truncate"
                                title="Click to edit title"
                              >
                                {editedTitles[clipIdx] || clip.title || "Untitled Clip"}
                              </div>
                            )}
                            {/* SEED STYLE BADGE */}
                            {clipSeedIds[clipIdx] && (() => {
                              const seed = STYLE_SEEDS.find(s => s.id === clipSeedIds[clipIdx]);
                              return seed ? (
                                <span className={`shrink-0 text-[9px] font-bold px-1.5 py-0.5 rounded-full border ${seed.badgeColor}`}>
                                  {seed.label}
                                </span>
                              ) : null;
                            })()}
                          </div>
```

### 6b — Per-clip dice button in the bottom actions row

- [ ] **Step 2: Add dice button next to the Render button**

Find this block (around lines 1050–1058):
```tsx
                          {/* RENDER BUTTON */}
                          <button
                            onClick={(e) => { e.stopPropagation(); renderClip(clipIdx); }}
                            disabled={status === "rendering"}
                            className="bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-300 text-white text-[10px] font-bold py-1.5 px-3 rounded-lg transition-all flex items-center gap-1 shadow-sm shrink-0"
                          >
                            <Zap className="w-3 h-3" />
                            Render
                          </button>
```

Replace with:
```tsx
                          {/* PER-CLIP DICE — re-roll this clip's style */}
                          <button
                            onClick={(e) => randomizeClipSeed(clipIdx, e)}
                            className="p-1.5 hover:bg-slate-100 rounded-lg border border-slate-200 text-slate-400 hover:text-indigo-600 transition-colors shrink-0"
                            title="Re-roll style for this clip"
                          >
                            <RefreshCw className="w-3.5 h-3.5" />
                          </button>
                          {/* RENDER BUTTON */}
                          <button
                            onClick={(e) => { e.stopPropagation(); renderClip(clipIdx); }}
                            disabled={status === "rendering"}
                            className="bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-300 text-white text-[10px] font-bold py-1.5 px-3 rounded-lg transition-all flex items-center gap-1 shadow-sm shrink-0"
                          >
                            <Zap className="w-3 h-3" />
                            Render
                          </button>
```

- [ ] **Step 3: Build-check**

```bash
cd clip-factory/frontend && npm run build 2>&1 | tail -20
```

Expected: `✓ Compiled successfully`. Fix any TypeScript errors before committing.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/page.tsx
git commit -m "feat: add seed badge and per-clip re-roll button to clip cards"
```

---

## Task 7 — Final verification

- [ ] **Step 1: Full build**

```bash
cd clip-factory/frontend && npm run build 2>&1
```

Expected: `✓ Compiled successfully` with no TypeScript errors.

- [ ] **Step 2: Spot-check the six changes in the file**

Run these greps to confirm all six pieces landed:

```bash
grep -n "STYLE_SEEDS\|assignSeedsToClips\|clipSeedIds\|randomizeAllSeeds\|randomizeClipSeed\|Randomize Styles\|seed\.badgeColor\|Re-roll style" frontend/src/app/page.tsx
```

Expected: at least one hit per term.

- [ ] **Step 3: Update BACKLOG.md**

Find the "New requests go below" section at the bottom of `BACKLOG.md` and add:

```markdown
| 65 | **Style randomization** — auto-assign + Randomize All + per-clip re-roll + badge | Done (code) | `page.tsx` only. 6 curated seeds. Auto-fires on clip load; Randomize All reshuffles batch; dice button per card. Not Colab-verified (visual). |
```

- [ ] **Step 4: Commit docs**

```bash
git add BACKLOG.md
git commit -m "docs: mark style randomization done in backlog"
```

---

## Verification checklist (for the next Colab run)

On the next real run, confirm:
- [ ] Clips load → each card immediately shows a colored badge (🔥 Viral, 🌑 Dark Pop, etc.)
- [ ] No two adjacent clip cards have the same badge
- [ ] "Randomize Styles" button in the controls bar reshuffles all badges + changes render settings
- [ ] The `🔄` dice button on a card re-rolls only that card's badge/style
- [ ] Rendering a clip uses its assigned seed style (not the global default)
