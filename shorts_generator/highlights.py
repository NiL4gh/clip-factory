"""
Local LLM highlight detection using llama-cpp-python.
"""
import json
import re

_llm_cache = {}

VIRALITY_CRITERIA = """
Virality signals (ranked by impact):
1. HOOK MOMENTS — "Nobody talks about...", "I was wrong about..."
2. EMOTIONAL PEAKS — surprise, laughter, anger, vulnerability
3. OPINION BOMBS — strong, polarizing statements
4. REVELATION MOMENTS — surprising facts that reframe thinking
5. CONFLICT/TENSION — disagreement confronted head-on
6. QUOTABLE ONE-LINERS — works as a standalone quote
7. STORY PEAKS — the climax or twist of an anecdote
8. PRACTICAL VALUE — a concrete tip the viewer can apply
"""

# Max characters to send per chunk. At ~4 chars/token, 40k chars ≈ 10k tokens,
# well inside Mistral's 32k window while leaving room for prompt + output.
CHUNK_CHARS = 40_000


def _get_llm(llm_path: str, gpu_layers: int = 35):
    from llama_cpp import Llama
    if llm_path not in _llm_cache:
        print(f"  [llm] Loading model from {llm_path} ...")
        # n_ctx=0  → use the model's own native max context (32 768 for Mistral)
        # n_gpu_layers=35 → offload most layers to T4 GPU
        _llm_cache[llm_path] = Llama(
            model_path=llm_path,
            n_gpu_layers=gpu_layers,
            n_ctx=0,
            verbose=False,
        )
        print("  [llm] Ready.")
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
    return json.loads(text)


def _query_llm(llm, system: str, prompt: str) -> list:
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
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return parsed.get("highlights", [parsed])
    return []


def get_highlights(
    transcript_data,
    num_clips: int = 3,
    llm_path: str = "",
    gpu_layers: int = 35,
) -> dict:
    """
    transcript_data: plain string  OR  dict with {"segments": [...]}
                     OR  (full_text, word_timestamps) tuple from transcriber.py
    Returns {"highlights": [{title, start_time, end_time, score, hook_sentence, virality_reason}]}
    """
    # Normalise transcript to a single string
    if isinstance(transcript_data, dict):
        segs = transcript_data.get("segments", [])
        text = "\n".join(f"[{s['start']:.1f}s] {s['text'].strip()}" for s in segs)
    elif isinstance(transcript_data, tuple):
        text = transcript_data[0]
    else:
        text = str(transcript_data)

    if not llm_path:
        raise RuntimeError("llm_path is required for local highlight detection.")

    llm   = _get_llm(llm_path, gpu_layers)
    system = (
        "You are an expert YouTube Shorts viral strategist. "
        "You output ONLY raw JSON with no markdown, no explanation."
    )

    schema = (
        '[{"title":"string","start_time":float,"end_time":float,'
        '"score":int,"hook_sentence":"string","virality_reason":"string"}]'
    )

    all_highlights = []

    # Split transcript into chunks so we never exceed context
    chunks = [text[i:i + CHUNK_CHARS] for i in range(0, len(text), CHUNK_CHARS)]
    clips_per_chunk = max(1, num_clips // len(chunks) + 1)

    for idx, chunk in enumerate(chunks):
        print(f"  [llm] Analysing chunk {idx + 1}/{len(chunks)} ...")
        prompt = (
            f"{VIRALITY_CRITERIA}\n\n"
            f"Analyse this transcript chunk and extract the TOP {clips_per_chunk} most engaging, "
            f"self-contained segments (30–90 seconds each) with a strong hook.\n\n"
            f"Transcript:\n{chunk}\n\n"
            f"Respond ONLY with a JSON array:\n{schema}"
        )
        try:
            results = _query_llm(llm, system, prompt)
            all_highlights.extend(results)
        except Exception as e:
            print(f"  [llm] Warning: chunk {idx + 1} failed — {e}")

    # Deduplicate overlapping clips (keep highest score)
    all_highlights = sorted(all_highlights, key=lambda x: int(x.get("score", 0)), reverse=True)
    seen, deduped = set(), []
    for h in all_highlights:
        key = round(float(h.get("start_time", 0)), 0)
        if key not in seen:
            seen.add(key)
            deduped.append(h)

    return {"highlights": deduped[:num_clips]}


# Legacy alias
get_viral_clips = get_highlights
