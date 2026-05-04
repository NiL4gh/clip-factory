"""
Local LLM highlight detection using llama-cpp-python.
Upgraded with elite virality prompting, angle-based regeneration,
cross-timestamp story stitching, and smarter clip scoring.
"""
import json
import re
from .logger import ui_logger

_llm_cache = {}
CHUNK_CHARS = 15_000
MIN_CLIP_SCORE = 45

# ── Virality Science ──────────────────────────────────────────────────────────
_VIRALITY_BASE = """You are an elite short-form content strategist for the Whop Content Rewards program.
Your goal is to extract clips that maximize view-based revenue by hitting high virality metrics.

WHOP VIRALITY SIGNALS (ranked by conversion power):

1. SCROLL-STOPPING HOOKS (The first 3 seconds)
   - Curiosity gaps: "The reason most people fail at X is..."
   - Bold/contrarian claims: "X is actually a scam, here's the truth."
   - Visual/Pattern interrupts: Start mid-action or with a shocking visual.

2. OPINION BOMBS & HOT TAKES (High shareability)
   - Statements that divide the audience.
   - Challenging conventional wisdom.
   - "Everyone is wrong about X" / "The secret no one tells you."

3. REVELATION & PROOF (High save rate)
   - Insider secrets or specific "how-to" steps.
   - Proof of results (numbers, stats, money).
   - "Aha!" moments where a complex idea becomes simple.

4. EMOTIONAL PEAKS
   - Genuine surprise, frustration, or breakthrough realizations.
   - High speaker energy or dramatic shifts in tone.

QUALITY RULES:
- Every clip MUST start with a hook that grabs attention in the first 3 seconds.
- Optimal duration: 45-75 seconds for TikTok/Reels performance.
- The clip MUST be standalone (zero external context required).
- NEVER clip mid-sentence at the start or end.
- Include a 5-second buffer mentally (start slightly earlier, end slightly later)."""

_ANGLE_INSTRUCTIONS = {
    "standard":
        "Extract the TOP most viral clips by OVERALL engagement potential across all virality signals.",
    "whop_rewards":
        "Focus EXCLUSIVELY on high-performance 'Content Rewards' clips: scandalous hot takes, "
        "insider money-making secrets, contrarian advice, and proof-of-results moments. "
        "These clips should be designed to generate massive view counts on TikTok/Reels.",
    "educational":
        "Focus EXCLUSIVELY on EDUCATIONAL moments — deep insights and 'aha!' moments.",
    "controversial":
        "Focus EXCLUSIVELY on CONTROVERSIAL moments that will generate comment wars.",
    "motivational":
        "Focus EXCLUSIVELY on MOTIVATIONAL breakthroughs and mindset shifts.",
    "storytelling":
        "Focus EXCLUSIVELY on STORY-DRIVEN moments with clear tension and resolution.",
}

_STITCH_CRITERIA = """
Find STORY CONNECTIONS between DISTANT timestamps that form a MORE POWERFUL clip when stitched
together than either part alone.

Connection types (ranked by viral potential):
1. Q&A BRIDGE: Compelling question asked early + detailed answer revealed much later
2. CLAIM -> PROOF: Bold claim stated early + specific evidence provided later
3. SETUP -> PAYOFF: Problem/situation introduced + the resolution/punchline comes later
4. BEFORE -> AFTER: "Before" state described + the transformation result revealed

Rules for valid connections:
- Combined duration of ALL segments: 30-90 seconds total
- Each individual segment: minimum 10 seconds
- Maximum 2 segments per stitched clip
- First segment MUST open with a strong hook
- The transition must feel natural when stitched — same topic thread throughout
- The timestamps must be at least 60 seconds apart (otherwise just use a single clip)"""


def _get_llm(llm_path: str, gpu_layers: int = 35):
    from llama_cpp import Llama
    if llm_path not in _llm_cache:
        ui_logger.log("Loading local LLM model...")
        _llm_cache[llm_path] = Llama(
            model_path=llm_path,
            n_gpu_layers=gpu_layers,
            n_ctx=0,
            verbose=False,
        )
        ui_logger.log("LLM loaded into memory.")
    return _llm_cache[llm_path]


def _parse_json_loose(raw: str):
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    for pattern in (r"\[.*\]", r"\{.*\}"):
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                continue
    try:
        return json.loads(text)
    except:
        return []


def _query_llm(llm, system: str, prompt: str) -> list:
    resp = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.25,
        max_tokens=3000,
    )
    raw = resp["choices"][0]["message"]["content"].strip()
    parsed = _parse_json_loose(raw)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return parsed.get("highlights", parsed.get("clips", [parsed]))
    return []


def _refine_clip(llm, system: str, schema: str, clip: dict, lines: list) -> dict:
    st = float(clip.get("start_time", 0))
    et = float(clip.get("end_time", 0))
    clip_text = [
        line for line in lines
        if (m := re.match(r'^\[([\d\.]+)s\]', line.strip()))
        and st - 10 <= float(m.group(1)) <= et + 10
    ]
    if not clip_text:
        return clip

    ui_logger.log(f"Refining clip '{clip.get('title', 'Untitled')}' ({int(et-st)}s) → targeting 45-75s...")
    prompt = (
        f"{_VIRALITY_BASE}\n\n"
        f"This segment is {int(et-st)}s — too long. Extract the SINGLE best 45-75 second sub-clip.\n"
        f"It MUST be under 90 seconds. It MUST start with the strongest possible hook.\n\n"
        f"Segment:\n" + "\n".join(clip_text) + f"\n\nRespond ONLY with a JSON array of ONE element:\n{schema}"
    )
    try:
        results = _query_llm(llm, system, prompt)
        if results:
            nc = results[0]
            if 15 <= float(nc.get("end_time", 0)) - float(nc.get("start_time", 0)) <= 120:
                nc.setdefault("title", clip.get("title", "Refined Clip"))
                return nc
    except Exception as e:
        ui_logger.log(f"Refinement failed: {e}")
    return clip


def _build_text(transcript_data) -> tuple:
    """Returns (text_for_llm, raw_word_list)."""
    if isinstance(transcript_data, list):
        words = transcript_data
        lines = []
        for i in range(0, len(words), 15):
            group = words[i:i+15]
            if group:
                lines.append(f"[{group[0]['start']:.1f}s] {' '.join(w['word'] for w in group)}")
        return "\n".join(lines), words
    if isinstance(transcript_data, dict):
        segs = transcript_data.get("segments", [])
        return "\n".join(f"[{s['start']:.1f}s] {s['text'].strip()}" for s in segs), []
    if isinstance(transcript_data, tuple):
        return transcript_data[0], []
    return str(transcript_data), []


def get_highlights(
    transcript_data,
    num_clips: int = 5,
    llm_path: str = "",
    gpu_layers: int = 35,
    max_clips: int = 20,
    language: str = "",
    angle: str = "standard",
) -> dict:
    text, raw_words = _build_text(transcript_data)

    if not llm_path:
        raise RuntimeError("llm_path is required for local highlight detection.")

    llm = _get_llm(llm_path, gpu_layers)
    
    if angle in _ANGLE_INSTRUCTIONS:
        angle_instruction = _ANGLE_INSTRUCTIONS[angle]
    else:
        angle_instruction = f"CUSTOM STRATEGY: {angle}"
        
    lang_hint = f" Transcript language: {language}." if language else ""

    system = (
        "You are an elite AI director for TikTok, Instagram Reels, and YouTube Shorts."
        f"{lang_hint} Output ONLY raw JSON arrays. No prose, no markdown, no explanation whatsoever."
    )

    schema = (
        '[\n'
        '  {\n'
        '    "title": "Punchy curiosity-driving title (max 10 words)",\n'
        '    "start_time": 12.5,\n'
        '    "end_time": 75.0,\n'
        '    "score": 92,\n'
        '    "hook_sentence": "The exact opening sentence that will stop the scroll",\n'
        '    "virality_reason": "Specific reason this will go viral (name the signal type)",\n'
        '    "hook_type": "curiosity_gap|bold_claim|controversy|revelation|story_arc|quotable",\n'
        '    "peak_moment": 45.0,\n'
        '    "thumbnail_moment": 38.0,\n'
        '    "theme": "Educational|Motivation|Comedy|Suspense|Storytime",\n'
        '    "broll_keywords": [{"start_time": 15.0, "keyword": "rocket launch"}],\n'
        '    "emoji_moments": [{"start_time": 20.0, "emoji_unicode": "🚀"}]\n'
        '  }\n'
        ']'
    )

    chunks = [text[i:i + CHUNK_CHARS] for i in range(0, max(len(text), 1), CHUNK_CHARS)]
    # Ceiling division so we always hit or exceed num_clips target
    target = min(max_clips, max(num_clips, 5))
    clips_per_chunk = max(3, -(-target // max(1, len(chunks))))

    all_highlights = []
    lines = text.split('\n')

    for idx, chunk in enumerate(chunks):
        ui_logger.log(f"LLM analysing chunk {idx + 1}/{len(chunks)} — targeting {clips_per_chunk} clips...")
        prompt = (
            f"{_VIRALITY_BASE}\n\n"
            f"ANGLE: {angle_instruction}\n\n"
            f"CRITICAL REQUIREMENT: Return EXACTLY {clips_per_chunk} clips. "
            f"If this section lacks standout moments, include the best available content — "
            f"returning fewer than {clips_per_chunk} clips is unacceptable.\n\n"
            f"Transcript:\n{chunk}\n\n"
            f"Respond ONLY with a JSON array of exactly {clips_per_chunk} clips:\n{schema}"
        )
        try:
            results = _query_llm(llm, system, prompt)
            all_highlights.extend(results)
        except Exception as e:
            ui_logger.log(f"Warning: chunk {idx + 1} failed — {e}")

    ui_logger.log(f"LLM extracted {len(all_highlights)} raw candidates. Scoring and filtering...")

    valid = []
    for h in all_highlights:
        try:
            st = float(h.get("start_time", 0))
            et = float(h.get("end_time", 0))
            dur = et - st
            score = max(0, min(100, int(h.get("score", 50))))

            # Refine clips that are too long
            if dur > 90:
                h = _refine_clip(llm, system, schema, h, lines)
                st = float(h.get("start_time", 0))
                et = float(h.get("end_time", 0))
                dur = et - st

            if dur < 15:
                continue

            # Validate and normalise theme
            theme = h.get("theme", "Storytime")
            if theme not in ["Motivation", "Educational", "Comedy", "Suspense", "Storytime"]:
                theme = "Storytime"

            h["duration"] = dur
            h["score"] = score
            h["theme"] = theme
            h["peak_moment"] = float(h.get("peak_moment", st + dur / 2))
            h["thumbnail_moment"] = float(h.get("thumbnail_moment", h["peak_moment"]))
            h["hook_type"] = h.get("hook_type", "story_arc")
            h.setdefault("broll_keywords", [])
            h.setdefault("emoji_moments", [])
            valid.append(h)
        except (ValueError, TypeError, KeyError):
            continue

    valid.sort(key=lambda x: x["score"], reverse=True)

    # Dedup: 15-second window
    seen, deduped = set(), []
    for h in valid:
        key = int(h["start_time"] // 15)
        if key not in seen:
            seen.add(key)
            deduped.append(h)

    # Ensure we return at least the requested number if we have them
    final = deduped[:target]
    ui_logger.log(f"Done. {len(final)} top clips identified (angle: {angle}).")
    return {"highlights": final}


def get_stitched_clips(
    transcript_data,
    llm_path: str = "",
    gpu_layers: int = 35,
    max_stitched: int = 5,
    language: str = "",
) -> dict:
    """
    Second LLM pass: find Q&A / Setup-Payoff / Claim-Proof pairs across
    distant timestamps and return them as multi-segment clips for stitching.
    """
    text, _ = _build_text(transcript_data)

    if not llm_path:
        raise RuntimeError("llm_path is required.")

    llm = _get_llm(llm_path, gpu_layers)
    lang_hint = f" Transcript language: {language}." if language else ""

    system = (
        "You are an elite viral content strategist specializing in story stitching for short-form video."
        f"{lang_hint} Output ONLY raw JSON arrays."
    )

    stitch_schema = (
        '[\n'
        '  {\n'
        '    "title": "Punchy title for the stitched story (max 10 words)",\n'
        '    "clip_type": "qa_pair|claim_proof|setup_payoff|before_after",\n'
        '    "segments": [\n'
        '      {"start_time": 65.0, "end_time": 95.0, "role": "question"},\n'
        '      {"start_time": 640.0, "end_time": 690.0, "role": "answer"}\n'
        '    ],\n'
        '    "score": 88,\n'
        '    "hook_sentence": "The exact first sentence of the first segment",\n'
        '    "virality_reason": "Why this connection makes a powerful clip",\n'
        '    "theme": "Educational|Motivation|Comedy|Suspense|Storytime",\n'
        '    "peak_moment": 670.0,\n'
        '    "thumbnail_moment": 670.0,\n'
        '    "broll_keywords": [],\n'
        '    "emoji_moments": []\n'
        '  }\n'
        ']'
    )

    # For stitching we need the full transcript context — use first 30K chars
    full_text = text[:30000]
    ui_logger.log(f"Scanning for cross-timestamp story connections...")

    prompt = (
        f"{_STITCH_CRITERIA}\n\n"
        f"TASK: Find the {max_stitched} most powerful story connections in this transcript. "
        f"Only return connections where the combined clip will be MORE engaging than either "
        f"timestamp alone. Each connection MUST span timestamps at least 60 seconds apart.\n\n"
        f"Transcript:\n{full_text}\n\n"
        f"Respond ONLY with a JSON array:\n{stitch_schema}"
    )

    try:
        results = _query_llm(llm, system, prompt)
    except Exception as e:
        ui_logger.log(f"Stitch analysis failed: {e}")
        return {"highlights": []}

    valid = []
    for h in results:
        try:
            segs = h.get("segments", [])
            if len(segs) < 2:
                continue
            total_dur = sum(
                float(s.get("end_time", 0)) - float(s.get("start_time", 0))
                for s in segs
            )
            # Validate timestamps are far apart
            span = float(segs[-1].get("start_time", 0)) - float(segs[0].get("end_time", 0))
            if total_dur < 20 or total_dur > 95 or span < 60:
                continue

            # Compute start/end from segments for compatibility
            h["start_time"] = float(segs[0]["start_time"])
            h["end_time"] = float(segs[-1]["end_time"])
            h["duration"] = total_dur
            h["score"] = max(0, min(100, int(h.get("score", 75))))
            h["is_stitched"] = True

            theme = h.get("theme", "Educational")
            if theme not in ["Motivation", "Educational", "Comedy", "Suspense", "Storytime"]:
                theme = "Educational"
            h["theme"] = theme
            h["peak_moment"] = float(h.get("peak_moment", segs[-1].get("start_time", 0)))
            h["thumbnail_moment"] = float(h.get("thumbnail_moment", h["peak_moment"]))
            h.setdefault("broll_keywords", [])
            h.setdefault("emoji_moments", [])
            valid.append(h)
        except (ValueError, TypeError, KeyError):
            continue

    valid.sort(key=lambda x: x["score"], reverse=True)
    ui_logger.log(f"Found {len(valid)} valid story connections.")
    return {"highlights": valid}


# backwards-compat alias
get_viral_clips = get_highlights
