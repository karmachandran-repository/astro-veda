import json
import sys
from server import calculate_d1_chart

print("--- Running server Vimshottari Dasha and Nakshatra calculations verification ---")
dob = "1966-08-29"
tob = "03:15"
tz_offset = "+05:30"
lat = 9.267
lon = 76.55

res_str = calculate_d1_chart(dob, tob, tz_offset, lat, lon)
print("Returned JSON String:")
print(res_str[:500] + "...")

print("\n--- Validating Output ---")
try:
    data = json.loads(res_str)
    
    # Assertions
    assert "ascendant" in data, "Lagna data is missing!"
    assert "planets" in data, "Core planets data is missing!"
    assert "upagrahas" in data, "Upagrahas data is missing!"
    assert "special_points" in data, "special_points key is missing!"
    assert "dasha_timeline" in data, "dasha_timeline key is missing!"
    
    # Assert Lagna fields
    asc = data["ascendant"]
    print(f"Lagna Cusp: {asc}")
    assert asc["nakshatra"] == "Punarvasu", f"Lagna Nakshatra should be Punarvasu, got {asc['nakshatra']}"
    assert asc["nakshatra_lord"] == "Jupiter", f"Lagna Nakshatra Lord should be Jupiter, got {asc['nakshatra_lord']}"
    
    # Assert Moon
    moon = data["planets"]["Moon"]
    print(f"Moon: {moon}")
    assert moon["nakshatra"] == "Shravana", f"Moon Nakshatra should be Shravana, got {moon['nakshatra']}"
    assert moon["nakshatra_lord"] == "Moon", f"Moon Nakshatra Lord should be Moon, got {moon['nakshatra_lord']}"
    
    # Assert Gulika - computed via classical weekday-slot formula (Scorpio / Jyeshtha, house 6)
    gulika = data["special_points"]["Gulika"]
    print(f"Gulika: {gulika}")
    assert gulika["nakshatra"] == "Jyeshtha", f"Gulika Nakshatra should be Jyeshtha, got {gulika['nakshatra']}"
    
    # Assert Dasha timeline
    dasha = data["dasha_timeline"]
    print(f"Dasha Balance at Birth: {dasha['dasha_balance']}")
    timeline = dasha["timeline"]
    print(f"Timeline entries: {len(timeline)}")
    assert len(timeline) > 0, "Dasha timeline array is empty!"
    
    # Verify first entry
    first = timeline[0]
    print(f"First dasha: {first}")
    assert first["dasha"] == "Moon", f"First dasha should be Moon, got {first['dasha']}"
    assert first["start_date"] == "1966-08-29", f"First dasha start date should be 1966-08-29, got {first['start_date']}"
    
    # Verify sequence
    assert timeline[1]["dasha"] == "Mars"
    assert timeline[2]["dasha"] == "Rahu"
    assert timeline[3]["dasha"] == "Jupiter"
    
    print("\nSUCCESS: Dasha and Nakshatra server calculations are 100% correct!")
    
except Exception as e:
    print(f"\nFAILED verification: {e}")
    sys.exit(1)
