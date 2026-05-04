"""
Local LLM highlight detection using llama-cpp-python.
"""
import json
import re
from .logger import ui_logger

_llm_cache = {}

VIRALITY_CRITERIA = """
Virality signals (ranked by impact):
1. HOOK MOMENTS — creates immediate curiosity
2. EMOTIONAL PEAKS — genuine surprise, laughter, anger, vulnerability
3. OPINION BOMBS — strong, polarizing statements
4. REVELATION MOMENTS — surprising facts
5. QUOTABLE ONE-LINERS — perfect standalone quotes
"""

CHUNK_CHARS = 15_000

def _get_llm(llm_path: str, gpu_layers: int = 35):
    from llama_cpp import Llama
    if llm_path not in _llm_cache:
        ui_logger.log(f"Loading local LLM model...")
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
        temperature=0.2,
        max_tokens=2048,
    )
    raw = resp["choices"][0]["message"]["content"].strip()
    parsed = _parse_json_loose(raw)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return parsed.get("highlights", [parsed])
    return []

def _refine_clip(llm, system: str, schema: str, clip: dict, lines: list) -> dict:
    st = float(clip.get("start_time", 0))
    et = float(clip.get("end_time", 0))
    margin = 10
    
    clip_text = []
    for line in lines:
        m = re.match(r'^\[([\d\.]+)s\]', line.strip())
        if m:
            t = float(m.group(1))
            if st - margin <= t <= et + margin:
                clip_text.append(line)
                
    if not clip_text:
        return clip
        
    segment_text = "\n".join(clip_text)
    
    ui_logger.log(f"Refining clip '{clip.get('title', 'Untitled')}' (duration {int(et-st)}s) down to 30-90s...")
    prompt = (
        f"{VIRALITY_CRITERIA}\n\n"
        f"This segment is too long. Extract the SINGLE most engaging, viral 30 to 90 second sub-clip from this exact segment.\n"
        f"It MUST be less than 90 seconds. Do not exceed 90 seconds.\n"
        f"Identify 'peak_moment', 'theme', 'broll_keywords', and 'emoji_moments' as before.\n\n"
        f"Segment:\n{segment_text}\n\n"
        f"Respond ONLY with a JSON array containing ONE element:\n{schema}"
    )
    
    try:
        results = _query_llm(llm, system, prompt)
        if results and len(results) > 0:
            new_clip = results[0]
            new_st = float(new_clip.get("start_time", 0))
            new_et = float(new_clip.get("end_time", 0))
            if 15 <= (new_et - new_st) <= 120:
                if not new_clip.get("title") or len(new_clip.get("title", "")) < 5:
                    new_clip["title"] = clip.get("title", "Refined Clip")
                return new_clip
    except Exception as e:
        ui_logger.log(f"Refinement failed: {e}")
        
    return clip


def get_highlights(
    transcript_data,
    num_clips: int = 5,
    llm_path: str = "",
    gpu_layers: int = 35,
    max_clips: int = 20,
    language: str = "",
) -> dict:
    if isinstance(transcript_data, dict):
        segs = transcript_data.get("segments", [])
        text = "\n".join(f"[{s['start']:.1f}s] {s['text'].strip()}" for s in segs)
    elif isinstance(transcript_data, list):
        chunks_words = []
        for i in range(0, len(transcript_data), 15):
            group = transcript_data[i:i+15]
            if group:
                st = group[0]['start']
                phrase = " ".join(w['word'] for w in group)
                chunks_words.append(f"[{st:.1f}s] {phrase}")
        text = "\n".join(chunks_words)
    elif isinstance(transcript_data, tuple):
        text = transcript_data[0]
    else:
        text = str(transcript_data)

    if not llm_path:
        raise RuntimeError("llm_path is required for local highlight detection.")

    llm = _get_llm(llm_path, gpu_layers)

    lang_hint = f" The transcript is in {language}." if language else ""
    system = (
        "You are an expert short-form content strategist for TikTok/Reels/Shorts."
        f"{lang_hint}"
        " You output ONLY raw JSON."
    )
    schema = (
        '[\n'
        '  {\n'
        '    "title": "A short engaging title",\n'
        '    "start_time": 12.5,\n'
        '    "end_time": 45.0,\n'
        '    "score": 95,\n'
        '    "hook_sentence": "The exact hook sentence spoken",\n'
        '    "virality_reason": "Why this works",\n'
        '    "peak_moment": 30.5,\n'
        '    "theme": "Educational",\n'
        '    "broll_keywords": [{"start_time": 15.0, "keyword": "rocket"}],\n'
        '    "emoji_moments": [{"start_time": 20.0, "emoji_unicode": "🤯"}]\n'
        '  }\n'
        ']'
    )

    chunks = [text[i:i + CHUNK_CHARS] for i in range(0, max(len(text), 1), CHUNK_CHARS)]
    clips_per_chunk = max(3, max_clips // len(chunks))
    all_highlights = []

    for idx, chunk in enumerate(chunks):
        ui_logger.log(f"LLM Analysing chunk {idx + 1}/{len(chunks)}...")
        prompt = (
            f"{VIRALITY_CRITERIA}\n\n"
            f"Analyse this transcript and extract the TOP {clips_per_chunk} most engaging COMPLETE STORIES. "
            f"Each clip must be a cohesive narrative arc (Hook -> Body -> Payoff) between 30 to 90 seconds long. "
            f"Do NOT fragment the clip. Just provide the overall start_time and end_time of the story block. "
            f"Identify the 'peak_moment' (exact timestamp where the punchline or highest energy hits). "
            f"Classify the overall 'theme' of the clip into exactly one of: Motivation, Educational, Comedy, Suspense, Storytime. "
            f"Also, provide 1 or 2 'broll_keywords' (visual nouns) and 1 or 2 'emoji_moments' (a single unicode emoji character like 🚀) with their exact timestamps to increase retention.\n\n"
            f"Transcript:\n{chunk}\n\n"
            f"Respond ONLY with a JSON array:\n{schema}"
        )
        try:
            results = _query_llm(llm, system, prompt)
            all_highlights.extend(results)
        except Exception as e:
            ui_logger.log(f"Warning: chunk {idx + 1} failed — {e}")

    ui_logger.log(f"LLM extracted {len(all_highlights)} potential clips. Processing and scoring...")
    valid = []
    lines = text.split('\n')
    for h in all_highlights:
        try:
            st = float(h.get("start_time", 0))
            et = float(h.get("end_time", 0))
            dur = et - st

            if dur > 90:
                h = _refine_clip(llm, system, schema, h, lines)
                st = float(h.get("start_time", 0))
                et = float(h.get("end_time", 0))
                dur = et - st

            if dur >= 15:
                h["duration"] = dur
                h["score"] = max(0, min(100, int(h.get("score", 50))))
                h["peak_moment"] = float(h.get("peak_moment", st + dur/2))

                theme = h.get("theme", "Storytime")
                if theme not in ["Motivation", "Educational", "Comedy", "Suspense", "Storytime"]:
                    theme = "Storytime"
                h["theme"] = theme

                h["broll_keywords"] = h.get("broll_keywords", [])
                h["emoji_moments"] = h.get("emoji_moments", [])

                valid.append(h)
        except (ValueError, TypeError, KeyError):
            continue

    valid.sort(key=lambda x: x["score"], reverse=True)

    seen, deduped = set(), []
    for h in valid:
        key = round(h["start_time"], -1)
        if key not in seen:
            seen.add(key)
            deduped.append(h)

    final_clips = deduped[:max_clips]
    ui_logger.log(f"Finished. Identified {len(final_clips)} top viral clips.")
    return {"highlights": final_clips}

get_viral_clips = get_highlights
