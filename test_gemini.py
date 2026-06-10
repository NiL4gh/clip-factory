import sys
import os

# Add the clip-factory dir to sys path to allow importing highlights
sys.path.insert(0, os.path.abspath('.'))

from shorts_generator.highlights import _execute_with_fallback, _parse_json_loose

test_sys = "You are an AI."
test_prompt = "Return a JSON array with one test highlight."

res = _execute_with_fallback("api:gemini:gemini-2.5-flash", test_sys, test_prompt, max_tokens=1000)
print("Result from Gemini:", res)
