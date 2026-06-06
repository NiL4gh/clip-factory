# Proposed Fixes for ClipFactory Issues

## 1. Header Text Style Never Changes
**File:** `shorts_generator/clipper.py`

**Solution:**
Update the `MagicHook` ASS style definition to dynamically read colors, outlines, and border styles from the user's chosen `TITLE_STYLE_PRESETS` (`ts`). This ensures the visual style respects the user's selection while maintaining the specific "hook" formatting (font size 60, predefined positioning).

```python
<<<<
        lines.append(f"Style: MagicHook,{font_name},60,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,6,3,{hook_align},40,40,{hook_margin},1")
====
        lines.append(f"Style: MagicHook,{font_name},60,{ts['PrimaryColour']}&,&H000000FF,{ts['OutlineColour']}&,{ts['BackColour']}&,1,0,0,0,100,100,0,0,{ts['BorderStyle']},{ts['Outline']},{ts['Shadow']},{hook_align},40,40,{hook_margin},1")
>>>>
```

## 2. Captions Have Weird Symbols (Mojibake) and Massive Duplicates
**Files:** `server/main.py` and `shorts_generator/cache.py`

**Solution:**
1. **Disable SRT Fast-Path**: Remove the flawed `download_srt` logic from `server/main.py` that parses rolling YouTube subtitles. We will fall back exclusively to Faster-Whisper to guarantee clean, accurate, non-duplicated word-level timestamps.
2. **Enforce UTF-8 in Cache**: Explicitly add `encoding="utf-8"` to all JSON file operations in `shorts_generator/cache.py` to prevent mojibake/encoding issues across OS environments.

**server/main.py**:
```python
<<<<
            # SRT fast-path: attempt YouTube subtitle download before running Whisper
            srt_path = download_srt(
                video_url=_state["current_url"],
                output_dir=str(WORK_DIR),
                video_id=_extract_video_id(_state["current_url"])
            )
            word_timestamps = []
            if srt_path:
                log("⚡ SRT subtitle found — skipping Whisper transcription")
                word_timestamps = parse_srt_to_word_timestamps(srt_path)
                if not word_timestamps:
                    log("⚠ SRT parse returned empty — falling back to Whisper")
                    srt_path = None
                else:
                    full_text = " ".join(w["word"] for w in word_timestamps)
                    cache.save_transcript(url.strip(), full_text, word_timestamps)
            if not srt_path:
                log("🎙 Running Faster-Whisper transcription...")
                full_text, word_timestamps = transcribe_audio(source_mp4, model_size=wsp_size, whisper_dir=WHISPER_DIR)
                cache.save_transcript(url.strip(), full_text, word_timestamps)
====
            # SRT fast-path disabled due to rolling subtitle duplicates and mojibake.
            # We strictly use Faster-Whisper to guarantee clean word-level timestamps.
            word_timestamps = []
            log("🎙 Running Faster-Whisper transcription...")
            full_text, word_timestamps = transcribe_audio(source_mp4, model_size=wsp_size, whisper_dir=WHISPER_DIR)
            cache.save_transcript(url.strip(), full_text, word_timestamps)
>>>>
```

**shorts_generator/cache.py**:
Add `encoding="utf-8"` to all `open()` calls. (Apply this to `save_metadata`, `save_transcript`, `load_transcript`, `save_highlights`, `load_highlights`, and `list_projects`). Example:
```python
<<<<
    with open(os.path.join(d, "metadata.json"), "w") as f:
====
    with open(os.path.join(d, "metadata.json"), "w", encoding="utf-8") as f:
>>>>
```

## 3. Clip Strategy Has Duplicates (Short vs Long Versions)
**File:** `shorts_generator/highlights.py`

**Solution:**
1. **Prompt Constraint:** Update the extraction prompts to explicitly forbid the LLM from outputting overlapping variations of the same core dialogue moment to meet its output quota.
2. **Time-Based Deduplication:** Update the post-LLM deduplication step. The current Jaccard similarity approach fails when a shorter fragment overlaps with a longer clip (because the union is too large, the similarity drops below 60%). The fix is to calculate proportional time overlap.

**shorts_generator/highlights.py** (Prompt Updates - applied to all extraction prompts):
```python
<<<<
                f"Extract ONLY the absolute best viral moments. If the section is boring or low energy, return an EMPTY array []. NEVER return clips that score below 85. Quality over quantity.\n"
====
                f"Extract ONLY the absolute best viral moments. If the section is boring or low energy, return an EMPTY array []. NEVER return clips that score below 85. Quality over quantity.\n"
                f"CRITICAL: Do NOT extract multiple overlapping clips from the same moment. If you find a great moment, extract ONE cohesive, fully-fleshed out clip (30-90s) rather than multiple overlapping fragments. Do NOT create duplicate variations of the same dialogue.\n"
>>>>
```

**shorts_generator/highlights.py** (Overlap Deduplication):
```python
<<<<
    # Dedup using content Jaccard similarity (>60% word overlap) (B5)
    def get_words_set(t_str):
        return set(re.findall(r'\w+', t_str.lower()))

    deduped = []
    for h in validated:
        h_words = get_words_set(h["ideal_transcript"])
        is_duplicate = False
        for existing in deduped:
            e_words = get_words_set(existing["ideal_transcript"])
            intersection = h_words.intersection(e_words)
            union = h_words.union(e_words)
            jaccard = len(intersection) / len(union) if union else 0.0
            if jaccard > 0.60:
                is_duplicate = True
                break
        if not is_duplicate:
            deduped.append(h)
====
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
>>>>
```