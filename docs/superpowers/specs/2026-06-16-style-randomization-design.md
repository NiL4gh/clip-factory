# Style Randomization — Design Spec
_ClipFactory.ai · 2026-06-16_

## Problem

Every clip in a batch currently renders with the same global style. Social media algorithms
penalise batches of visually identical clips. The owner runs multiple accounts and needs clips
that look distinctly different from each other with zero manual fiddling.

## Decision: Frontend-only seed table (Approach 1)

All randomization logic lives in `page.tsx`. No backend changes. Randomized styles ride along
in the render request the same way manual per-clip overrides do today — the backend already
reads per-clip settings fields (`bg_style`, `caption_style`, `header_style`, etc.) unchanged.

Rejected alternative: backend assigns seeds during strategize (adds schema/parse complexity
for no real benefit — the 8B model cannot make meaningful style decisions).

---

## 6 Curated Seeds

Each seed is a complete style combination guaranteed to look good (no bad field combos).

| ID | Badge Label | layout_mode | bg_style | caption_style | hook_display | header_style | header_font | caption_font |
|---|---|---|---|---|---|---|---|---|
| `viral_stroke` | 🔥 Viral | box | brand | Pop | 3s | stroke | bebas | montserrat |
| `viral_dark` | 🌑 Dark Pop | box | black | Pop | 5s | card | bebas | montserrat |
| `clean_white` | ✨ Clean | box | white | Classic | off | card | montserrat black | poppins |
| `brand_minimal` | 🎯 Minimal | box | brand | Classic | 3s | card | inter | roboto |
| `blur_punch` | 💥 Punch | portrait | blur | Pop | 3s | stroke | bebas | montserrat |
| `cinematic` | 🎬 Cinematic | portrait | blur | CinematicSlate | off | card | inter | poppins |

Each seed also sets `hook_font = caption_font` (consistent with existing behaviour).

Fields **not** randomized: `remove_silence`, `bg_music_genre`, `face_center`, `hook_position`,
`show_outro` — these are functional, not stylistic.

---

## Behaviour

### Auto-assign on clip load

When the clip list populates after strategize completes, the app immediately shuffle-assigns
one seed per clip:

1. Shuffle the 6 seed IDs into a random order.
2. Cycle through clips in order, assigning seeds from the shuffled list (wrapping if clips > 6).
3. Enforce a **no-adjacent-duplicate** constraint: if a clip would get the same seed as the
   previous clip, swap it with the next seed in the list.
4. Write each assignment into the existing per-clip `clipSettings` map using `applySetting`.

This runs once automatically. The user sees badges immediately.

### "Randomize All" button

- Location: gallery controls bar, same row as the sort dropdown.
- Label: `🎲 Randomize All Styles`
- Action: re-runs the shuffle-assign algorithm above for every clip, replacing all current
  per-clip style overrides (including any the user manually changed since the last randomize).
- Intent: "start fresh" — wipes slate and re-deals.

### Per-clip dice button

- Location: top-right corner of each clip card, small icon button (`🎲`).
- Action: picks a random seed that is **different from the clip's current seed**, writes it
  to that clip's `clipSettings` entry.
- Does not affect any other clip.

### Badge on clip card

- Displayed as a small colored pill below the clip thumbnail.
- Shows the seed's emoji + label (e.g. `🌑 Dark Pop`).
- Each seed has a fixed badge color (set in the seed definition) so variety is visible
  at a glance across the whole batch without reading every label.

---

## Data structures

```ts
// Seed definition (added to page.tsx, alongside STYLE_PRESETS)
type StyleSeed = {
  id: string;
  label: string;       // shown in badge
  badgeColor: string;  // Tailwind bg class e.g. "bg-slate-800"
  changes: Record<string, string>;  // fields to write via applySetting
};

const STYLE_SEEDS: StyleSeed[] = [ /* 6 entries from table above */ ];

// Per-clip seed tracking (added to clipSettings state)
// clipSeedId[clipIndex] = seed id string (e.g. "viral_dark")
// Stored alongside existing clipSettings so badges can read it.
```

---

## Files changed

| File | Change |
|---|---|
| `frontend/src/app/page.tsx` | Add `STYLE_SEEDS` constant; add `clipSeedId` state; add `assignSeedsToClips()` helper; call it when clip list populates; add "Randomize All" button; add per-clip dice button + badge to clip card |

No other files change.

---

## Out of scope

- Phase 3 uniqueness layer (audio pitch, pixel mutation, metadata cleansing) — deferred per BACKLOG #44.
- Persisting seed assignments to Drive / session storage — seeds are ephemeral UI state; they
  are re-assigned on each strategize run. This is intentional (fresh batch = fresh styles).
- LLM-driven style selection — rejected above.
