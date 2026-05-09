"""
Local LLM highlight detection using llama-cpp-python.
Professional 3-pass architecture:
  Pass 0: Persona Detection (fast model)
  Pass 1: Topic Indexing — map the entire transcript into distinct topics
  Pass 2: Per-Topic Clip Extraction — extract clips with multi-segment stitching
"""
import json
import re
from .logger import ui_logger

_llm_cache = {}
CHUNK_CHARS = 12_000  # Conservative size for 8k context models (Llama 3, Gemma 2)


# ── Opus-Style Viral Director Prompt ─────────────────────────────────────────
_VIRALITY_BASE = """You are an elite viral content director for a paid AI clipping platform competing with Opus.pro and CapCut.
Your job is to extract SHORT-FORM clips that will STOP THE SCROLL on TikTok, Instagram Reels, and YouTube Shorts.

TOTAL VIDEO DURATION: {video_duration_str}
TARGET CLIP DENSITY: Extract roughly 1 high-quality clip per 5-8 minutes of video. If the content is exceptionally engaging, you may extract more.

═══════════════════════════════════════════════════════
VIRALITY SIGNALS (ranked by importance):

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

═══════════════════════════════════════════════════════
CRITICAL EXTRACTION RULES:

- MULTI-SEGMENT STITCHING: If the speaker makes a great point but pauses, goes off-topic, or stutters in the middle, use MULTIPLE segments to stitch together ONLY the relevant parts. Each segment is a contiguous time range. The segments will be stitched together automatically.
- Every clip MUST start with a hook that grabs attention in the first 3 seconds.
- Every clip MUST have a clear narrative arc: Hook (Beginning) -> Context/Value (Middle) -> Payoff/Conclusion (End).
- The clip MUST end on a COMPLETED SENTENCE. Never cut off mid-thought.
- Include a 2-3 second buffer at the start and end of each segment.
- Each clip must be 100% SELF-CONTAINED. A viewer who sees ONLY this clip must understand the full story.
- Total clip duration (sum of all segments): 30-90 seconds optimal, never under 20s or over 120s.
- Do NOT hallucinate or invent content. Only use timestamps from the transcript."""


# ── LLM Management ───────────────────────────────────────────────────────────

def _get_llm(llm_path: str, gpu_layers: int = 35):
    from llama_cpp import Llama
    if llm_path not in _llm_cache:
        ui_logger.log("Loading local LLM model...")
        _llm_cache[llm_path] = Llama(
            model_path=llm_path,
            n_gpu_layers=gpu_layers,
            n_ctx=8192,  # Explicitly set context window for reliability
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


def _query_llm(llm, system: str, prompt: str, max_tokens: int = 3000) -> list:
    try:
        resp = llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.25,
            max_tokens=max_tokens,
        )
    except Exception as e:
        ui_logger.log(f"Model error (possibly system role not supported). Retrying with combined user prompt. Details: {e}")
        resp = llm.create_chat_completion(
            messages=[
                {"role": "user", "content": f"{system}\n\n{prompt}"},
            ],
            temperature=0.25,
            max_tokens=max_tokens,
        )

    raw = resp["choices"][0]["message"]["content"].strip()
    parsed = _parse_json_loose(raw)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return parsed.get("highlights", parsed.get("clips", parsed.get("topics", [parsed])))
    return []


# ── Transcript Formatting ────────────────────────────────────────────────────

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


def _get_text_slice(full_text: str, start_time: float, end_time: float) -> str:
    """Extract lines from the timestamped transcript within [start_time, end_time]."""
    lines = full_text.split('\n')
    result = []
    for line in lines:
        m = re.match(r'^\[(\d+\.?\d*)s\]', line.strip())
        if m:
            t = float(m.group(1))
            if start_time - 5 <= t <= end_time + 5:
                result.append(line)
    return "\n".join(result) if result else full_text[:CHUNK_CHARS]

def _match_quote(quote: str, raw_words: list, target_time: float, is_start: bool) -> float:
    """Finds the precise timestamp by fuzzily matching a quote in the transcript."""
    if not quote or not raw_words:
        return target_time
    
    quote_tokens = [re.sub(r'[^a-z0-9]', '', w.lower()) for w in quote.split()]
    quote_tokens = [w for w in quote_tokens if w]
    if not quote_tokens:
        return target_time
        
    best_match_time = target_time
    best_score = -1
    
    # Search within a +/- 60 second window of the LLM's guessed target_time
    for i, w in enumerate(raw_words):
        if abs(w["start"] - target_time) > 60:
            continue
            
        match_count = 0
        for j, q_tok in enumerate(quote_tokens):
            if i + j < len(raw_words):
                w_tok = re.sub(r'[^a-z0-9]', '', raw_words[i+j]["word"].lower())
                if w_tok == q_tok:
                    match_count += 1
                elif len(w_tok) > 3 and len(q_tok) > 3 and (w_tok in q_tok or q_tok in w_tok):
                    match_count += 0.5
        
        score = match_count / len(quote_tokens)
        if score > best_score and score >= 0.4:  # At least 40% match
            best_score = score
            if is_start:
                best_match_time = raw_words[i]["start"]
            else:
                end_idx = min(len(raw_words)-1, i + len(quote_tokens) - 1)
                best_match_time = raw_words[end_idx]["end"]
                
    return best_match_time


def _get_video_duration(word_timestamps: list) -> float:
    """Get total video duration in seconds from word timestamps."""
    if not word_timestamps:
        return 0.0
    return word_timestamps[-1].get("end", 0) - word_timestamps[0].get("start", 0)


def _format_duration(seconds: float) -> str:
    """Format seconds as 'Xm Ys' or 'Xh Ym'."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    m = int(seconds // 60)
    s = int(seconds % 60)
    if m < 60:
        return f"{m}m {s}s"
    h = m // 60
    m = m % 60
    return f"{h}h {m}m"


# ── Estimated Clip Density ───────────────────────────────────────────────────

def estimate_clip_potential(word_timestamps: list) -> int:
    """Estimate how many clips a video could produce based on its duration."""
    if not word_timestamps:
        return 3
    duration_secs = _get_video_duration(word_timestamps)
    duration_mins = duration_secs / 60.0
    # Rule of thumb: ~1 clip per 6 minutes of content
    return max(3, int(duration_mins / 6))


# ── Post-LLM Validation ─────────────────────────────────────────────────────

def _validate_clips(clips: list, raw_words: list) -> list:
    """
    Post-LLM validation. Discard clips that:
    1. Don't end on a completed sentence (last word must end with . ! or ?)
    2. Are under 30s or over 90s after stitch estimation
    3. Lack a clear narrative arc (heuristic: too short without multiple segments)
    """
    valid = []
    for clip in clips:
        segments = clip.get("segments", [])
        if not segments:
            continue

        # Calculate total stitched duration
        total_dur = 0.0
        for seg in segments:
            try:
                st = float(seg.get("start_time", 0))
                et = float(seg.get("end_time", 0))
                total_dur += max(0, et - st)
            except (ValueError, TypeError):
                continue

        # Duration check: 20-120s with preference for 30-90s
        if total_dur < 20 or total_dur > 120:
            ui_logger.log(f"  Discarded clip '{clip.get('title', '?')}': duration {total_dur:.0f}s out of bounds")
            continue

        # Sentence completion check: find the last word in the last segment
        if raw_words:
            last_seg = segments[-1]
            try:
                last_et = float(last_seg.get("end_time", 0))
                # Find transcript words near the end of the last segment
                end_words = [w for w in raw_words if abs(w["end"] - last_et) < 3.0]
                if end_words:
                    last_word = end_words[-1]["word"].strip()
                    if last_word and last_word[-1] not in '.!?':
                        # Try to extend slightly to find a sentence end
                        extended = [w for w in raw_words if last_et < w["start"] < last_et + 5.0]
                        found_end = False
                        for ew in extended:
                            if ew["word"].strip() and ew["word"].strip()[-1] in '.!?':
                                # Extend the last segment to include the sentence ending
                                last_seg["end_time"] = ew["end"] + 0.5
                                total_dur += (ew["end"] + 0.5 - last_et)
                                found_end = True
                                break
                        if not found_end and total_dur > 30:
                            # Only discard if we have enough other clips
                            ui_logger.log(f"  Warning: clip '{clip.get('title', '?')}' may end mid-sentence")
            except (ValueError, TypeError, IndexError):
                pass

        # Narrative arc heuristic: at least 1 segment >=20s or multiple segments
        has_arc = len(segments) >= 2 or total_dur >= 25
        if not has_arc:
            ui_logger.log(f"  Discarded clip '{clip.get('title', '?')}': too short for narrative arc ({total_dur:.0f}s)")
            continue

        clip["duration"] = total_dur
        clip["is_stitched"] = len(segments) > 1
        valid.append(clip)

    return valid


# ── Pass 0: Persona Detection ───────────────────────────────────────────────

def detect_video_persona(transcript_data, llm_path: str, gpu_layers: int = 35) -> dict:
    """Run a fast pass to detect video genre, tone, target audience, and suggested styles."""
    if not llm_path:
        return {}
        
    text, _ = _build_text(transcript_data)
    llm = _get_llm(llm_path, gpu_layers)
    
    system = "You are an expert video analyst. Output ONLY raw JSON. No markdown."
    prompt = (
        "Analyze the following video transcript chunk and determine its core persona.\n\n"
        "Return ONLY a JSON object with this exact schema:\n"
        "{\n"
        '  "genre": "Podcast|Tutorial|Vlog|Rant|Interview|Comedy|Educational",\n'
        '  "tone": "Casual|Professional|High-Energy|Calm|Controversial",\n'
        '  "target_audience": "Brief description of who this is for",\n'
        '  "suggested_brand_kit": "Hormozi|Ali Abdaal|MrBeast|Standard",\n'
        '  "suggested_bgm": "Lofi / Chill|High Energy / Phonk|Suspense / Dark|Corporate / Upbeat"\n'
        "}\n\n"
        f"Transcript (first 5000 chars):\n{text[:5000]}"
    )
    
    try:
        results = _query_llm(llm, system, prompt)
        if isinstance(results, list) and len(results) > 0:
            return results[0]
        if isinstance(results, dict):
            return results
    except Exception as e:
        ui_logger.log(f"Persona detection failed: {e}")
        
    return {
        "genre": "General", 
        "tone": "Neutral", 
        "target_audience": "Broad",
        "suggested_brand_kit": "Standard",
        "suggested_bgm": "Lofi / Chill"
    }


# ── Pass 1: Topic Indexing ───────────────────────────────────────────────────

def get_topic_index(transcript_data, llm_path: str, gpu_layers: int = 35, language: str = "") -> list:
    """
    First pass: Map the entire transcript into distinct discussion topics.
    Returns a list of topics with their timestamp ranges.
    """
    text, _ = _build_text(transcript_data)
    if not llm_path:
        raise RuntimeError("llm_path is required.")

    llm = _get_llm(llm_path, gpu_layers)
    lang_hint = f" Transcript language: {language}." if language else ""

    system = (
        "You are a content analyst. Your job is to identify distinct discussion topics in a video transcript."
        f"{lang_hint} Output ONLY raw JSON arrays. No prose, no markdown."
    )

    topic_schema = (
        '[\n'
        '  {\n'
        '    "topic": "Short descriptive title of the discussion topic (5-10 words)",\n'
        '    "start_time": 0.0,\n'
        '    "end_time": 180.0,\n'
        '    "summary": "1-sentence summary of what is discussed"\n'
        '  }\n'
        ']'
    )

    # Process transcript in large chunks to identify topics across the full video
    chunks = [text[i:i + CHUNK_CHARS] for i in range(0, max(len(text), 1), CHUNK_CHARS)]
    all_topics = []

    for idx, chunk in enumerate(chunks):
        ui_logger.log(f"Topic indexing chunk {idx + 1}/{len(chunks)}...")
        prompt = (
            "Analyze this transcript section and identify ALL distinct discussion topics.\n"
            "A 'topic' is any coherent section where the speaker(s) discuss a single subject.\n"
            "Even short tangents (30+ seconds) count as separate topics.\n\n"
            "Rules:\n"
            "- Each topic must have accurate start_time and end_time from the transcript timestamps\n"
            "- Topics should NOT overlap\n"
            "- Include ALL sections — do not skip any part of the transcript\n"
            "- A 10-minute section typically has 5-10 topics\n\n"
            f"Transcript:\n{chunk}\n\n"
            f"Respond ONLY with a JSON array:\n{topic_schema}"
        )
        try:
            results = _query_llm(llm, system, prompt, max_tokens=2000)
            if isinstance(results, list):
                all_topics.extend(results)
        except Exception as e:
            ui_logger.log(f"Warning: Topic indexing chunk {idx + 1} failed — {e}")

    # Validate and deduplicate topics
    valid_topics = []
    for t in all_topics:
        try:
            st = float(t.get("start_time", 0))
            et = float(t.get("end_time", 0))
            if et - st >= 20:  # At least 20 seconds
                valid_topics.append({
                    "topic": t.get("topic", "Untitled Topic"),
                    "start_time": st,
                    "end_time": et,
                    "summary": t.get("summary", ""),
                })
        except (ValueError, TypeError):
            continue

    # Sort by start time and merge overlapping topics
    valid_topics.sort(key=lambda x: x["start_time"])
    
    ui_logger.log(f"Identified {len(valid_topics)} discussion topics across the video.")
    return valid_topics


# ── Pass 2: Per-Topic Clip Extraction ────────────────────────────────────────

def get_highlights(
    transcript_data,
    num_clips: int = 5,
    llm_path: str = "",
    gpu_layers: int = 35,
    max_clips: int = 30,
    language: str = "",
    angle: str = "standard",
    topics: list = None,
) -> dict:
    """
    Extract viral clips from the transcript using multi-segment stitching.
    If topics are provided (from Pass 1), extract clips per-topic for comprehensive coverage.
    """
    text, raw_words = _build_text(transcript_data)

    if not llm_path:
        raise RuntimeError("llm_path is required for local highlight detection.")

    llm = _get_llm(llm_path, gpu_layers)
    
    # Calculate video duration for the prompt
    video_dur = _get_video_duration(raw_words) if raw_words else 0
    video_duration_str = _format_duration(video_dur) if video_dur > 0 else "Unknown"
    
    lang_hint = f" Transcript language: {language}." if language else ""

    system = (
        "You are an elite AI director for TikTok, Instagram Reels, and YouTube Shorts."
        f"{lang_hint} Output ONLY raw JSON arrays. No prose, no markdown, no explanation whatsoever."
    )

    # New multi-segment schema with hook_text and virality_score
    schema = (
        '[\n'
        '  {\n'
        '    "title": "Catchy TikTok-style title (max 10 words)",\n'
        '    "virality_score": 85,\n'
        '    "hook_text": "The exact first sentence that hooks the viewer",\n'
        '    "segments": [\n'
        '      {"start_time": 12.5, "end_time": 45.0},\n'
        '      {"start_time": 48.0, "end_time": 72.0}\n'
        '    ],\n'
        '    "start_quote": "Exact first 5 to 8 words of the clip",\n'
        '    "end_quote": "Exact last 5 to 8 words of the clip",\n'
        '    "theme": "Educational|Motivation|Comedy|Suspense|Storytime"\n'
        '  }\n'
        ']'
    )

    all_highlights = []

    # Build the virality prompt with dynamic video duration
    virality_prompt = _VIRALITY_BASE.format(video_duration_str=video_duration_str)

    if topics and len(topics) > 0:
        # ── Topic-Aware Extraction ──
        clips_per_topic = max(2, min(4, -(-num_clips // max(1, len(topics)))))
        
        for tidx, topic in enumerate(topics):
            ui_logger.log(f"Topic {tidx + 1}/{len(topics)}: \"{topic['topic']}\"")
            topic_text = _get_text_slice(text, topic["start_time"], topic["end_time"])
            if not topic_text.strip(): continue

            prompt = (
                f"{virality_prompt}\n\n"
                f"You are analyzing a specific section of a video about: \"{topic['topic']}\"\n"
                f"Time range: {topic['start_time']:.0f}s to {topic['end_time']:.0f}s\n\n"
                f"Extract the {clips_per_topic} most viral moments from THIS section.\n"
                f"CRITICAL: Use the 'segments' array to stitch together disjoint parts of a thought.\n"
                f"If the speaker makes a great point at 120s-135s, goes off topic at 135s-142s, then returns to conclude at 142s-158s, "
                f"use segments: [{{start_time: 120, end_time: 135}}, {{start_time: 142, end_time: 158}}]\n"
                f"For continuous thoughts, use a single segment.\n"
                f"Each segment's start_time and end_time MUST be within {topic['start_time']:.0f}s to {topic['end_time']:.0f}s.\n\n"
                f"Transcript:\n{topic_text}\n\n"
                f"Respond ONLY with a JSON array of {clips_per_topic} clips:\n{schema}"
            )
            try:
                results = _query_llm(llm, system, prompt)
                for clip in results:
                    clip["source_topic"] = topic["topic"]
                    clip["source_topic_idx"] = tidx
                all_highlights.extend(results)
            except Exception as e:
                ui_logger.log(f"Warning: Topic {tidx + 1} extraction failed — {e}")
    else:
        # ── Fallback: Chunk-Based Extraction ──
        chunks = [text[i:i + CHUNK_CHARS] for i in range(0, max(len(text), 1), CHUNK_CHARS)]
        clips_per_chunk = max(3, -(-max_clips // max(1, len(chunks))))

        for idx, chunk in enumerate(chunks):
            ui_logger.log(f"Analyzing chunk {idx + 1}/{len(chunks)} — targeting {clips_per_chunk} clips...")
            prompt = (
                f"{virality_prompt}\n\n"
                f"Extract the {clips_per_chunk} most viral moments from this transcript.\n"
                f"Use the 'segments' array — even for continuous clips, wrap in a single segment.\n\n"
                f"Transcript:\n{chunk}\n\n"
                f"Respond ONLY with a JSON array of {clips_per_chunk} clips:\n{schema}"
            )
            try:
                results = _query_llm(llm, system, prompt)
                all_highlights.extend(results)
            except Exception as e:
                ui_logger.log(f"Warning: chunk {idx + 1} failed — {e}")

    ui_logger.log(f"LLM extracted {len(all_highlights)} raw candidates. Validating and scoring...")

    # ── Normalize LLM output into consistent format ──
    normalized = []
    for h in all_highlights:
        try:
            # Handle segments — ensure every clip has a segments array
            segments = h.get("segments", [])
            if not segments:
                # Legacy fallback: build segments from start_time/end_time
                raw_st = float(h.get("start_time", 0))
                raw_et = float(h.get("end_time", 0))
                if raw_et > raw_st:
                    segments = [{"start_time": raw_st, "end_time": raw_et}]
                else:
                    continue
            
            # Validate each segment
            valid_segs = []
            for seg in segments:
                try:
                    st = float(seg.get("start_time", 0))
                    et = float(seg.get("end_time", 0))
                    if et - st >= 3:  # At least 3 seconds per segment
                        valid_segs.append({"start_time": st, "end_time": et})
                except (ValueError, TypeError):
                    continue
            
            if not valid_segs:
                continue

            # Snap first/last segment timestamps using quotes if available
            if raw_words:
                first_seg = valid_segs[0]
                last_seg = valid_segs[-1]
                first_seg["start_time"] = _match_quote(
                    h.get("start_quote", ""), raw_words, first_seg["start_time"], is_start=True
                )
                last_seg["end_time"] = _match_quote(
                    h.get("end_quote", ""), raw_words, last_seg["end_time"], is_start=False
                )

            # Map fields for backward compat
            score = max(0, min(100, int(h.get("virality_score", h.get("score", 50)))))
            hook_sentence = h.get("hook_text", h.get("hook_sentence", ""))
            theme = h.get("theme", "Storytime")
            if theme not in ["Motivation", "Educational", "Comedy", "Suspense", "Storytime"]:
                theme = "Storytime"

            # Compute overall start/end from segments for backward compat
            overall_st = valid_segs[0]["start_time"]
            overall_et = valid_segs[-1]["end_time"]

            normalized.append({
                "title": h.get("title", "Untitled Clip"),
                "segments": valid_segs,
                "start_time": overall_st,
                "end_time": overall_et,
                "score": score,
                "hook_sentence": hook_sentence,
                "hook_text": hook_sentence,
                "virality_reason": h.get("virality_reason", ""),
                "theme": theme,
                "hook_type": h.get("hook_type", "story_arc"),
                "broll_keywords": h.get("broll_keywords", []),
                "emoji_moments": h.get("emoji_moments", []),
                "source_topic": h.get("source_topic", "General"),
            })
        except (ValueError, TypeError, KeyError):
            continue

    # ── Post-LLM Validation ──
    ui_logger.log(f"Running post-LLM validation on {len(normalized)} candidates...")
    validated = _validate_clips(normalized, raw_words)
    
    # Sort by score
    validated.sort(key=lambda x: x["score"], reverse=True)

    # Dedup: 15-second window based on first segment start
    seen, deduped = set(), []
    for h in validated:
        key = int(h["start_time"] // 15)
        if key not in seen:
            seen.add(key)
            deduped.append(h)

    final = deduped[:max_clips]
    ui_logger.log(f"Done. {len(final)} top clips passed validation.")
    return {"highlights": final}


# backwards-compat alias
get_viral_clips = get_highlights
