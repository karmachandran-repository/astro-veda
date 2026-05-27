import requests
import json
import time

url = "http://localhost:11434/api/generate"
payload = {
    "model": "gemma4:e4b",
    "prompt": "Chart: {'ascendant': {'sign': 'Gemini'}}\nRule: Rule: Gulika in the first house makes the native courageous.\nWrite a very short 1-paragraph Vedic reading prioritizing the rule.",
    "stream": False,
    "options": {
        "num_ctx": 8192
    }
}

print("Sending non-streaming request...")
start = time.time()
try:
    res = requests.post(url, json=payload, timeout=120)
    duration = time.time() - start
    print(f"Completed in {duration:.2f} seconds!")
    print("Response status:", res.status_code)
    print("Response text snippet:")
    print(res.json().get("response", "No response field"))
except Exception as e:
    print("Error:", e)
