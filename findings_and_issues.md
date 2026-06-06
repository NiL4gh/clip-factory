# ClipFactory Issue Diagnosis

This document contains the findings from investigating the issues reported by the user in the rendered clips and strategy extraction.

## 1. Header Text Style Never Changes
**Problem:** The user reported that changing the Title Style (e.g., "Impact", "Suits", "Yellow") in the UI has no effect on the rendered header text.
**Root Cause:** In `shorts_generator/clipper.py`'s `_generate_ass` function, when `magic_hook_text` is active (which it always is for the first segment `idx == 0` of a clip) and `hook_display` is `"full"` (the default), the `Header` ASS style is intentionally hidden. Instead, it renders the text using the `MagicHook` ASS style. The `MagicHook` style is strictly hardcoded (White text, Black outline, Drop shadow) and ignores the `TITLE_STYLE_PRESETS` (`ts`) entirely. Since most clips are short, the user only ever sees the hardcoded `MagicHook` style and never sees the actual `Header` style.
**Required Fix for Next Session:**
- Apply the `TITLE_STYLE_PRESETS` (colors, borders, shadows) to the `MagicHook` ASS style definition in `clipper.py`, OR
- Modify the logic so `MagicHook` respects the user's chosen `title_style` visually while maintaining its specific top/bottom positioning and font size.
- Ensure any mojibake in the text itself is properly handled with UTF-8 encoding in the API layer.

## 2. Captions Have Weird Symbols (Mojibake) and Massive Duplicates
**Problem:** The captions contain duplicate words on top of each other and weird symbols like `ðŸŽ¬`.
**Root Cause:** A recently introduced "SRT fast-path" in `server/main.py` downloads auto-generated YouTube subtitles using `yt-dlp --write-auto-sub --convert-subs srt`. YouTube's auto-generated subtitles are "rolling" captions, meaning the text is repeated across multiple subtitle blocks as it scrolls. The `parse_srt_to_word_timestamps` function in `transcriber.py` linearly interpolates words from these blocks without deduplication. This causes massive overlapping duplicates of the same words in `word_timestamps` and introduces VTT/SRT formatting artifacts (which show up as mojibake/weird symbols).
**Required Fix for Next Session:**
- The most robust fix is to disable/remove the flawed SRT fast-path (`download_srt` and `parse_srt_to_word_timestamps`) in `server/main.py` and always fall back to Faster-Whisper, which guarantees clean, non-duplicated, word-level timestamps.
- Alternatively, rewrite the downloader to fetch YouTube's `json3` subtitle format, which has precise word-level timestamps without rolling duplication. (Whisper fallback is safer and higher quality).
- Ensure Python's `open()` calls and JSON responses strictly use `encoding="utf-8"`.

## 3. Clip Strategy Has Duplicates (Short vs Long Versions)
**Problem:** The strategy extractor outputs duplicate clips for the same moment (e.g., one 15-second clip and one 25-second clip covering the exact same dialogue).
**Root Cause:** In `shorts_generator/highlights.py`, the LLM is prompted to extract clips per topic (`clips_per_topic = max(2, min(4, ...))`). The prompt does not explicitly forbid extracting overlapping variations of the same moment. The LLM tries to fulfill the "num_clips" quota by extracting multiple fragmented variations of the same core dialogue.
**Required Fix for Next Session:**
- Update the prompt in `get_highlights` (in `shorts_generator/highlights.py` lines 848 and 894) to add an explicit constraint: `"CRITICAL: Do NOT extract multiple overlapping clips from the same moment. If you find a great moment, extract ONE cohesive, fully-fleshed out clip (30-90s) rather than multiple overlapping fragments. Do NOT create duplicate variations of the same dialogue."`
- Implement a quick post-processing overlap deduplication in Python after the LLM returns the clips (e.g., sort clips by `score` or duration, and filter out any clip that overlaps more than 50% with a higher-priority clip).

## Next Steps
The next Claude session should read this file, formulate the exact code solutions for these three issues, and document them or prepare to implement them in the final session.

## Status
**RESOLVED:** All three issues were implemented in the previous session:
1. `MagicHook` dynamically inherits style from `TITLE_STYLE_PRESETS` in `clipper.py`.
2. SRT fast-path removed in `server/main.py`; explicit `encoding="utf-8"` added to cache saves in `cache.py`.
3. Highlight prompt constraint added and strict time-based deduplication logic implemented in `highlights.py`.
