import urllib.request
import json

try:
    print("Testing connection to http://localhost:8000/ ...")
    with urllib.request.urlopen("http://localhost:8000/") as response:
        html = response.read().decode('utf-8')
        print(f"Response status: {response.status}")
        print(f"HTML starts with: {html[:100]}")
    
    print("\nTesting connection to http://localhost:8000/api/panchang ...")
    with urllib.request.urlopen("http://localhost:8000/api/panchang") as response:
        data = json.loads(response.read().decode('utf-8'))
        print(f"Response status: {response.status}")
        print(f"Panchang data: {list(data.keys())}")
        
    print("\nTesting connection to http://localhost:8000/api/prediction/stream ...")
    # Stream for a bit
    req = urllib.request.Request("http://localhost:8000/api/prediction/stream")
    with urllib.request.urlopen(req) as response:
        print(f"Response status: {response.status}")
        print("Reading first 3 lines of SSE stream...")
        for _ in range(3):
            line = response.readline().decode('utf-8')
            if line:
                print(line.strip())
                
    print("\nTesting connection to http://localhost:8000/api/chart ...")
    # POST to chart
    chart_req = {
        "dob": "1966-05-25",
        "tob": "16:58",
        "tz_offset": "+05:30",
        "lat": 8.9602,
        "lon": 76.6788,
        "ayanamsha": "raman",
        "prediction_date": "2026-05-26",
        "gender": "Female"
    }
    req_post = urllib.request.Request(
        "http://localhost:8000/api/chart",
        data=json.dumps(chart_req).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req_post) as response:
        chart_data = json.loads(response.read().decode('utf-8'))
        print(f"Response status: {response.status}")
        print(f"Chart data contains lagna_sign: {chart_data.get('lagna_sign')}")
        print(f"Chart planets count: {len(chart_data.get('planets', {}))}")

    print("\nALL LOCALHOST CHECKS PASSED!")
except Exception as e:
    print(f"\nLOCALHOST CHECK FAILED: {e}")
    import traceback
    traceback.print_exc()
