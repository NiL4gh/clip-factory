"""
Local LLM highlight detection using llama-cpp-python.
Drop-in replacement — same get_highlights() / get_viral_clips() interface.
"""
import json
import re
from typing import Dict, List

_llm_cache = {}


def _get_llm(llm_path: str, gpu_layers: int = 35):
    from llama_cpp import Llama

    if llm_path not in _llm_cache:
        print(f"  [llm] Loading model from {llm_path} ...")
        # n_ctx=0 tells llama.cpp to use the model's native max context (32768 for Mistral).
        # n_gpu_layers=35 offloads most layers to the T4 GPU.
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

# ── Memory-safe chunking ──────────────────────────────────────────────────────
