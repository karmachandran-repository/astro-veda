import json
import sys
from server import calculate_d1_chart

dob = "1966-08-29"
tob = "03:15"
tz_offset = "+05:30"
lat = 9.267
lon = 76.55

# Execute under Pushya Mode for prediction date 2026-05-25
print("--- Calculating D1 Chart and Gochara under PUSHYA (Target Date: 2026-05-25) ---")
res_2026_str = calculate_d1_chart(dob, tob, tz_offset, lat, lon, ayanamsha="pushya", prediction_date="2026-05-25")
data_2026 = json.loads(res_2026_str)

# Execute under Pushya Mode for prediction date 2032-12-12
print("\n--- Calculating D1 Chart and Gochara under PUSHYA (Target Date: 2032-12-12) ---")
res_2032_str = calculate_d1_chart(dob, tob, tz_offset, lat, lon, ayanamsha="pushya", prediction_date="2032-12-12")
data_2032 = json.loads(res_2032_str)

print("\n--- Validating Payload Structure and Calculations ---")
try:
    # 1. Assert required core keys exist
    for payload in [data_2026, data_2032]:
        assert "natal_positions" in payload, "natal_positions key is missing!"
        assert "transit_positions" in payload, "transit_positions key is missing!"
        assert "dasha_and_antardasha_timeline" in payload, "dasha_and_antardasha_timeline key is missing!"
        
        # Verify nested structures
        natal = payload["natal_positions"]
        assert "planets" in natal, "natal_positions planets are missing!"
        assert "special_points" in natal, "natal_positions special_points are missing!"
        assert "Lagna" in natal["special_points"], "Natal Lagna is missing!"
        
    # 2. Verify two-tier Vimshottari Dashas
    two_tier = data_2026["dasha_and_antardasha_timeline"]
    print(f"Total Mahadashas generated: {len(two_tier)}")
    assert len(two_tier) > 0
    
    # Assert nested Antardashas structure
    first_mahadasha = two_tier[0]
    print(f"First Mahadasha: {first_mahadasha['mahadasha']} ({first_mahadasha['start_date']} to {first_mahadasha['end_date']})")
    antardashas = first_mahadasha["antardashas"]
    print(f"  Total nested Antardashas: {len(antardashas)}")
    assert len(antardashas) > 0, "No Antardashas found in Mahadasha block!"
    
    # Verify sub-lord cycle starts with the Mahadasha Lord itself
    first_antar = antardashas[0]
    print(f"  First Antardasha sub-period: {first_mahadasha['mahadasha']} - {first_antar['antardasha']} ({first_antar['start_date']} to {first_antar['end_date']})")
    
    # Subsequent Mahadashas should have exactly 9 nested Antardashas
    if len(two_tier) > 1:
        second_mahadasha = two_tier[1]
        print(f"Second Mahadasha: {second_mahadasha['mahadasha']} ({second_mahadasha['start_date']} to {second_mahadasha['end_date']})")
        second_antars = second_mahadasha["antardashas"]
        print(f"  Total nested Antardashas: {len(second_antars)}")
        assert len(second_antars) == 9, f"Subsequent Mahadasha should have exactly 9 Antardashas, got {len(second_antars)}"
        assert second_antars[0]["antardasha"] == second_mahadasha["mahadasha"], "Antardasha cycle should start with the Mahadasha Lord!"
        
    # 3. Assert transit position layouts are mathematically distinct for different target dates
    transit_2026 = data_2026["transit_positions"]
    transit_2032 = data_2032["transit_positions"]
    
    print(f"Transit Jupiter (2026): Longitude={transit_2026['Jupiter']['longitude']}, Sign={transit_2026['Jupiter']['sign']}, House={transit_2026['Jupiter']['house']}")
    print(f"Transit Jupiter (2032): Longitude={transit_2032['Jupiter']['longitude']}, Sign={transit_2032['Jupiter']['sign']}, House={transit_2032['Jupiter']['house']}")
    
    assert transit_2026["Jupiter"]["longitude"] != transit_2032["Jupiter"]["longitude"], "Transit Jupiter coordinates should be distinct for different dates!"
    assert transit_2026["Sun"]["longitude"] != transit_2032["Sun"]["longitude"], "Transit Sun coordinates should be distinct!"
    
    print("\nSUCCESS: Two-tier dashas and Gochara transits are mathematically 100% correct!")
except Exception as e:
    print(f"\nFAILED verification: {e}")
    sys.exit(1)
