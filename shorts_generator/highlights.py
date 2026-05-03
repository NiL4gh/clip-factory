"""
Local LLM highlight detection using llama-cpp-python.
"""
import json
import re

_llm_cache = {}

VIRALITY_CRITERIA = """
Virality signals (ranked by impact):
1. HOOK MOMENTS — creates immediate curiosity
2. EMOTIONAL PEAKS — genuine surprise, laughter, anger, vulnerability
3. OPINION BOMBS — strong, polarizing statements
4. REVELATION MOMENTS — surprising facts
5. QUOTABLE ONE-LINERS — perfect standalone quotes
"""

CHUNK_CHARS = 40_000

def _get_llm(llm_path: str, gpu_layers: int = 35):
    from llama_cpp import Llama
    if llm_path not in _llm_cache:
        print(f"  [llm] Loading {llm_path} ...")
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
    elif isinstance(transcript_data, tuple):
        text = transcript_data[0]
    else:
        text = str(transcript_data)

    if not llm_path:
        raise RuntimeError("llm_path is required for local highlight detection.")

    llm = _get_llm(llm_path, gpu_layers)

    lang_hint = f" The transcript is in {language}." if language else ""
    system = (
        "You are an expert short-form content strategist."
        f"{lang_hint}"
        " You output ONLY raw JSON."
    )
    schema = (
        '[{{"title":"string","segments":[{{"start_time":float,"end_time":float}}],'
        '"score":int,"hook_sentence":"string","virality_reason":"string","peak_moment":float,'
        '"theme":"string(Motivation|Educational|Comedy|Suspense|Storytime)"}}]'
    )

    chunks = [text[i:i + CHUNK_CHARS] for i in range(0, max(len(text), 1), CHUNK_CHARS)]
    clips_per_chunk = max(3, max_clips // len(chunks))
    all_highlights = []

    for idx, chunk in enumerate(chunks):
        print(f"  [llm] Analysing chunk {idx + 1}/{len(chunks)} ...")
        prompt = (
            f"{VIRALITY_CRITERIA}\n\n"
            f"Analyse this transcript and extract the TOP {clips_per_chunk} most engaging clips "
            f"with a strong hook. Create 'smart multi-segment clips' by skipping boring filler. "
            f"Each clip must have an array of 'segments' (start and end times) that join together to form a punchy 15-60 second video. "
            f"Identify the 'peak_moment' (exact timestamp where the punchline or highest energy hits). "
            f"Classify the overall 'theme' of the clip into exactly one of: Motivation, Educational, Comedy, Suspense, Storytime.\n\n"
            f"Transcript:\n{chunk}\n\n"
            f"Respond ONLY with a JSON array:\n{schema}"
        )
        try:
            results = _query_llm(llm, system, prompt)
            all_highlights.extend(results)
        except Exception as e:
            print(f"  [llm] Warning: chunk {idx + 1} failed \u2014 {e}")

    valid = []
    for h in all_highlights:
        try:
            # Backwards compat
            if "segments" not in h and "start_time" in h and "end_time" in h:
                h["segments"] = [{"start_time": float(h["start_time"]), "end_time": float(h["end_time"])}]
            
            if not h.get("segments"):
                continue
                
            total_dur = 0
            valid_segs = []
            for seg in h["segments"]:
                st = float(seg.get("start_time", 0))
                et = float(seg.get("end_time", 0))
                if et > st:
                    valid_segs.append({"start_time": st, "end_time": et})
                    total_dur += (et - st)
            
            if total_dur >= 5 and valid_segs:
                h["segments"] = valid_segs
                h["start_time"] = valid_segs[0]["start_time"]
                h["end_time"] = valid_segs[-1]["end_time"]
                h["duration"] = total_dur
                h["score"] = max(0, min(100, int(h.get("score", 50))))
                h["peak_moment"] = float(h.get("peak_moment", h["start_time"] + total_dur/2))
                
                theme = h.get("theme", "Storytime")
                if theme not in ["Motivation", "Educational", "Comedy", "Suspense", "Storytime"]:
                    theme = "Storytime"
                h["theme"] = theme
                
                valid.append(h)
        except (ValueError, TypeError, KeyError):
            continue

    valid.sort(key=lambda x: x["score"], reverse=True)

    seen, deduped = set(), []
    for h in valid:
        key = round(h["start_time"], 0)
        if key not in seen:
            seen.add(key)
            deduped.append(h)

    return {"highlights": deduped[:max_clips]}

get_viral_clips = get_highlights
