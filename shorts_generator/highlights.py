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
_VIRALITY_BASE = """You are an exhaustive video editor. Your goal is to find EVERY single distinct thought, story, or high-value moment in this transcript that could stand alone as a Short. Do not force content. If a section is boring, skip it. If a section has 5 good moments, extract all 5. A 2-hour podcast typically yields 15-30 natural clips. Leave no good content behind.

TOTAL VIDEO DURATION: {video_duration_str}
CRITICAL: Do not force quotas. Just extract the natural clips.

═══════════════════════════════════════════════════════
VIRALITY SIGNALS (ranked by importance):

1. SCROLL-STOPPING HOOKS (The first 3 seconds)
   - Curiosity gaps: "The reason most people fail at X is..."
   - Bold/contrarian claims: "X is actually a scam, here's the truth."

2. OPINION BOMBS & HOT TAKES (High shareability)
   - Statements that divide the audience.
   - Challenging conventional wisdom.

3. REVELATION & PROOF (High save rate)
   - Insider secrets or specific "how-to" steps.

4. EMOTIONAL PEAKS
   - Genuine surprise, frustration, or breakthrough realizations.

═══════════════════════════════════════════════════════
CRITICAL EXTRACTION RULES:

- Every clip MUST start with a hook that grabs attention in the first 3 seconds.
- Every clip MUST have a clear narrative arc: Hook (Beginning) -> Context/Value (Middle) -> Payoff/Conclusion (End).
- Extract the longest possible natural narrative arc. A clip MUST be a single, continuous, unbroken story or argument.
- Only extract multi-segment clips if the speaker pauses for more than 3 seconds or goes completely off-topic in the middle of a great point. Do NOT stitch unrelated thoughts together just to make the video longer.
- A 60-second continuous thought is infinitely better than a 60-second stitched Frankenstein clip.
- Do NOT include timestamps or segment numbers. Only the literal spoken words.
- The clip MUST end on a COMPLETED SENTENCE. Never cut off mid-thought.
- Each clip must be 100% SELF-CONTAINED. A viewer who sees ONLY this clip must understand the full story.
- Do NOT hallucinate or invent content. Only use exact spoken words from the transcript."""


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

def _map_text_to_stitched_segments(ideal_transcript: str, raw_words: list) -> list:
    if not ideal_transcript or not raw_words:
        return []

    sentences = re.split(r'(?<=[.!?])\s+', ideal_transcript.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    segments = []
    current_segment = None
    search_idx = 0

    def normalize_word(w):
        return re.sub(r'[^a-z0-9]', '', w.lower())

    raw_normalized = [normalize_word(w["word"]) for w in raw_words]

    def find_anchor(anchor_words, start_search_idx):
        if not anchor_words:
            return -1
        anchor_len = len(anchor_words)
        
        # Try exact match with anchor_len
        for i in range(start_search_idx, len(raw_normalized) - anchor_len + 1):
            match = True
            for j in range(anchor_len):
                if raw_normalized[i+j] != anchor_words[j]:
                    match = False
                    break
            if match:
                return i
                
        # If 3 words fail, try 2 words if possible
        if anchor_len > 2:
            for i in range(start_search_idx, len(raw_normalized) - 1):
                if raw_normalized[i] == anchor_words[0] and raw_normalized[i+1] == anchor_words[1]:
                    return i
                    
        return -1

    for sentence in sentences:
        words = [normalize_word(w) for w in sentence.split()]
        words = [w for w in words if w]
        if not words:
            continue
            
        start_anchor = words[:3]
        end_anchor = words[-3:] if len(words) >= 3 else words
        
        # Find start
        start_idx = find_anchor(start_anchor, search_idx)
        if start_idx == -1:
            continue
            
        # Find end
        end_idx = find_anchor(end_anchor, start_idx)
        if end_idx == -1:
            end_idx = start_idx + len(words) - 1
            end_idx = min(end_idx, len(raw_words) - 1)
        else:
            end_idx = end_idx + len(end_anchor) - 1
            
        st = raw_words[start_idx]["start"]
        et = raw_words[end_idx]["end"]
        
        search_idx = end_idx + 1
        
        if current_segment is None:
            current_segment = {"start_time": st, "end_time": et}
        else:
            gap = st - current_segment["end_time"]
            if gap < 1.5:
                # Merge
                current_segment["end_time"] = max(current_segment["end_time"], et)
            else:
                # New segment
                segments.append(current_segment)
                current_segment = {"start_time": st, "end_time": et}
                
    if current_segment:
        segments.append(current_segment)
        
    if not segments and raw_words and ideal_transcript:
        # Fallback: finding the first word of the ideal_transcript in the raw words
        first_word = normalize_word(ideal_transcript.split()[0]) if ideal_transcript.split() else ""
        for i, w in enumerate(raw_words):
            if normalize_word(w["word"]) == first_word:
                st = w["start"]
                et = min(st + 45.0, raw_words[-1]["end"])
                return [{"start_time": st, "end_time": et}]
        
    return segments


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
    1. Are under 20s or over 120s after stitch estimation
    (Clips over 90s are sliced down sentence by sentence)
    """
    valid = []
    for clip in clips:
        segments = clip.get("segments", [])
        ideal_transcript = clip.get("ideal_transcript", "")
        if not segments or not ideal_transcript:
            continue

        # Calculate total stitched duration
        total_dur = sum(max(0, seg.get("end_time", 0) - seg.get("start_time", 0)) for seg in segments)

        # Duration check: >90s -> slice transcript and remap
        if total_dur > 90:
            sentences = re.split(r'(?<=[.!?])\s+', ideal_transcript.strip())
            sliced_transcript = ""
            for s in sentences:
                test_transcript = (sliced_transcript + " " + s).strip()
                test_segments = _map_text_to_stitched_segments(test_transcript, raw_words)
                test_dur = sum(max(0, seg.get("end_time", 0) - seg.get("start_time", 0)) for seg in test_segments) if test_segments else 0
                if test_dur > 90 and sliced_transcript:
                    break
                sliced_transcript = test_transcript
            
            if sliced_transcript:
                segments = _map_text_to_stitched_segments(sliced_transcript, raw_words)
                if not segments:
                    continue
                total_dur = sum(max(0, seg.get("end_time", 0) - seg.get("start_time", 0)) for seg in segments)
                clip["ideal_transcript"] = sliced_transcript
                clip["segments"] = segments
                clip["start_time"] = segments[0]["start_time"]
                clip["end_time"] = segments[-1]["end_time"]

        # Final duration check
        if total_dur < 15 or total_dur > 120:
            ui_logger.log(f"  Discarded clip '{clip.get('title', '?')}': duration {total_dur:.0f}s out of bounds")
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

    # New schema focused on semantic text extraction
    schema = (
        '[\n'
        '  {\n'
        '    "title": "Catchy TikTok-style title (max 10 words)",\n'
        '    "virality_score": 85,\n'
        '    "ideal_transcript": "The exact word-for-word transcript of the perfect 40-60 second clip. Include the hook at the beginning and the natural conclusion at the end. Do not include timestamps, just the raw spoken words.",\n'
        '    "theme": "Educational|Motivation|Comedy|Suspense|Storytime",\n'
        '    "music_query": "A 3-4 word search term for no-copyright background music that fits the vibe (e.g., upbeat phonk, calm lofi, dark suspense)"\n'
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
                f"Extract ALL of the most viral, natural moments from THIS section.\n"
                f"CRITICAL: Do NOT output timestamps. Only the exact spoken words.\n\n"
                f"Transcript:\n{topic_text}\n\n"
                f"Respond ONLY with a JSON array of clips:\n{schema}"
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
        clips_per_chunk = max(5, min(8, -(-max_clips // max(1, len(chunks)))))

        for idx, chunk in enumerate(chunks):
            ui_logger.log(f"Analyzing chunk {idx + 1}/{len(chunks)} — exhaustive extraction...")
            prompt = (
                f"{virality_prompt}\n\n"
                f"You MUST output all natural clips for this chunk. Do not force content.\n"
                f"CRITICAL: Do NOT output timestamps. Only the exact spoken words.\n\n"
                f"Transcript:\n{chunk}\n\n"
                f"Respond ONLY with a JSON array of clips:\n{schema}"
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
            ideal_transcript = h.get("ideal_transcript", "")
            if not ideal_transcript:
                continue

            segments = _map_text_to_stitched_segments(ideal_transcript, raw_words)
            if not segments:
                continue

            score = max(0, min(100, int(h.get("virality_score", h.get("score", 50)))))
            theme = h.get("theme", "Storytime")
            if theme not in ["Motivation", "Educational", "Comedy", "Suspense", "Storytime"]:
                theme = "Storytime"

            overall_st = segments[0]["start_time"]
            overall_et = segments[-1]["end_time"]

            sentences = re.split(r'(?<=[.!?])\s+', ideal_transcript.strip())
            hook_sentence = sentences[0] if sentences else ""

            normalized.append({
                "title": h.get("title", "Untitled Clip"),
                "ideal_transcript": ideal_transcript,
                "segments": segments,
                "start_time": overall_st,
                "end_time": overall_et,
                "score": score,
                "hook_sentence": hook_sentence,
                "hook_text": hook_sentence,
                "virality_reason": h.get("virality_reason", ""),
                "theme": theme,
                "music_query": h.get("music_query", ""),
                "source_topic": h.get("source_topic", "General"),
            })
        except Exception:
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
