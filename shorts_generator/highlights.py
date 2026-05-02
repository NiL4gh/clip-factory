"""
Local LLM highlight detection using llama-cpp-python.
Drop-in replacement — same get_highlights() / get_viral_clips() interface.
"""
import json
import re
from typing import Dict, List

_llm_cache = {}


def _get_llm(llm_path: str, gpu_layers: int = 0):
    from llama_cpp import Llama
    
    # By setting n_ctx=0, we tell llama.cpp to read the model's native maximum 
    # context size (which is 32,768 for Mistral) instead of the 8k default.
    return Llama(
        model_path=llm_path, 
        n_gpu_layers=gpu_layers,
        n_ctx=0,  # <-- THIS IS THE CRITICAL FIX
        verbose=False
    )
        print("  [llm] Ready.")
    return _llm_cache[llm_path]


def _parse_json_loose(raw: str):
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # Try array first, then object
    for pattern in (r"\[.*\]", r"\{.*\}"):
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                continue
    return json.loads(text)


VIRALITY_CRITERIA = """
Virality signals (ranked by impact):
1. HOOK MOMENTS — creates immediate curiosity ("Nobody talks about...", "I was wrong about...")
2. EMOTIONAL PEAKS — genuine surprise, laughter, anger, vulnerability
3. OPINION BOMBS — strong, polarizing or counter-intuitive statements
4. REVELATION MOMENTS — surprising facts or confessions that reframe thinking
5. CONFLICT/TENSION — disagreement or a problem confronted head-on
6. QUOTABLE ONE-LINERS — a sentence that works as a standalone quote
7. STORY PEAKS — the climax or twist of an anecdote
8. PRACTICAL VALUE — a concrete tip the viewer can immediately apply
"""


def get_highlights(
    transcript_data,
    num_clips: int = 3,
    llm_path: str = "",
    gpu_layers: int = 35,
) -> Dict:
    """
    transcript_data: either a plain string (full transcript text)
                     or a dict with {"segments": [...]} from faster-whisper
    Returns {"highlights": [{title, start_time, end_time, score, hook_sentence, virality_reason}]}
    """
    # Accept both string and dict transcript formats
    if isinstance(transcript_data, dict):
        segs = transcript_data.get("segments", [])
        text = "\n".join(f"[{s['start']:.1f}s] {s['text'].strip()}" for s in segs)
    elif isinstance(transcript_data, tuple):
        # (full_text, word_timestamps) from transcriber.py
        text = transcript_data[0]
    else:
        text = str(transcript_data)

    if not llm_path:
        raise RuntimeError("llm_path is required for local highlight detection.")

    llm = _get_llm(llm_path, gpu_layers)

    system = (
        "You are an expert YouTube Shorts viral strategist. "
        "You output ONLY raw JSON with no markdown, no explanation."
    )

    prompt = (
        f"{VIRALITY_CRITERIA}\n\n"
        f"Analyze this transcript and extract the TOP {num_clips} most engaging, "
        f"self-contained segments (30–90 seconds each) with a strong hook.\n\n"
        f"Transcript:\n{text[:8000]}\n\n"
        f"Respond ONLY with a JSON array:\n"
        f'[{{"title":"string","start_time":float,"end_time":float,'
        f'"score":int,"hook_sentence":"string","virality_reason":"string"}}]'
    )

    resp = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.2,
        max_tokens=1024,
    )

    raw = resp["choices"][0]["message"]["content"].strip()
    parsed = _parse_json_loose(raw)

    # Normalise — model might return array or {"highlights": [...]}
    if isinstance(parsed, list):
        highlights = parsed
    elif isinstance(parsed, dict):
        highlights = parsed.get("highlights", [parsed])
    else:
        highlights = []

    # Sort by score descending
    highlights = sorted(highlights, key=lambda x: int(x.get("score", 0)), reverse=True)
    return {"highlights": highlights}


# Legacy alias
get_viral_clips = get_highlights
