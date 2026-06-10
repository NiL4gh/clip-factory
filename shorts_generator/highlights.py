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
CHUNK_CHARS = 3000  # More granular chunks to ensure we identify 5-10+ topics for 15-20 clips


_VIRALITY_BASE = """You are an expert short-form video editor.
Your job is to identify highly engaging moments in the transcript that have the natural shape of a viral clip.

A viral clip has three parts:
1. THE HOOK: An entry point that creates an open question, challenges a belief, or promises value.
2. THE BUILD: The context, story, or logic that answers the hook.
3. THE LANDING: A satisfying conclusion or takeaway.

EXTRACTION RULES:
- Extract EVERY moment that follows this structure.
- You can stitch multiple non-contiguous segments together to skip filler and keep the pace fast.
- Ensure the local conversational subject is clear to the viewer (e.g., replace "it" with what they are talking about).
- End clips strongly on a clear resolution, never mid-thought.
- Write punchy, non-repetitive hooks for `hook_sentence` and `hook_text`.
- Make sure it is highly punchy, clear, and natural.

NEVER EXTRACT any of the following regardless of how interesting the
words sound:
- Podcast or show intros: segments containing phrases like "welcome to",
  "welcome back", "today on", "in today's episode", "I'm your host",
  "on this podcast", "this week we're", "joining me today"
- Outros and closings: "thank you for listening", "subscribe",
  "follow us", "see you next", "that's all for today", "until next time"
- Sponsor reads and ad breaks: "this episode is sponsored by",
  "brought to you by", "use code", "link in the bio", "check out",
  "discount", "promo code"
- Segments where the speaker is only describing what they are ABOUT TO
  say rather than actually saying it — framing and setup language is
  not a clip
- Any segment whose primary function is to introduce, frame, or close
  the content rather than deliver the core insight or story
"""

_TRIGGER_WORDS = """
VIRAL TRIGGER WORD REFERENCE (use these to sharpen hook_text):
- Insider Words (create exclusivity): "secret", "nobody tells you",
  "they don't want you to know", "behind the scenes", "what they hide",
  "industry secret"
- Helper Words (promise value): "how to", "the fix", "what actually works",
  "step by step", "the solution", "here's how"
- Thinker Words (spark curiosity): "why", "the real reason", "the truth
  about", "what actually happened", "the root cause"
- Amplifier Words (raise stakes): "brutal", "shocking", "raw", "honest",
  "unpopular opinion", "controversial", "most people don't"
- FOMO Words (create urgency): "before it's too late", "stop missing out",
  "everyone else already knows", "you're behind", "the window is closing"
"""

_HOOK_TYPES = """
PSYCHOLOGICAL HOOK TYPE — you must classify each clip's hook into exactly
one of these six types and set the hook_type field accordingly:

1. "curiosity_gap" — Information asymmetry. Imply knowledge the viewer
   lacks. Example hook: "Nobody talks about this, but it explains
   everything."
2. "loss_aversion" — Trigger fear of losing something or missing out.
   Example hook: "Stop wasting time on X before it's too late."
3. "self_identification" — Directly address a specific identity or
   struggle so the viewer feels seen. Example hook: "If you've ever
   struggled with X, this is for you."
4. "pattern_interrupt" — A contrarian statement that breaks the viewer's
   expected narrative. Example hook: "I quit X after 10 years. Here's
   what changed."
5. "open_loop" — Create an unresolved tension that demands completion.
   Example hook: "The third point is the one that actually matters."
6. "opinion_bomb" — A controversial take, hot opinion, or statement that
   contradicts mainstream advice. Example hook: "Most people are completely wrong about X."

Choose the type that best fits the clip's actual content and tone.
Do not force a type. If the clip is primarily educational with no strong
psychological trigger, use "curiosity_gap" as default.
"""



# â”€â”€ LLM Management â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _get_llm(llm_path: str, gpu_layers: int = 35):
    if isinstance(llm_path, str) and llm_path.startswith("api:"):
        return llm_path

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


def _execute_with_fallback(llm, system: str, prompt: str, max_tokens: int = 3000) -> list:
    if not isinstance(llm, str) or not llm.startswith("api:"):
        content = f"{system}\n\n{prompt}"
        try:
            resp = llm.create_chat_completion(
                messages=[{"role": "user", "content": content}],
                temperature=0.40,
                max_tokens=max_tokens,
            )
            raw = resp["choices"][0]["message"]["content"].strip()
            parsed = _parse_json_loose(raw)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return parsed.get("highlights", parsed.get("clips", parsed.get("topics", [parsed])))
        except Exception as e:
            ui_logger.log(f"Model query error: {e}")
        return []

    import os, urllib.request, json
    
    parts = llm.split(":", 2)
    selected_provider = parts[1] if len(parts) > 1 else "gemini"
    model_name = parts[2] if len(parts) > 2 else "gemini-2.5-flash"
    
    def get_keys(env_var):
        val = os.getenv(env_var, "").strip()
        return [k.strip() for k in val.split(",") if k.strip()]
        
    providers_config = {
        "gemini": {
            "keys": get_keys("GEMINI_API_KEY"),
            "url_func": lambda model, key: f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
            "format_payload": lambda model, sys, pr, mx: {
                "contents": [{"parts": [{"text": f"System Instructions:\n{sys}\n\nUser Request:\n{pr}"}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4, "maxOutputTokens": mx}
            },
            "extract_response": lambda res: res["candidates"][0]["content"]["parts"][0]["text"],
            "fallback_model": "gemini-2.5-flash",
            "auth_header": False
        },
        "groq": {
            "keys": get_keys("GROQ_API_KEY"),
            "url_func": lambda model, key: "https://api.groq.com/openai/v1/chat/completions",
            "format_payload": lambda model, sys, pr, mx: {
                "model": model,
                "messages": [{"role": "system", "content": sys}, {"role": "user", "content": pr}],
                "temperature": 0.4,
                "max_tokens": mx,
                "response_format": {"type": "json_object"}
            },
            "extract_response": lambda res: res["choices"][0]["message"]["content"],
            "fallback_model": "llama3-8b-8192",
            "auth_header": True
        },
        "openrouter": {
            "keys": get_keys("OPENROUTER_API_KEY"),
            "url_func": lambda model, key: "https://openrouter.ai/api/v1/chat/completions",
            "format_payload": lambda model, sys, pr, mx: {
                "model": model,
                "messages": [{"role": "system", "content": sys}, {"role": "user", "content": pr}],
                "temperature": 0.4,
                "max_tokens": mx
            },
            "extract_response": lambda res: res["choices"][0]["message"]["content"],
            "fallback_model": "meta-llama/llama-3-8b-instruct",
            "auth_header": True
        },
        "glm": {
            "keys": get_keys("GLM_API_KEY"),
            "url_func": lambda model, key: "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            "format_payload": lambda model, sys, pr, mx: {
                "model": model,
                "messages": [{"role": "system", "content": sys}, {"role": "user", "content": pr}],
                "temperature": 0.4,
                "max_tokens": mx
            },
            "extract_response": lambda res: res["choices"][0]["message"]["content"],
            "fallback_model": "glm-4-flash",
            "auth_header": True
        },
        "ollama": {
            "keys": ["local"],
            "url_func": lambda model, key: "http://localhost:11434/api/generate",
            "format_payload": lambda model, sys, pr, mx: {
                "model": model,
                "system": sys,
                "prompt": pr,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.4, "num_predict": mx}
            },
            "extract_response": lambda res: res["response"],
            "fallback_model": "llama3",
            "auth_header": False
        }
    }
    
    fallback_order = ["gemini", "groq", "openrouter", "glm", "ollama"]
    if selected_provider in fallback_order:
        fallback_order.remove(selected_provider)
    fallback_order.insert(0, selected_provider)
    
    for provider_id in fallback_order:
        pconfig = providers_config.get(provider_id)
        if not pconfig or not pconfig["keys"]:
            continue
            
        current_model = model_name if provider_id == selected_provider else pconfig["fallback_model"]
            
        for key_idx, key in enumerate(pconfig["keys"]):
            url = pconfig["url_func"](current_model, key)
            headers = {"Content-Type": "application/json"}
            if pconfig["auth_header"] and key != "local":
                headers["Authorization"] = f"Bearer {key}"
                
            payload = pconfig["format_payload"](current_model, system, prompt, max_tokens)
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
            
            try:
                ui_logger.log(f"Querying {provider_id} API ({current_model}) with key #{key_idx + 1}...")
                with urllib.request.urlopen(req) as response:
                    res_data = json.loads(response.read().decode("utf-8"))
                    raw_text = pconfig["extract_response"](res_data).strip()
                    parsed = _parse_json_loose(raw_text)
                    if isinstance(parsed, list): return parsed
                    if isinstance(parsed, dict): return parsed.get("highlights", parsed.get("clips", parsed.get("topics", [parsed])))
                    return []
            except Exception as e:
                err_code = getattr(e, "code", 500)
                ui_logger.log(f"{provider_id} API Error (key #{key_idx + 1}): HTTP {err_code}")
                continue
                
    ui_logger.log("All API providers and fallback keys failed.")
    return []


# â”€â”€ Transcript Formatting â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _build_text(transcript_data) -> tuple:
    """Returns (text_for_llm, raw_word_list)."""
    if isinstance(transcript_data, list):
        words = transcript_data
        lines = []
        curr_group = []
        for i, w in enumerate(words):
            if curr_group:
                prev_w = curr_group[-1]
                # Secondary pause check: split when speaker pauses exceed 2.0s
                if w["start"] - prev_w["end"] > 2.0 or len(curr_group) >= 15:
                    lines.append(f"[{curr_group[0]['start']:.1f}s] {' '.join(x['word'] for x in curr_group)}")
                    curr_group = []
            curr_group.append(w)
        if curr_group:
            lines.append(f"[{curr_group[0]['start']:.1f}s] {' '.join(x['word'] for x in curr_group)}")
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

def _map_quotes_to_segments(llm_segments: list, raw_words: list) -> list:
    if not llm_segments or not raw_words:
        return []

    segments = []
    current_segment = None
    search_idx = 0

    import unicodedata
    def normalize_word(w):
        if not w:
            return ""
        normalized = "".join(c for c in w if not unicodedata.category(c).startswith(('P', 'S')))
        return normalized.lower()

    raw_normalized = [normalize_word(w["word"]) for w in raw_words]

    def find_anchor(anchor_words, start_search_idx):
        if not anchor_words:
            return -1
        anchor_len = len(anchor_words)

        for i in range(start_search_idx, len(raw_normalized) - anchor_len + 1):
            match = True
            for j in range(anchor_len):
                if raw_normalized[i+j] != anchor_words[j]:
                    match = False
                    break
            if match:
                return i

        if anchor_len > 2:
            for i in range(start_search_idx, len(raw_normalized) - 1):
                if raw_normalized[i] == anchor_words[0] and raw_normalized[i+1] == anchor_words[1]:
                    return i
        return -1

    for seg_data in llm_segments:
        start_q = seg_data.get("start_quote", "")
        end_q = seg_data.get("end_quote", "")

        start_words = [normalize_word(w) for w in start_q.split()]
        start_words = [w for w in start_words if w][:5]

        end_words = [normalize_word(w) for w in end_q.split()]
        end_words = [w for w in end_words if w][-5:]

        if not start_words:
            continue

        start_idx = find_anchor(start_words, search_idx)
        if start_idx == -1:
            continue

        if end_words:
            end_idx = find_anchor(end_words, start_idx)
            if end_idx == -1:
                end_idx = start_idx + len(start_words) - 1
            else:
                end_idx = end_idx + len(end_words) - 1
        else:
            end_idx = start_idx + len(start_words) - 1

        end_idx = min(end_idx, len(raw_words) - 1)

        st = raw_words[start_idx]["start"]
        et = raw_words[end_idx]["end"]

        # B4: Walk-forward sentence-boundary cuts
        best_extended_et = et
        for next_idx in range(end_idx + 1, len(raw_words)):
            next_w = raw_words[next_idx]
            if next_w["start"] - et > 6.0:
                break
            best_extended_et = next_w["end"]
            has_punc = any(p in next_w["word"] for p in [".", "!", "?", "।", "|"])
            pause_after = False
            if next_idx + 1 < len(raw_words):
                pause_after = (raw_words[next_idx + 1]["start"] - next_w["end"]) > 0.4
            if has_punc or pause_after:
                break
        et = best_extended_et

        search_idx = end_idx + 1

        if current_segment is None:
            current_segment = {"start_time": st, "end_time": et}
        else:
            gap = st - current_segment["end_time"]
            if gap < 1.5:
                current_segment["end_time"] = max(current_segment["end_time"], et)
            else:
                segments.append(current_segment)
                current_segment = {"start_time": st, "end_time": et}

    if current_segment:
        segments.append(current_segment)

    return segments


def _map_text_to_stitched_segments(ideal_transcript: str, raw_words: list) -> list:
    """Bridge between ideal_transcript (free text) and _map_quotes_to_segments.

    The LLM returns ideal_transcript as a block of text. This function
    extracts the first and last words to build synthetic start_quote/end_quote
    pairs, then delegates to the existing anchor-based mapper.
    """
    if not ideal_transcript or not raw_words:
        return []

    words = ideal_transcript.split()
    if len(words) < 2:
        return []

    # Build a single segment request from the full ideal_transcript
    synth_segments = [{
        "start_quote": " ".join(words[:5]),
        "end_quote": " ".join(words[-5:])
    }]

    return _map_quotes_to_segments(synth_segments, raw_words)


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


# â”€â”€ Estimated Clip Density â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def estimate_clip_potential(word_timestamps: list) -> int:
    """Estimate how many clips a video could produce based on its duration."""
    if not word_timestamps:
        return 3
    duration_secs = _get_video_duration(word_timestamps)
    duration_mins = duration_secs / 60.0
    # Rule of thumb: ~1 clip per 6 minutes of content
    return max(3, int(duration_mins / 6))


# ── Post-LLM Validation ─────────────────────────────────────────────────────

# Phrases that indicate the LLM copied schema instructions instead of generating content
_HOOK_TEXT_POISON_PHRASES = [
    "exact first", "bold, original", "prompt instructions", "curiosity gap. not a summary",
    "do not copy", "do not use generic", "specific payload", "declarative statement",
    "scroll-stopping", "3-5 words of the segment",
]


def _sanitize_hook_text(raw_hook_text: str, fallback_hook_sentence: str) -> str:
    """Return clean hook_text, falling back to hook_sentence if the LLM
    output prompt instructions instead of actual content."""
    text = (raw_hook_text or "").strip()

    if not text:
        return fallback_hook_sentence

    # Detect prompt instruction leakage
    text_lower = text.lower()
    if any(phrase in text_lower for phrase in _HOOK_TEXT_POISON_PHRASES):
        return fallback_hook_sentence

    return text


def _validate_clips(clips: list, raw_words: list) -> list:
    valid = []
    import re
    for clip in clips:
        segments = clip.get("segments", [])
        if not segments:
            continue

        total_dur = sum(max(0, seg.get("end_time", 0) - seg.get("start_time", 0)) for seg in segments)

        if total_dur < 15 or total_dur > 180:
            ui_logger.log(f"  Discarded clip '{clip.get('title', '?')}': duration {total_dur:.0f}s out of bounds")
            continue

        clip["duration"] = total_dur
        clip["is_stitched"] = len(segments) > 1
        valid.append(clip)

    return valid

# â”€â”€ Pass 0: Persona Detection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
        results = _execute_with_fallback(llm, system, prompt)
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


# â”€â”€ Pass 1: Topic Indexing â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
    
    # Smart Sliding Window Chunking
    # Overlap by 1000 characters to prevent splitting context/stories across boundaries
    overlap = 1000
    step = max(500, CHUNK_CHARS - overlap)
    chunks = []
    
    # Split by lines to ensure we don't cut words or timestamps in half
    lines = text.split('\n')
    current_chunk = ""
    for line in lines:
        if len(current_chunk) + len(line) > CHUNK_CHARS and len(current_chunk) > overlap:
            chunks.append(current_chunk)
            current_chunk = current_chunk[-overlap:] + '\n' + line
        else:
            current_chunk += line + '\n'
    if current_chunk:
        chunks.append(current_chunk)

    all_topics = []
    all_topics = []

    for idx, chunk in enumerate(chunks):
        ui_logger.log(f"Topic indexing chunk {idx + 1}/{len(chunks)}...")
        prompt = (
            "Analyze this transcript section and identify distinct moments.\n\n"
            "You are hunting for MOMENTS, not topics. A moment is a short passage\n"
            "where something genuinely interesting happens. Ignore filler, logistics,\n"
            "introductions, and transitions entirely.\n\n"
            "Hunt specifically for these moment types, in priority order:\n\n"
            "1. REVELATION (HIGHEST PRIORITY) — The speaker says something surprising, counterintuitive,\n"
            "   or that directly contradicts mainstream advice, industry consensus, or popular belief.\n"
            "   This is the highest priority moment type. Signal phrases: \"most\n"
            "   people think\", \"what nobody tells you\", \"the truth is\", \"I found out\".\n\n"
            "2. TENSION OR DISAGREEMENT — The speaker pushes back on an idea, admits\n"
            "   a mistake, or challenges the audience. Signal phrases: \"but here's the\n"
            "   problem\", \"I was wrong about\", \"this is where people get it wrong\".\n\n"
            "3. SPECIFIC NUMBERS OR PROOF — The speaker cites a concrete number,\n"
            "   statistic, personal result, or named example. Signal: any dollar\n"
            "   amount, percentage, timeframe, or named person/company as evidence.\n\n"
            "4. STRONG PERSONAL OPINION (OPINION BOMB) — The speaker makes a controversial declarative claim\n"
            "   they clearly believe strongly. Signal phrases: \"I genuinely believe\",\n"
            "   \"most people will never\", \"the reason X fails is\", \"nobody wants to\n"
            "   hear this but\".\n\n"
            "5. STORY WITH STAKES — A personal anecdote or scenario where something\n"
            "   is at risk (money, reputation, relationship, health). Must have a\n"
            "   clear beginning setup and an implied outcome.\n\n"
            "SKIP any passage that is:\n"
            "- Explaining who the guest or host is\n"
            "- Discussing the show, episode, or sponsor\n"
            "- Transitioning between subjects with no clear point\n"
            "- Generic advice with no specific example or proof\n"
            "- A question without an answer in the same passage\n\n"
            "Rules:\n"
            "- Each topic must have accurate start_time and end_time from the transcript timestamps\n"
            "- Topics should NOT overlap\n"
            "- Include ALL sections — do not skip any part of the transcript\n"
            "- A 3-minute section typically has 1-3 topics\n"
            "- Identify at least 2 distinct topics for this section if possible to ensure we don't group everything together\n\n"
            f"Transcript:\n{chunk}\n\n"
            f"Respond ONLY with a JSON array:\n{topic_schema}"
        )
        try:
            results = _execute_with_fallback(llm, system, prompt, max_tokens=2000)
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


# ——— Pass 2: Per-Topic Clip Extraction ————————————————————————————————————————————

# 5 one-shot viral hook examples labeled by persona type (L1)
_VIRAL_HOOKS_EXAMPLES = """
VIRAL HOOK ONE-SHOT EXAMPLES BY PERSONA TYPE:
- DEBATE: "Everyone is lying to you about X... here is the real reason why."
- DEBATE: "They want you to believe X, but the data completely contradicts them."
- INTERVIEW: "This single question completely broke his brain..."
- INTERVIEW: "The moment he said X, I knew the interview was over."
- MONOLOGUE: "I spent 10 years learning X so you can learn it in 30 seconds."
"""

_DEBATE_PROMPT_ADDITION = """
PERSONA STYLE: DEBATE
Focus intensely on conflict, contrarian opinions, rapid-fire back-and-forth arguments, high-tension disagreements, and bold rebuttals.
Make sure the hook highlights the intellectual clash or the contrarian take.
"""

_INTERVIEW_PROMPT_ADDITION = """
PERSONA STYLE: INTERVIEW
Focus on deep emotional revelations, shocking answers, high-value expert secrets, dramatic pauses, or mind-blowing question-and-answer exchanges.
Make sure the hook highlights the host's framing or the guest's sudden realization/opinion bomb.
"""

_MONOLOGUE_PROMPT_ADDITION = """
PERSONA STYLE: MONOLOGUE
Focus on direct-to-camera storytelling, step-by-step advice, personal breakthrough realizations, clear educational insights, and actionable tips.
Make sure the hook builds intense curiosity or promises a specific transformation.
"""

def get_highlights(
    transcript_data,
    num_clips: int = 5,
    llm_path: str = "",
    gpu_layers: int = 35,
    max_clips: int = 30,
    language: str = "",
    angle: str = "standard",
    topics: list = None,
    energy_peaks: list = None,
    persona: dict = None,
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

    # New schema focused on semantic text extraction (strict Title formatting L2)
    schema = (
        '[\n'
        '  {\n'
        '    "title": "ULTRA-SHORT TOPIC HOOK (2-5 words max). MUST be punchy, curiosity-inducing, and extremely short to fit on screen (e.g. \\"THE TRUTH ABOUT X\\", \\"STOP DOING THIS\\"). NO long sentences.",\n'
        '    "ideal_transcript": "Copy the exact spoken words from the transcript that make up this clip. Include the full text from start to end.",\n'
        '    "virality_score": 85,\n'
        '    "hook_score": 20, // integer 0-25 — how scroll-stopping is the opening moment\n'
        '    "engagement_score": 20, // integer 0-25 — how compelling is the middle content\n'
        '    "value_score": 20, // integer 0-25 — educational or entertainment value\n'
        '    "shareability_score": 20, // integer 0-25 — would someone actively share this\n'
        '    "start_timestamp": 12.4,\n'
        '    "end_timestamp": 54.1,\n'
        '    "segments": [\n'
        '      {\n'
        '        "start_quote": "The exact first 3-5 spoken words of this segment, copied verbatim from the transcript. No timestamps.",\n'
        '        "end_quote": "The exact last 3-5 spoken words of this segment, copied verbatim from the transcript. No timestamps."\n'
        '      }\n'
        '    ],\n'
        '    "virality_reason": "1-2 sentences explaining WHY this clip would go viral — what psychological trigger or content quality makes it shareable.",\n'
        '    "source_topic": "The topic name this clip was extracted from.",\n'
        '    "theme": "Educational|Motivation|Comedy|Suspense|Storytime",\n'
        '    "music_query": "A 3-4 word search term for no-copyright background music (e.g., upbeat phonk, calm lofi, dark suspense)",\n'
        '    "broll_keywords": ["2-3 concrete visual nouns that match the clip content, e.g., money, laptop, crowd"],\n'
        '    "emoji_moments": ["1-3 single emoji characters that match emotional peaks in the clip, e.g., 🔥, 💡, 😂"],\n'
        '    "hook_text": "Write 3-8 words: a punchy headline about THIS clip. Example for a clip about first jobs: YOUR FIRST JOB WAS A LIE. Example for a friendship clip: MEN NEED BETTER FRIENDS. Must be specific to the clip content.",\n'
        '    "hook_sentence": "A REWRITTEN scroll-stopping opening line (12-18 words) authored for social media — NOT copied from the transcript. Write an original hook tailored to the specific content of the clip. DO NOT copy the template examples from the prompt. It must be highly specific, punchy, and original. Max 18 words.",\n'
        '    "hook_type": "one of exactly: \\"curiosity_gap\\" | \\"loss_aversion\\" | \\"self_identification\\" | \\"pattern_interrupt\\" | \\"open_loop\\" | \\"opinion_bomb\\""\n'
        '  }\n'
        ']'
    )

    all_highlights = []

    # Fork prompts dynamically based on whether detected persona is a Debate, Interview, or Monologue (L3)
    persona_genre = (persona or {}).get("genre", "Monologue")
    persona_addition = _MONOLOGUE_PROMPT_ADDITION
    if any(k in persona_genre for k in ["Debate", "Rant", "Controversial"]):
        persona_addition = _DEBATE_PROMPT_ADDITION
    elif any(k in persona_genre for k in ["Interview", "Podcast"]):
        persona_addition = _INTERVIEW_PROMPT_ADDITION

    # Build the virality prompt with dynamic video duration, structured hook examples, and persona additions
    virality_prompt = f"{_VIRALITY_BASE}\n\n{_VIRAL_HOOKS_EXAMPLES}\n\n{persona_addition}".format(video_duration_str=video_duration_str)
    virality_prompt += f"\n\n{_TRIGGER_WORDS}\n\n{_HOOK_TYPES}"

    angle_instructions = ""
    if angle == "contrarian":
        angle_instructions = (
            "\n\nEXTRACTION ANGLE: CONTRARIAN / HOT TAKES. Focus strictly on controversial claims, unpopular opinions, and contrarian perspectives.\n"
            "Prioritize segments where the speaker goes against mainstream thought, challenges beliefs, or exposes industry myths."
        )
    elif angle == "educational":
        angle_instructions = (
            "\n\nEXTRACTION ANGLE: ACTIONABLE SECRETS. Focus strictly on actionable advice, tutorials, step-by-step methods, and educational secrets.\n"
            "Prioritize segments where the speaker clearly teaches the viewer how to solve a specific problem or explains a clear concept."
        )
    elif angle == "story":
        angle_instructions = (
            "\n\nEXTRACTION ANGLE: EMOTIONAL STORIES. Focus strictly on narrative-driven passages, personal anecdotes, struggles, failures, and triumphs.\n"
            "Prioritize clips that tell a cohesive personal story with clear emotional resonance."
        )
    elif angle == "multi-angle":
        angle_instructions = (
            "\n\nEXTRACTION ANGLE: MULTI-ANGLE MIX. Extract a diverse mix of highlights across different angles: some contrarian hot takes, some educational secrets, and some personal stories, ensuring a wide variety of content."
        )
    virality_prompt += angle_instructions
    virality_prompt += (
        "\n\nâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•\n"
        "TIMESTAMP EXTRACTION RULES:\n"
        "- The 'start_timestamp' and 'end_timestamp' fields must be floating point numbers (in seconds).\n"
        "- They must correspond precisely to the bracketed timestamps (e.g., [12.5s]) inside the transcript.\n"
        "- Example: If the perfect clip starts at '[25.1s] So here is why...' and ends at '[58.6s] ...and that is it.', then set 'start_timestamp': 25.1 and 'end_timestamp': 58.6.\n"
    )
    virality_prompt += """
---
SELF-VALIDATION — MANDATORY BEFORE RETURNING OUTPUT
Before returning the JSON array, silently verify every item in this list.
If any check fails, fix the output before returning. Do not explain the
fix. Simply return the corrected JSON.

□ Every clip has all required fields: title, ideal_transcript, segments,
  virality_score, hook_score, engagement_score, value_score, shareability_score,
  start_timestamp, end_timestamp, hook_sentence, hook_text, hook_type,
  virality_reason, theme, music_query, broll_keywords, emoji_moments,
  source_topic
□ hook_type is exactly one of: curiosity_gap | loss_aversion |
  self_identification | pattern_interrupt | open_loop | opinion_bomb
□ hook_text is 8 words or fewer — if longer, trim it
□ virality_score is an integer between 0 and 100 — not a string, not a float
□ hook_score, engagement_score, value_score, shareability_score are each integers between 0 and 25
□ broll_keywords is a list of strings, not a single string
□ emoji_moments is a list of strings
□ segments is a list of objects each with start_quote (string) and end_quote (string) — exact words from the transcript
□ No field has a null value — use empty string "" or empty list [] as fallback
□ Output is a valid JSON array only — no markdown, no commentary, no
  explanation outside the array

---
"""

    if topics and len(topics) > 0:
        # â”€â”€ Topic-Aware Extraction â”€â”€
        clips_per_topic = max(2, min(6, -(-num_clips // max(1, len(topics)))))
        
        for tidx, topic in enumerate(topics):
            ui_logger.log(f"Topic {tidx + 1}/{len(topics)}: \"{topic['topic']}\"")
            topic_text = _get_text_slice(text, topic["start_time"], topic["end_time"])
            if not topic_text.strip(): continue

            topic_peaks = [] if not energy_peaks else [
                p for p in energy_peaks
                if topic.get("start_time", 0) - 5 <= p["time"] <= topic.get("end_time", 9999) + 5
            ]

            energy_hint = ""
            if topic_peaks:
                peak_times = ", ".join(f"{p['time']:.1f}" for p in topic_peaks)
                energy_hint = (
                    f"\n\nHIGH-ENERGY AUDIO MOMENTS detected in this topic (laughter, volume\n"
                    f"spikes, excitement peaks) at these timestamps in seconds:\n"
                    f"{peak_times}\n"
                    f"Strongly prefer clips that contain or start near these timestamps.\n"
                    f"These moments have proven audio engagement signals beyond the text."
                )

            prompt = (
                f"{virality_prompt}\n\n"
                f"You are analyzing a specific section of a video about: \"{topic['topic']}\"\n"
                f"Time range: {topic['start_time']:.0f}s to {topic['end_time']:.0f}s\n\n"
                f"Extract the most engaging moments from this section. ALWAYS try to return at least 1-2 good clips unless the section is completely silent or unusable.\n"
                f"CRITICAL: Do NOT extract multiple overlapping clips from the same moment. If you find a great moment, extract ONE cohesive, fully-fleshed out clip (30-90s) rather than multiple overlapping fragments. Do NOT create duplicate variations of the same dialogue.\n"
                f"CRITICAL: Do NOT include timestamp brackets (e.g., [12.4s]) inside start_quote or end_quote. Only output the raw spoken words. However, you MUST output the start_timestamp and end_timestamp floating-point keys in the JSON object itself.{energy_hint}\n\n"
                f"Transcript:\n{topic_text}\n\n"
                f"Respond ONLY with a JSON array of clips:\n{schema}"
            )
            try:
                results = _execute_with_fallback(llm, system, prompt)
                for clip in results:
                    clip["source_topic"] = topic["topic"]
                    clip["source_topic_idx"] = tidx
                all_highlights.extend(results)
            except Exception as e:
                ui_logger.log(f"Warning: Topic {tidx + 1} extraction failed — {e}")
    else:
        # â”€â”€ Fallback: Run topic indexing first, then extract per-topic â”€â”€
        ui_logger.log("No topics provided — running automatic topic indexing (Pass 1)...")
        auto_topics = get_topic_index(transcript_data, llm_path, gpu_layers, language)

        if auto_topics:
            clips_per_topic = max(2, min(6, -(-num_clips // max(1, len(auto_topics)))))
            for tidx, topic in enumerate(auto_topics):
                ui_logger.log(f"Topic {tidx + 1}/{len(auto_topics)}: \"{topic['topic']}\"")
                topic_text = _get_text_slice(text, topic["start_time"], topic["end_time"])
                if not topic_text.strip():
                    continue

                topic_peaks = [] if not energy_peaks else [
                    p for p in energy_peaks
                    if topic.get("start_time", 0) - 5 <= p["time"] <= topic.get("end_time", 9999) + 5
                ]

                energy_hint = ""
                if topic_peaks:
                    peak_times = ", ".join(f"{p['time']:.1f}" for p in topic_peaks)
                    energy_hint = (
                        f"\n\nHIGH-ENERGY AUDIO MOMENTS detected in this topic (laughter, volume\n"
                        f"spikes, excitement peaks) at these timestamps in seconds:\n"
                        f"{peak_times}\n"
                        f"Strongly prefer clips that contain or start near these timestamps.\n"
                        f"These moments have proven audio engagement signals beyond the text."
                    )

                prompt = (
                    f"{virality_prompt}\n\n"
                    f"You are analyzing a specific section of a video about: \"{topic['topic']}\"\n"
                    f"Time range: {topic['start_time']:.0f}s to {topic['end_time']:.0f}s\n\n"
                    f"Extract the most engaging and interesting moments from this section. ALWAYS try to return at least 1-2 good clips (30-90s) even if it's an educational or slower-paced video.\n"
                    f"CRITICAL: Do NOT extract multiple overlapping clips from the same moment. If you find a great moment, extract ONE cohesive, fully-fleshed out clip (30-90s) rather than multiple overlapping fragments. Do NOT create duplicate variations of the same dialogue.\n"
                    f"CRITICAL: Do NOT include timestamp brackets (e.g., [12.4s]) inside start_quote or end_quote. Only output the raw spoken words. However, you MUST output the start_timestamp and end_timestamp floating-point keys in the JSON object itself.{energy_hint}\n\n"
                    f"Transcript:\n{topic_text}\n\n"
                    f"Respond ONLY with a JSON array of clips:\n{schema}"
                )
                try:
                    results = _execute_with_fallback(llm, system, prompt)
                    for clip in results:
                        clip["source_topic"] = topic["topic"]
                        clip["source_topic_idx"] = tidx
                    all_highlights.extend(results)
                except Exception as e:
                    ui_logger.log(f"Warning: Topic {tidx + 1} extraction failed — {e}")
        else:
            ui_logger.log("WARNING: Topic indexing returned no topics. Extracting from chunks as last resort.")
            
            # Use the same sliding window logic
            overlap = 1000
            step = max(500, CHUNK_CHARS - overlap)
            fallback_chunks = []
            current_chunk = ""
            for line in text.split('\n'):
                if len(current_chunk) + len(line) > CHUNK_CHARS and len(current_chunk) > overlap:
                    fallback_chunks.append(current_chunk)
                    current_chunk = current_chunk[-overlap:] + '\n' + line
                else:
                    current_chunk += line + '\n'
            if current_chunk:
                fallback_chunks.append(current_chunk)
                
            for idx, f_chunk in enumerate(fallback_chunks):
                prompt = (
                    f"{virality_prompt}\n\n"
                    f"Extract the most engaging moments from this chunk. Try to return at least 1-2 good clips.\n"
                    f"CRITICAL: Do NOT extract multiple overlapping clips from the same moment. If you find a great moment, extract ONE cohesive, fully-fleshed out clip (30-90s) rather than multiple overlapping fragments. Do NOT create duplicate variations of the same dialogue.\n"
                    f"CRITICAL: Do NOT include timestamp brackets (e.g., [12.4s]) inside start_quote or end_quote. Only output the raw spoken words. However, you MUST output the start_timestamp and end_timestamp floating-point keys in the JSON object itself.\n\n"
                    f"Transcript (Part {idx+1}/{len(fallback_chunks)}):\n{f_chunk}\n\n"
                    f"Respond ONLY with a JSON array of clips:\n{schema}"
                )
                try:
                    results = _execute_with_fallback(llm, system, prompt)
                    all_highlights.extend(results)
                except Exception as e:
                    ui_logger.log(f"Warning: Chunk {idx+1} fallback extraction failed — {e}")

    ui_logger.log(f"LLM extracted {len(all_highlights)} raw candidates. Validating and scoring...")

    # â”€â”€ Normalize LLM output into consistent format â”€â”€
    normalized = []
    for h in all_highlights:
        try:
            ideal_transcript = h.get("ideal_transcript", "")
            
            start_ts = h.get("start_timestamp")
            end_ts = h.get("end_timestamp")
            
            # Always use exact text mapping if raw_words are available, as LLMs hallucinate timestamps
            segments = []
            if raw_words:
                # Primary: use LLM's segments array (start_quote/end_quote pairs)
                llm_segments = h.get("segments", [])
                if llm_segments and isinstance(llm_segments, list) and all(
                    isinstance(s, dict) and ("start_quote" in s or "end_quote" in s)
                    for s in llm_segments
                ):
                    segments = _map_quotes_to_segments(llm_segments, raw_words)

                # Fallback: use ideal_transcript text for anchor-based mapping
                if not segments and ideal_transcript:
                    segments = _map_text_to_stitched_segments(ideal_transcript, raw_words)

            # Last resort: LLM timestamps (known to be unreliable)
            if not segments and start_ts is not None and end_ts is not None:
                try:
                    segments = [{"start_time": float(start_ts), "end_time": float(end_ts)}]
                except (ValueError, TypeError):
                    segments = []
                
            if not segments:
                continue

            if raw_words and segments:
                matching_words = [w for w in raw_words if segments[0]["start_time"] <= w["start"] <= segments[-1]["end_time"]]
                ideal_transcript = " ".join(w["word"] for w in matching_words)
            else:
                ideal_transcript = "No transcript text available."

            score = max(0, min(100, int(h.get("virality_score", h.get("score", 50)))))
            theme = h.get("theme", "Storytime")
            if theme not in ["Motivation", "Educational", "Comedy", "Suspense", "Storytime"]:
                theme = "Storytime"

            overall_st = segments[0]["start_time"]
            overall_et = segments[-1]["end_time"]

            # Composite Scoring (P3)
            clip_peaks = [p["energy"] for p in (energy_peaks or []) if overall_st - 2 <= p["time"] <= overall_et + 2]
            energy_val = max(clip_peaks) if clip_peaks else 0.0
            energy_score = int(energy_val * 100)
            
            hook_type = h.get("hook_type", "curiosity_gap")
            opinion_bonus = 8 if hook_type == "opinion_bomb" else 0
            composite_score = int((score * 0.6) + (energy_score * 0.4)) + opinion_bonus
            composite_score = min(100, composite_score)

            sentences = re.split(r'(?<=[.!?।|])\s+', ideal_transcript.strip())
            # Read from LLM output, fallback to first sentence if empty/missing
            hook_sentence = h.get("hook_sentence", "").strip()
            if not hook_sentence:
                hook_sentence = sentences[0] if sentences else ""
            hook_score = int(h.get("hook_score", 0) or 0)
            engagement_score = int(h.get("engagement_score", 0) or 0)
            value_score = int(h.get("value_score", 0) or 0)
            shareability_score = int(h.get("shareability_score", 0) or 0)

            normalized.append({
                "title": h.get("title", "Untitled Clip"),
                "ideal_transcript": ideal_transcript,
                "segments": segments,
                "start_time": overall_st,
                "end_time": overall_et,
                "score": composite_score,
                "virality_score": score,
                "energy_score": energy_score,
                "hook_score": hook_score,
                "engagement_score": engagement_score,
                "value_score": value_score,
                "shareability_score": shareability_score,
                "hook_sentence": hook_sentence,
                "hook_text": _sanitize_hook_text(h.get("hook_text", ""), hook_sentence),
                "hook_type": hook_type,
                "virality_reason": h.get("virality_reason", ""),
                "theme": theme,
                "music_query": h.get("music_query", ""),
                "broll_keywords": h.get("broll_keywords", []),
                "emoji_moments": h.get("emoji_moments", []),
                "source_topic": h.get("source_topic", "General"),
            })
        except Exception:
            continue

    # ── Post-LLM Validation ──
    ui_logger.log(f"Running post-LLM validation on {len(normalized)} candidates...")
    validated = _validate_clips(normalized, raw_words)
    
    # Sort by score
    validated.sort(key=lambda x: x["score"], reverse=True)

    # Dedup using timestamp overlap (>50% of the shorter clip)
    deduped = []
    for h in validated:
        h_st = h["start_time"]
        h_et = h["end_time"]
        h_dur = h_et - h_st

        is_duplicate = False
        for existing in deduped:
            e_st = existing["start_time"]
            e_et = existing["end_time"]
            e_dur = e_et - e_st

            overlap_start = max(h_st, e_st)
            overlap_end = min(h_et, e_et)
            overlap_dur = max(0, overlap_end - overlap_start)

            if h_dur > 0 and e_dur > 0:
                min_dur = min(h_dur, e_dur)
                if overlap_dur / min_dur > 0.50:
                    is_duplicate = True
                    break
        if not is_duplicate:
            deduped.append(h)

    final = deduped[:max_clips]
    ui_logger.log(f"Done. {len(final)} top clips passed validation.")
    return {"highlights": final}


# backwards-compat alias
get_viral_clips = get_highlights
