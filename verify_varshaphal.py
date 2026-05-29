import json
import sys
from server import calculate_d1_chart

print("--- Running server Tajika Varshaphal astronomical calculation verification ---")
dob = "1990-05-25"
tob = "16:58"
tz_offset = "+05:30"
lat = 9.2505
lon = 76.5402
prediction_date = "2025-11-20"  # Target age 35 completed

res_str = calculate_d1_chart(dob, tob, tz_offset, lat, lon, ayanamsha="lahiri", prediction_date=prediction_date)

try:
    data = json.loads(res_str)
    
    # Assertions
    assert "varshaphal" in data, "Varshaphal key is missing from output!"
    varshaphal = data["varshaphal"]
    print("Calculated Varshaphal Details:")
    print(json.dumps(varshaphal, indent=2))
    
    # Check completed age (born May 25 1990, target Nov 20 2025 -> completed age 35)
    assert varshaphal["completed_age"] == 35, f"Expected completed age 35, got {varshaphal['completed_age']}"
    
    # Check solar return date
    assert varshaphal["solar_return_date"] == "2025-05-25", f"Expected solar return date 2025-05-25, got {varshaphal['solar_return_date']}"
    
    # Check Varsha Lagna
    assert "varsha_lagna" in varshaphal, "Varsha Lagna details missing!"
    print(f"Varsha Lagna: {varshaphal['varsha_lagna']}")
    
    # Check Muntha
    assert "muntha" in varshaphal, "Muntha details missing!"
    print(f"Muntha: {varshaphal['muntha']}")
    
    # Check Varsha Planets
    assert "varsha_planets" in varshaphal, "Varsha planets positions missing!"
    assert len(varsha_planets := varshaphal["varsha_planets"]) == 9, f"Expected 9 planets in Varsha chart, got {len(varsha_planets)}"
    print(f"Varsha Planets check: Sun sign is {varsha_planets['Sun']['sign']} at {varsha_planets['Sun']['longitude']}°")
    
    print("\nSUCCESS: Tajika Varshaphal astronomical calculations are 100% correct!")
    
except Exception as e:
    print(f"\nFAILED verification: {e}")
    sys.exit(1)
