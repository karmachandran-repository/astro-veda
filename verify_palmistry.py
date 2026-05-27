import sys
import json
import requests
from web_server import calculate_elements, compute_hasta_melapak, HandProfile

def run_tests():
    print("==================================================")
    print("ASTROVEDA VEDIC PALMISTRY (HASTA SAMUDRIKA) TEST SUITE")
    print("==================================================")

    # Test 1: Hand Profile Element Profiler Math Calculations
    print("\n--- Test 1: Prakriti Hand Element Profiler Math Calculations ---")
    
    # Square shape (+20 Prithvi/Vayu), Short fingers (+15 Prithvi/Agni), Dry skin (+20 Vayu), Pale tone (+10 Jala/Vayu)
    # Baseline for all elements: 10
    # Prithvi: 10 + 20 (Square) + 15 (Short) = 45
    # Jala: 10 + 10 (Pale) = 20
    # Agni: 10 + 15 (Short) = 25
    # Vayu: 10 + 20 (Square) + 20 (Dry) + 10 (Pale) = 60
    # Total = 45 + 20 + 25 + 60 = 150
    # Prithvi % = round(45 / 150 * 100) = 30%
    # Jala % = round(20 / 150 * 100) = 13%
    # Agni % = round(25 / 150 * 100) = 17%
    # Vayu % = round(60 / 150 * 100) = 40% (Dominant)
    
    e1 = calculate_elements(shape="Square", fingers="Short", skin="Dry", tone="Pale")
    print(f"Calculated Elements: {e1}")
    assert e1["Prithvi"] == 30, f"Expected Prithvi to be 30, got {e1['Prithvi']}"
    assert e1["Jala"] == 13, f"Expected Jala to be 13, got {e1['Jala']}"
    assert e1["Agni"] == 17, f"Expected Agni to be 17, got {e1['Agni']}"
    assert e1["Vayu"] == 40, f"Expected Vayu to be 40, got {e1['Vayu']}"
    assert max(e1, key=e1.get) == "Vayu", "Dominant element should be Vayu"
    print("PASS: Hand Profile Element calculations validated successfully.")

    # Test 2: Hasta Melapak Compatibility scoring Math Calculations
    print("\n--- Test 2: Hasta Melapak Compatibility Score Math Calculations ---")
    p1 = HandProfile(
        shape="Square",
        fingers="Short",
        skin="Dry",
        tone="Pale",
        lines={"ayur": "deep", "matri": "straight", "dharma": "jupiter", "bhagya": "wrist"},
        signs=["Matsya (Fish)"]
    )
    p2 = HandProfile(
        shape="Rectangle",
        fingers="Long",
        skin="Soft",
        tone="Pinkish",
        lines={"ayur": "chained", "matri": "straight", "dharma": "jupiter", "bhagya": "moon"},
        signs=["Kamala (Lotus)"]
    )
    
    # Calculate elements for p2:
    # Rectangle shape (+20 Jala/Agni), Long fingers (+15 Vayu/Jala), Soft skin (+20 Jala), Pinkish tone (+10 Jala/Vayu)
    # Baseline for all elements: 10
    # Prithvi: 10
    # Jala: 10 + 20 (Rectangle) + 15 (Long) + 20 (Soft) + 10 (Pinkish) = 75
    # Agni: 10 + 20 (Rectangle) = 30
    # Vayu: 10 + 15 (Long) + 10 (Pinkish) = 35
    # Total = 10 + 75 + 30 + 35 = 150
    # Jala % = round(75 / 150 * 100) = 50% (Dominant)
    
    # Compatibility between p1 (dominant Vayu) and p2 (dominant Jala):
    # harmony_matrix["Vayu"]["Jala"] = 12 Gunas
    # Heart Line agreement: both have 'jupiter' => +9 Gunas
    # Head Line agreement: both have 'straight' => +9 Gunas
    # Total compatibility: 12 + 9 + 9 = 30 / 36 Gunas.
    
    comp = compute_hasta_melapak(p1, p2)
    print(f"Melapak Score Result: {comp}")
    assert comp["p1_dom"] == "Vayu", f"Expected Partner 1 dominant to be Vayu, got {comp['p1_dom']}"
    assert comp["p2_dom"] == "Jala", f"Expected Partner 2 dominant to be Jala, got {comp['p2_dom']}"
    assert comp["elemental_harmony"] == 12, f"Expected elemental harmony to be 12, got {comp['elemental_harmony']}"
    assert comp["line_agreement"] == 18, f"Expected line agreement to be 18, got {comp['line_agreement']}"
    assert comp["total_score"] == 30, f"Expected total score to be 30, got {comp['total_score']}"
    print("PASS: Hasta Melapak Compatibility scoring calculations validated successfully.")

    # Live Server Endpoint Verifications
    BASE_URL = "http://127.0.0.1:8000"
    print(f"\n--- Hitting Live Server at {BASE_URL} ---")
    
    # Test 3: /api/palm/profile Endpoint
    print("\n--- Test 3: POST /api/palm/profile endpoint ---")
    profile_payload = {
        "shape": "Square",
        "fingers": "Short",
        "skin": "Dry",
        "tone": "Pale",
        "lines": {"ayur": "chained", "matri": "sloping", "dharma": "short", "bhagya": "moon"},
        "signs": ["Matsya (Fish)", "Trishula (Trident)"]
    }
    
    resp = requests.post(f"{BASE_URL}/api/palm/profile", json=profile_payload)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    resp_data = resp.json()
    assert resp_data["status"] == "success", "Endpoint status was not 'success'"
    assert "elements" in resp_data, "Missing elements key in response"
    assert "milestones" in resp_data, "Missing milestones key in response"
    assert resp_data["detected_signs"] == ["Matsya (Fish)", "Trishula (Trident)"], "Signs list does not match"
    
    # Verify custom milestones
    milestones = resp_data["milestones"]
    assert "chained" in milestones["Ayur (Life Line)"].lower() or "fluctuates" in milestones["Ayur (Life Line)"].lower(), "Incorrect Ayur milestone"
    assert "sloping" in milestones["Matri (Head Line)"].lower() or "creative" in milestones["Matri (Head Line)"].lower(), "Incorrect Matri milestone"
    assert "short" in milestones["Dharma (Heart Line)"].lower() or "practical" in milestones["Dharma (Heart Line)"].lower(), "Incorrect Dharma milestone"
    assert "moon" in milestones["Bhagya (Fate Line)"].lower() or "popularity" in milestones["Bhagya (Fate Line)"].lower(), "Incorrect Bhagya milestone"
    print("PASS: POST /api/palm/profile successfully returned correct data and milestones.")

    # Test 4: POST /api/palm/compatibility Endpoint
    print("\n--- Test 4: POST /api/palm/compatibility endpoint ---")
    compatibility_payload = {
        "partner1_name": "Devi",
        "partner1_profile": {
            "shape": "Square",
            "fingers": "Short",
            "skin": "Dry",
            "tone": "Pale",
            "lines": {"ayur": "deep", "matri": "straight", "dharma": "jupiter", "bhagya": "wrist"},
            "signs": ["Matsya (Fish)"]
        },
        "partner2_name": "Shiva",
        "partner2_profile": {
            "shape": "Rectangle",
            "fingers": "Long",
            "skin": "Soft",
            "tone": "Pinkish",
            "lines": {"ayur": "chained", "matri": "straight", "dharma": "jupiter", "bhagya": "moon"},
            "signs": []
        }
    }
    
    resp = requests.post(f"{BASE_URL}/api/palm/compatibility", json=compatibility_payload)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    resp_data = resp.json()
    assert resp_data["total_score"] == 30, f"Expected 30 points, got {resp_data['total_score']}"
    assert resp_data["p1_name"] == "Devi", "Partner 1 name incorrect"
    assert resp_data["p2_name"] == "Shiva", "Partner 2 name incorrect"
    print("PASS: POST /api/palm/compatibility successfully scored element and line dynamics.")

    # Test 5: GET /api/palm/stream SSE Endpoint
    print("\n--- Test 5: GET /api/palm/stream (SSE) streaming verification ---")
    stream_url = (
        f"{BASE_URL}/api/palm/stream?"
        f"shape=Square&fingers=Short&skin=Dry&tone=Pale&"
        f"ayur=deep&matri=straight&dharma=jupiter&bhagya=wrist&"
        f"signs=Matsya (Fish),Trishula (Trident)&"
        f"native_name=Devi&native_gender=Female"
    )
    
    # Send request with stream=True
    resp = requests.get(stream_url, stream=True)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert "text/event-stream" in resp.headers.get("Content-Type", ""), "Expected event-stream header"
    
    print("Reading stream chunks...")
    streamed_text = ""
    chunk_count = 0
    for line in resp.iter_lines():
        if line:
            decoded_line = line.decode("utf-8")
            if decoded_line.startswith("data: "):
                chunk_json = json.loads(decoded_line[6:])
                streamed_text += chunk_json["content"]
                chunk_count += 1
                
    print(f"Stream finished. Received {chunk_count} text chunks.")
    print("Excerpt of streamed response:")
    print("-" * 40)
    print(streamed_text[:350].encode("ascii", errors="replace").decode("ascii") + "...")
    print("-" * 40)
    
    assert "samudrika" in streamed_text.lower(), "Expected streamed response to contain palmistry reference"
    assert "vayu" in streamed_text.lower() or "element" in streamed_text.lower(), "Expected streamed response to contain element or constitution details"
    print("PASS: GET /api/palm/stream successfully streams palmistry analysis.")

    print("\n==================================================")
    print("ALL TESTS PASSED SUCCESSFULLY! Vedic Palmistry Verified.")
    print("==================================================")

if __name__ == "__main__":
    try:
        run_tests()
    except Exception as e:
        print(f"\nFAILED verification: {e}")
        sys.exit(1)
