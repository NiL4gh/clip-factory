import json
import re
from llama_cpp import Llama

def get_viral_clips(transcript, llm_path, gpu_layers):
    llm = Llama(model_path=llm_path, n_gpu_layers=gpu_layers, n_ctx=8192, verbose=False)
    
    prompt = f"""
    Analyze this transcript for high-retention viral segments (30-60s).
    Grade each clip on Hook, Flow, and Payoff. 
    
    Transcript: {transcript[:8000]}

    Return ONLY a JSON array:
    [{{
      "start": int, 
      "end": int, 
      "title": "string", 
      "score": int, 
      "reason": "string"
    }}]
    """
    
    resp = llm.create_chat_completion(
        messages=[{"role": "system", "content": "You are a viral strategist. Output raw JSON."},
                  {"role": "user", "content": prompt}],
        temperature=0.3
    )
    
    raw = resp["choices"][0]["message"]["content"].strip()
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    return json.loads(match.group()) if match else []
