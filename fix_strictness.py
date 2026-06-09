import re

with open('shorts_generator/highlights.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Fix strictness for provided topics
text = text.replace(
    'Extract the best viral moments. If a section is genuinely boring or low energy, return an EMPTY array []. NEVER return clips that score below 75.\\n',
    'Extract the most engaging moments from this section. ALWAYS try to return at least 1-2 good clips unless the section is completely silent or unusable.\\n'
)

# Fix strictness and timestamp rule for auto-topics
target_auto = '''Extract ONLY the absolute best viral moments. If the section is boring or low energy, return an EMPTY array []. NEVER return clips that score below 85. Quality over quantity.\\n"
                    f"CRITICAL: Do NOT extract multiple overlapping clips from the same moment. If you find a great moment, extract ONE cohesive, fully-fleshed out clip (30-90s) rather than multiple overlapping fragments. Do NOT create duplicate variations of the same dialogue.\\n"
                    f"CRITICAL: Do NOT output timestamps. Only the exact spoken words.'''

replacement_auto = '''Extract the most engaging and interesting moments from this section. ALWAYS try to return at least 1-2 good clips (30-90s) even if it's an educational or slower-paced video.\\n"
                    f"CRITICAL: Do NOT extract multiple overlapping clips from the same moment. If you find a great moment, extract ONE cohesive, fully-fleshed out clip (30-90s). Do NOT create duplicate variations of the same dialogue.\\n"
                    f"CRITICAL: Do NOT include timestamp brackets (e.g., [12.4s]) inside start_quote or end_quote. Only output the raw spoken words. However, you MUST output the start_timestamp and end_timestamp floating-point keys in the JSON object itself.'''

text = text.replace(target_auto, replacement_auto)

# Also fix the fallback chunk section just in case
text = text.replace(
    'Extract ONLY the absolute best viral moments.\\n',
    'Extract the most engaging moments from this chunk. Try to return at least 1-2 good clips.\\n'
)

with open('shorts_generator/highlights.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Fixed LLM prompt strictness and JSON schema alignment in highlights.py.")
