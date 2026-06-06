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


# â”€â”€ Opus-Style Viral Director Prompt â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_VIRALITY_BASE = """You are an expert short-form video editor who has studied thousands of viral TikTok, Instagram Reels, and YouTube Shorts clips. Your job is to hunt through this transcript and identify every moment that has the natural shape of a viral clip. A 2-hour podcast typically contains 15-30 of these moments. Your job is to find all of them.

TOTAL VIDEO DURATION: {video_duration_str}

â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
THE SHAPE OF A VIRAL CLIP — LEARN THIS PATTERN:

Every viral clip from a podcast or interview has the same three-part shape.
Your job is to find moments in the transcript where this shape already exists
naturally in what the speaker said. You are not creating structure — you are
recognizing it.

PART 1 — THE ENTRY POINT (the first thing the viewer hears):
This is a line that makes a scrolling viewer stop and watch. It works because
it creates an open question in their mind — something feels unresolved, surprising,
or counterintuitive. They have to keep watching to understand it.

What it sounds like in real transcripts:
- A bold claim that challenges something most people believe:
  "The problem with goal-setting is that it's actually working against you."
- A specific surprising detail that implies a bigger story:
  "I fired my entire sales team on a Tuesday and revenue went up 40%."
- A question that the viewer immediately wants the answer to:
  "Why do the most disciplined people I know get the least done?"
- A contradiction that doesn't make sense yet:
  "The harder I worked on my marriage, the worse it got."

What it does NOT sound like:
- Introductions: "So today I want to talk about..."
- Context-setting: "A little background on this topic..."
- Transitions: "So moving on to the next point..."
- Agreements: "Yeah, exactly, that's a great point..."

PART 2 — THE BUILD (the middle of the clip):
This is where the speaker explains, proves, or tells the story behind the
entry point. The viewer stays because they want the answer to the question
the entry point created. The build is what separates a viral clip from a
viral quote — it earns the payoff through substance.

What it sounds like:
- The speaker walks through the logic behind their claim step by step
- The speaker tells a specific story or gives a concrete example
- The speaker challenges the conventional wisdom and explains why it's wrong
- The speaker reveals what they discovered, learned, or experienced

The build must be substantial — at least 3-5 sentences of development.
A clip with a great entry point and no build feels hollow and gets skipped.

PART 3 — THE LANDING (the last thing the viewer hears):
This is the line that closes the loop. The viewer was holding a question
in their mind since the entry point — the landing answers it in a way that
feels satisfying, surprising, or memorable. This is the line people screenshot,
share, or quote. It is the reason the clip was worth watching.

What it sounds like:
- A reframe that makes the viewer see something differently:
  "So the goal was never the goal. The goal was who you had to become to get it."
- A hard truth delivered plainly:
  "Most people aren't failing because they lack discipline. They're failing
   because they're optimizing for the wrong thing."
- A specific actionable conclusion:
  "Stop setting outcome goals. Set process goals. Track the behavior, not the result."
- An emotional release — a moment of genuine humor, vulnerability, or relief

The landing MUST be the actual conclusion of the thought. If the speaker
is still mid-explanation, mid-story, or mid-argument when you cut — the
clip has no landing. Keep reading the transcript forward until the thought
closes naturally. That closing line is your landing.

â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
HOW TO HUNT FOR THESE MOMENTS:

Read through the transcript and look for these trigger patterns that signal
a complete viral clip is nearby:

TRIGGER 1 — CONTRAST STATEMENTS:
Any time the speaker says "but", "however", "the problem is", "here's the
thing", "what most people don't realize", "the truth is", "what nobody
tells you" — a clip is likely starting. Read forward from that point and
find where the thought fully closes.

TRIGGER 2 — SPECIFIC NUMBERS OR DETAILS:
Any time the speaker uses a specific number, statistic, or concrete detail
("10 years", "40%", "every single time", "$50,000") — these signal a real
story or real evidence is coming. These clips have high credibility and
shareability.

TRIGGER 3 — PERSONAL STORIES WITH A LESSON:
Any time the speaker says "I remember when", "there was this moment",
"I used to think", "I made this mistake" — a story arc is beginning.
Read forward until the speaker explicitly draws the lesson from the story.
That lesson is your landing.

TRIGGER 4 — DIRECT AUDIENCE ADDRESS:
Any time the speaker shifts from talking about themselves or others to
talking directly to the listener — "if you're struggling with", "here's
what I want you to understand", "stop doing this" — these clips feel
personal and convert well because the viewer feels spoken to directly.

TRIGGER 5 — OPINION BOMBS:
Any time the speaker says something that a significant portion of the
audience would disagree with or find surprising — these clips generate
comments and shares because they provoke a reaction. Find where the
speaker defends or explains the opinion. That explanation is the build.
The original statement is the entry point.

â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
EXTRACTION RULES:

- Extract EVERY moment that has a clear Entry Point, Build, and Landing.
  If a topic section has 5 such moments, extract all 5.
- Each clip MUST contain one or more segments that total 30-90 seconds. This represents approximately 30-90 seconds of speech. This expanded length ensures you have ample room to capture the complete payoff or answer.
- THE PAYOFF MANDATE: Every single clip MUST deliver a clear, satisfying conclusion, takeaway, or payoff. If the clip's hook or opening raises a specific question, introduces a problem, or starts a discussion topic, the clip MUST include the exact resolution or answer. Sometimes, the payoff is delivered a bit later in the transcript—in these cases, you MUST continue reading forward and extend the clip's end boundary to capture the actual resolution. A clip that cuts off before the answer or payoff is an absolute failure. The viewer must get something high-value out of the ending.
- ENDING RULES — NON-NEGOTIABLE:
  The final segment's end_quote MUST be one of these:
    - The speaker's conclusion or answer to the question they raised
    - A punchline or surprising reversal that pays off the setup
    - A strong declarative statement that closes the argument
    - A specific result, number, or outcome that proves the point
  The final segment's end_quote must NEVER be:
    - A question (unless it is purely rhetorical with no answer needed)
    - A transitional phrase ("so anyway", "but yeah", "moving on")
    - A filler or acknowledgment ("right", "exactly", "I mean")
    - Mid-argument ("and the reason for that is", "so what happens is")
    - An incomplete thought that sets up something outside the clip
  Ensure the final segment captures the closing sentence perfectly. A clip that runs 5 seconds long but ends properly is always better than a clip that ends on time but cuts the landing.
- VALUABLE INSIGHT FALLBACK: While structured story arcs are preferred, if a section contains highly engaging, funny, contrarian, or educational discussion but lacks a formal question/resolution payoff, you MUST still extract it! Simply ensure it ends on a completed, coherent thought so the viewer gets clear value. Never be too conservative or return zero clips; prioritize extracting the most entertaining, informative, or high-energy blocks available in the text.
- Always extend the final segment forward until the thought fully
  closes. Never end on a sentence that is still building toward something.
- Never cut in the middle of a sentence, story, or argument.
- Only the exact spoken words from the transcript. No invented content.
- STRICT EDITING MANDATE: You MUST actively edit out all boring filler, long pauses, tangents, secondary details, or host interruptions. Skip them entirely. The stitching engine will automatically concatenate your selected high-energy segments into a punchy, jump-cut video. Do not be lazy - extract ONLY the absolute best sentences that drive the point home fast.
- Do not extract intros, outros, sponsor reads, or off-topic transitions.
- HOOK NON-REPETITION MANDATE: For `hook_sentence` and `hook_text`, write completely clean, non-repetitive, grammatically correct sentences. NEVER repeat any words, clauses, or phrases inside the sentence (avoid loops like 'mostly reasonable works better than mostly reasonable works better than'). Make sure it is highly punchy, clear, and natural.

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
one of these five types and set the hook_type field accordingly:

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

Choose the type that best fits the clip's actual content and tone.
Do not force a type. If the clip is primarily educational with no strong
psychological trigger, use "curiosity_gap" as default.
"""



# â”€â”€ LLM Management â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _get_llm(llm_path: str, gpu_layers: int = 35):
    if isinstance(llm_path, str) and llm_path.startswith("gemini-"):
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


def _query_gemini(model_name: str, system: str, prompt: str, max_tokens: int = 3000) -> list:
    import os
    import urllib.request
    import json
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        ui_logger.log("ERROR: GEMINI_API_KEY environment variable is not set!")
        raise RuntimeError("Missing GEMINI_API_KEY in environment or .env file.")
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": f"System Instructions:\n{system}\n\nUser Request:\n{prompt}"}
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.4,
            "maxOutputTokens": max_tokens
        }
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    
    try:
        ui_logger.log(f"Querying Gemini API ({model_name})...")
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            raw_text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            parsed = _parse_json_loose(raw_text)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return parsed.get("highlights", parsed.get("clips", parsed.get("topics", [parsed])))
            return []
    except Exception as e:
        ui_logger.log(f"Gemini API Error: {e}")
        if hasattr(e, "read"):
            try:
                err_body = e.read().decode('utf-8')
                ui_logger.log(f"API Response Details: {err_body}")
            except:
                pass
        return []


def _query_llm(llm, system: str, prompt: str, max_tokens: int = 3000) -> list:
    if isinstance(llm, str) and llm.startswith("gemini-"):
        return _query_gemini(llm, system, prompt, max_tokens)

    # Merging system instructions and user prompt by default to prevent system role support issues and eliminate retries
    content = f"{system}\n\n{prompt}"
    try:
        resp = llm.create_chat_completion(
            messages=[
                {"role": "user", "content": content},
            ],
            temperature=0.40,
            max_tokens=max_tokens,
        )
    except Exception as e:
        ui_logger.log(f"Model query error: {e}")
        return []

    raw = resp["choices"][0]["message"]["content"].strip()
    parsed = _parse_json_loose(raw)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return parsed.get("highlights", parsed.get("clips", parsed.get("topics", [parsed])))
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


# â”€â”€ Post-LLM Validation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _validate_clips(clips: list, raw_words: list) -> list:
    valid = []
    for clip in clips:
        segments = clip.get("segments", [])
        if not segments:
            continue

        total_dur = sum(max(0, seg.get("end_time", 0) - seg.get("start_time", 0)) for seg in segments)

        if total_dur < 10 or total_dur > 180:
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
            "1. REVELATION — The speaker says something surprising, counterintuitive,\n"
            "   or that contradicts a commonly held belief. Signal phrases: \"most\n"
            "   people think\", \"what nobody tells you\", \"the truth is\", \"I found out\".\n\n"
            "2. TENSION OR DISAGREEMENT — The speaker pushes back on an idea, admits\n"
            "   a mistake, or challenges the audience. Signal phrases: \"but here's the\n"
            "   problem\", \"I was wrong about\", \"this is where people get it wrong\".\n\n"
            "3. SPECIFIC NUMBERS OR PROOF — The speaker cites a concrete number,\n"
            "   statistic, personal result, or named example. Signal: any dollar\n"
            "   amount, percentage, timeframe, or named person/company as evidence.\n\n"
            "4. STRONG PERSONAL OPINION — The speaker makes a declarative claim they\n"
            "   clearly believe strongly. Signal phrases: \"I genuinely believe\",\n"
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


# â”€â”€ Pass 2: Per-Topic Clip Extraction â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
        '    "virality_score": 85,\n'
        '    "hook_score": 20, // integer 0-25 — how scroll-stopping is the opening moment\n'
        '    "engagement_score": 20, // integer 0-25 — how compelling is the middle content\n'
        '    "value_score": 20, // integer 0-25 — educational or entertainment value\n'
        '    "shareability_score": 20, // integer 0-25 — would someone actively share this\n'
        '    "start_timestamp": 12.4,\n'
        '    "end_timestamp": 54.1,\n'
        '    "segments": [\n''      {\n''        "start_quote": "The exact first 3-5 words of the segment. No timestamps.",\n''        "end_quote": "The exact last 3-5 words of the segment. No timestamps."\n''      }\n''    ],\n'
        '    "theme": "Educational|Motivation|Comedy|Suspense|Storytime",\n'
        '    "music_query": "A 3-4 word search term for no-copyright background music (e.g., upbeat phonk, calm lofi, dark suspense)",\n'
        '    "broll_keywords": ["2-3 concrete visual nouns that match the clip content, e.g., money, laptop, crowd"],\n'
        '    "emoji_moments": ["1-3 single emoji characters that match emotional peaks in the clip, e.g., 🔥, 💡, 😂"],\n'
        '    "hook_text": "Max 8 words. A bold, original declarative statement that creates a curiosity gap. NOT a summary. DO NOT copy the prompt instructions verbatim. DO NOT use generic phrases. It must reflect the specific payload of the clip.",\n'
        '    "hook_sentence": "A REWRITTEN scroll-stopping opening line (12-18 words) authored for social media — NOT copied from the transcript. Write an original hook tailored to the specific content of the clip. DO NOT copy the template examples from the prompt. It must be highly specific, punchy, and original. Max 18 words.",\n'
        '    "hook_type": "one of exactly: \\"curiosity_gap\\" | \\"loss_aversion\\" | \\"self_identification\\" | \\"pattern_interrupt\\" | \\"open_loop\\""\n'
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
  score, virality_score, energy_score, hook_sentence, hook_text, hook_type,
  virality_reason, theme, music_query, broll_keywords, emoji_moments,
  source_topic
□ hook_type is exactly one of: curiosity_gap | loss_aversion |
  self_identification | pattern_interrupt | open_loop
□ hook_text is 8 words or fewer — if longer, trim it
□ virality_score is an integer between 0 and 100 — not a string, not a float
□ hook_score, engagement_score, value_score, shareability_score are each integers between 0 and 25
□ score is an integer between 0 and 100
□ broll_keywords is a list of strings, not a single string
□ emoji_moments is a list of strings
□ segments is a list of objects each with start_time and end_time as floats
□ No field has a null value — use empty string "" or empty list [] as fallback
□ Output is a valid JSON array only — no markdown, no commentary, no
  explanation outside the array

---
"""

    if topics and len(topics) > 0:
        # â”€â”€ Topic-Aware Extraction â”€â”€
        clips_per_topic = max(2, min(4, -(-num_clips // max(1, len(topics)))))
        
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
                f"Extract ONLY the absolute best viral moments. If the section is boring or low energy, return an EMPTY array []. NEVER return clips that score below 85. Quality over quantity.\n"
                f"CRITICAL: Do NOT extract multiple overlapping clips from the same moment. If you find a great moment, extract ONE cohesive, fully-fleshed out clip (30-90s) rather than multiple overlapping fragments. Do NOT create duplicate variations of the same dialogue.\n"
                f"CRITICAL: Do NOT include timestamp brackets (e.g., [12.4s]) inside start_quote or end_quote. Only output the raw spoken words. However, you MUST output the start_timestamp and end_timestamp floating-point keys in the JSON object itself.{energy_hint}\n\n"
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
        # â”€â”€ Fallback: Run topic indexing first, then extract per-topic â”€â”€
        ui_logger.log("No topics provided — running automatic topic indexing (Pass 1)...")
        auto_topics = get_topic_index(transcript_data, llm_path, gpu_layers, language)

        if auto_topics:
            clips_per_topic = max(2, min(4, -(-num_clips // max(1, len(auto_topics)))))
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
                    f"Extract ONLY the absolute best viral moments. If the section is boring or low energy, return an EMPTY array []. NEVER return clips that score below 85. Quality over quantity.\n"
                    f"CRITICAL: Do NOT extract multiple overlapping clips from the same moment. If you find a great moment, extract ONE cohesive, fully-fleshed out clip (30-90s) rather than multiple overlapping fragments. Do NOT create duplicate variations of the same dialogue.\n"
                    f"CRITICAL: Do NOT output timestamps. Only the exact spoken words.{energy_hint}\n\n"
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
                    f"Extract ONLY the absolute best viral moments.\n"
                    f"CRITICAL: Do NOT extract multiple overlapping clips from the same moment. If you find a great moment, extract ONE cohesive, fully-fleshed out clip (30-90s) rather than multiple overlapping fragments. Do NOT create duplicate variations of the same dialogue.\n"
                    f"CRITICAL: Do NOT include timestamp brackets (e.g., [12.4s]) inside start_quote or end_quote. Only output the raw spoken words. However, you MUST output the start_timestamp and end_timestamp floating-point keys in the JSON object itself.\n\n"
                    f"Transcript (Part {idx+1}/{len(fallback_chunks)}):\n{f_chunk}\n\n"
                    f"Respond ONLY with a JSON array of clips:\n{schema}"
                )
                try:
                    results = _query_llm(llm, system, prompt)
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
            if raw_words and ideal_transcript:
                segments = _map_text_to_stitched_segments(ideal_transcript, raw_words)
                # Fallback to LLM timestamps ONLY if mapping totally failed
                if not segments and start_ts is not None and end_ts is not None:
                    try:
                        segments = [{"start_time": float(start_ts), "end_time": float(end_ts)}]
                    except (ValueError, TypeError):
                        pass
            else:
                if start_ts is not None and end_ts is not None:
                    try:
                        segments = [{"start_time": float(start_ts), "end_time": float(end_ts)}]
                    except (ValueError, TypeError):
                        segments = []
                else:
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
            clip_peaks = [p["energy"] for p in (energy_peaks or []) if overall_st <= p["time"] <= overall_et]
            energy_val = max(clip_peaks) if clip_peaks else 0.0
            energy_score = int(energy_val * 100)
            composite_score = int((score * 0.6) + (energy_score * 0.4))

            sentences = re.split(r'(?<=[.!?।|])\s+', ideal_transcript.strip())
            # Read from LLM output, fallback to first sentence if empty/missing
            hook_sentence = h.get("hook_sentence", "").strip()
            if not hook_sentence:
                hook_sentence = sentences[0] if sentences else ""
            hook_type = h.get("hook_type", "curiosity_gap")
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
                "hook_text": h.get("hook_text", hook_sentence),
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

    # â”€â”€ Post-LLM Validation â”€â”€
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
