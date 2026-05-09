"""
Local LLM highlight detection using llama-cpp-python.
Professional 3-pass architecture:
  Pass 0: Persona Detection (fast model)
  Pass 1: Topic Indexing — map the entire transcript into distinct topics
  Pass 2: Per-Topic Clip Extraction — extract 2-3 clips per topic
"""
import json
import re
from .logger import ui_logger

_llm_cache = {}
CHUNK_CHARS = 12_000  # Conservative size for 8k context models (Llama 3, Gemma 2)


# ── Virality Prompting ────────────────────────────────────────────────────────
_VIRALITY_BASE = """You are an elite short-form content strategist specializing in TikTok, Instagram Reels, and YouTube Shorts.
Your goal is to extract clips that maximize viewer engagement and virality.

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

QUALITY & NARRATIVE RULES:
- Every clip MUST start with a hook that grabs attention in the first 3 seconds.
- Every clip MUST have a clear narrative: Hook (Beginning) -> Context (Middle) -> Payoff (End).
- HUMAN EDITOR RULE: You must act like a professional human editor. Start the clip exactly when the speaker introduces the topic, and end the clip ONLY when they have completely finished their point.
- NEVER cut off a speaker mid-sentence or end a clip before the thought is fully resolved.
- Include a 3-5 second buffer (start slightly earlier, end slightly later) to ensure no words are clipped.
- Each clip must be 100% SELF-CONTAINED. A viewer who sees ONLY this clip must understand the full story.
- Optimal duration: 30-180 seconds total for short-form performance.
- Do NOT hallucinate or invent content. Only use timestamps that exist in the transcript."""


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


# ── Estimated Clip Density ───────────────────────────────────────────────────

def estimate_clip_potential(word_timestamps: list) -> int:
    """Estimate how many clips a video could produce based on its duration."""
    if not word_timestamps:
        return 3
    duration_secs = word_timestamps[-1].get("end", 0) - word_timestamps[0].get("start", 0)
    duration_mins = duration_secs / 60.0
    # Rule of thumb: ~1 clip per 2 minutes of content
    return max(5, int(duration_mins / 2))


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
    Extract viral clips from the transcript. If topics are provided (from Pass 1),
    extract clips per-topic for comprehensive coverage. Otherwise, falls back to
    chunk-based extraction.
    """
    text, raw_words = _build_text(transcript_data)

    if not llm_path:
        raise RuntimeError("llm_path is required for local highlight detection.")

    llm = _get_llm(llm_path, gpu_layers)
    
    lang_hint = f" Transcript language: {language}." if language else ""

    system = (
        "You are an elite AI director for TikTok, Instagram Reels, and YouTube Shorts."
        f"{lang_hint} Output ONLY raw JSON arrays. No prose, no markdown, no explanation whatsoever."
    )

    schema = (
        '[\n'
        '  {\n'
        '    "title": "Punchy curiosity-driving title (max 10 words)",\n'
        '    "start_quote": "Exact first 5 to 8 words of the clip",\n'
        '    "end_quote": "Exact last 5 to 8 words of the clip",\n'
        '    "start_time": 12.5,\n'
        '    "end_time": 75.0,\n'
        '    "score": 92,\n'
        '    "hook_sentence": "The exact opening sentence that will stop the scroll",\n'
        '    "virality_reason": "Specific reason this will go viral",\n'
        '    "theme": "Educational|Motivation|Comedy|Suspense|Storytime"\n'
        '  }\n'
        ']'
    )

    all_highlights = []

    if topics and len(topics) > 0:
        # ── Topic-Aware Extraction ──
        clips_per_topic = max(3, min(6, -(-num_clips // max(1, len(topics)))))
        
        for tidx, topic in enumerate(topics):
            ui_logger.log(f"Topic {tidx + 1}/{len(topics)}: \"{topic['topic']}\"")
            topic_text = _get_text_slice(text, topic["start_time"], topic["end_time"])
            if not topic_text.strip(): continue
            
            # Get the transcript slice for this topic
            topic_text = _get_text_slice(text, topic["start_time"], topic["end_time"])
            if not topic_text.strip():
                continue

            prompt = (
                f"{_VIRALITY_BASE}\n\n"
                f"You are analyzing a specific section of a video about: \"{topic['topic']}\"\n"
                f"Time range: {topic['start_time']:.0f}s to {topic['end_time']:.0f}s\n\n"
                f"Extract the {clips_per_topic} most viral moments from THIS section.\n"
                f"Each clip MUST have start_time and end_time within the range "
                f"{topic['start_time']:.0f}s to {topic['end_time']:.0f}s.\n"
                f"Each clip should be 30-90 seconds long.\n\n"
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
                f"{_VIRALITY_BASE}\n\n"
                f"Extract the {clips_per_chunk} most viral moments from this transcript.\n"
                f"Each clip should be 30-90 seconds long.\n\n"
                f"Transcript:\n{chunk}\n\n"
                f"Respond ONLY with a JSON array of {clips_per_chunk} clips:\n{schema}"
            )
            try:
                results = _query_llm(llm, system, prompt)
                all_highlights.extend(results)
            except Exception as e:
                ui_logger.log(f"Warning: chunk {idx + 1} failed — {e}")

    ui_logger.log(f"LLM extracted {len(all_highlights)} raw candidates. Scoring and filtering...")

    # ── Validate and Normalize ──
    valid = []
    for h in all_highlights:
        try:
            raw_st = float(h.get("start_time", 0))
            raw_et = float(h.get("end_time", 0))
            
            # Snap timestamps precisely using quotes if raw_words are available
            if raw_words:
                st = _match_quote(h.get("start_quote", ""), raw_words, raw_st, is_start=True)
                et = _match_quote(h.get("end_quote", ""), raw_words, raw_et, is_start=False)
            else:
                st, et = raw_st, raw_et
                
            dur = et - st
            score = max(0, min(100, int(h.get("score", 50))))

            if dur < 10 or dur > 180:  # Loosened minimum duration to 10s
                continue

            # Validate and normalise theme
            theme = h.get("theme", "Storytime")
            if theme not in ["Motivation", "Educational", "Comedy", "Suspense", "Storytime"]:
                theme = "Storytime"

            h["start_time"] = st
            h["end_time"] = et
            h["duration"] = dur
            h["score"] = score
            h["theme"] = theme
            h["hook_type"] = h.get("hook_type", "story_arc")
            h.setdefault("broll_keywords", [])
            h.setdefault("emoji_moments", [])
            h.setdefault("source_topic", "General")
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

    final = deduped[:max_clips]
    ui_logger.log(f"Done. {len(final)} top clips identified.")
    return {"highlights": final}


# backwards-compat alias
get_viral_clips = get_highlights
