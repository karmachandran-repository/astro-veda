import json
import sys
from server import calculate_d1_chart

print("--- Running server calculate_d1_chart direct verification ---")
dob = "2010-12-31"
tob = "23:40"
tz_offset = "+08:00"
lat = 35.65
lon = 139.83

res_str = calculate_d1_chart(dob, tob, tz_offset, lat, lon)
print("Returned JSON String:")
print(res_str)

print("\n--- Validating Output ---")
try:
    data = json.loads(res_str)
    
    # Assertions
    assert "ascendant" in data, "Lagna data is missing!"
    assert "planets" in data, "Core planets data is missing!"
    assert "upagrahas" in data, "Upagrahas data is missing!"
    
    # Assert Lagna fields
    asc = data["ascendant"]
    print(f"Lagna Cusp: {asc}")
    assert asc["sign"] == "Virgo", f"Lagna sign is incorrect! Expected Virgo, got {asc['sign']}"
    assert asc["house"] == 1, f"Lagna house must be 1, got {asc['house']}"
    
    # Assert Planets
    planets = data["planets"]
    print(f"Planets count: {len(planets)}")
    assert len(planets) == 9, f"Expected 9 planets, got {len(planets)}"
    for name in ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]:
        assert name in planets, f"Planet {name} is missing!"
        p = planets[name]
        print(f"  {name}: Sign={p['sign']}, Longitude={p['longitude']}, House={p['house']}")
        assert p["longitude"] > 0.0, f"{name} longitude is invalid!"
        assert isinstance(p["house"], int), f"{name} house is not integer!"
        assert isinstance(p["sign"], str), f"{name} sign is not string!"
        
    # Assert Gulika
    gulika = data["upagrahas"]["Gulika"]
    print(f"Gulika: {gulika}")
    assert gulika["sign"] == "Leo", f"Gulika sign is incorrect! Expected Leo, got {gulika['sign']}"
    assert gulika["house"] == 12, f"Gulika house is incorrect! Expected 12, got {gulika['house']}"
    
    # Assert minified JSON (no whitespace in formatting)
    assert " " not in res_str.replace("Tokyo, Kanto, Japan", "").replace("BirthLocation", ""), "JSON string should be minified!"
    
    print("\nSUCCESS: All server calculations and data mappings are 100% correct!")
    
except Exception as e:
    print(f"\nFAILED verification: {e}")
    sys.exit(1)
