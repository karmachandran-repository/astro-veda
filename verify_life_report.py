import urllib.request
import urllib.parse
import json
import sys

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        # Fallback for older python versions without reconfigure
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def test_life_report_stream():
    print("--- Running server Personal Life Report streaming verification ---")
    
    params = {
        "dob": "1966-05-25",
        "tob": "16:58",
        "tz_offset": "+05:30",
        "lat": 8.9602,
        "lon": 76.6788,
        "ayanamsha": "raman",
        "gender": "Female",
        "prediction_date": "2026-05-26"
    }
    
    query_str = urllib.parse.urlencode(params)
    url = f"http://localhost:8000/api/life-report/stream?{query_str}"
    
    print(f"Querying endpoint: {url}")
    
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as response:
            print(f"Response status: {response.status}")
            assert response.status == 200, f"Expected status 200, got {response.status}"
            
            print("Reading SSE stream chunks...")
            chunks_count = 0
            has_content = False
            
            # Read first 10 non-empty lines from the stream
            for _ in range(30):
                line = response.readline().decode('utf-8')
                if not line:
                    break
                line_stripped = line.strip()
                if line_stripped.startswith("data: "):
                    chunks_count += 1
                    data_json = json.loads(line_stripped[6:])
                    content = data_json.get("content", "")
                    if content:
                        has_content = True
                        print(content, end="", flush=True)
            
            print("\n...")
            print(f"Read {chunks_count} data chunks successfully.")
            assert chunks_count > 0, "No data chunks received from SSE stream!"
            assert has_content, "Data chunks contain no text content!"
            
            print("\nSUCCESS: Personal Life Report stream verification passed perfectly!")
            
    except Exception as e:
        print(f"\nFAILED Personal Life Report verification: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_life_report_stream()
