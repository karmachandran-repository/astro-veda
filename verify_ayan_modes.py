import json
import sys
from server import calculate_d1_chart

dob = "1966-08-29"
tob = "03:15"
tz_offset = "+05:30"
lat = 9.267
lon = 76.55

results = {}
for mode in ['lahiri', 'raman', 'pushya']:
    print(f"\n--- Calculating D1 chart under {mode.upper()} Ayanamsha ---")
    res_str = calculate_d1_chart(dob, tob, tz_offset, lat, lon, ayanamsha=mode)
    data = json.loads(res_str)
    
    # Extract metadata and values
    meta = data["metadata"]["ayanamsha"]
    moon = data["planets"]["Moon"]
    dasha = data["dasha_timeline"]
    
    print(f"Metadata Ayanamsha: {meta}")
    print(f"Moon: Longitude={moon['longitude']}, Nakshatra={moon['nakshatra']} (Lord={moon['nakshatra_lord']})")
    print(f"Dasha Balance: {dasha['dasha_balance']}")
    
    results[mode] = {
        "longitude": moon['longitude'],
        "nakshatra": moon['nakshatra'],
        "balance_years": dasha['dasha_balance']['years']
    }

print("\n--- Validating Mathematical Distinctions ---")
try:
    # Assertions
    assert results['lahiri']['longitude'] != results['raman']['longitude'], "Lahiri and Raman moon longitudes should be distinct!"
    assert results['raman']['longitude'] != results['pushya']['longitude'], "Raman and Pushya moon longitudes should be distinct!"
    assert results['lahiri']['longitude'] != results['pushya']['longitude'], "Lahiri and Pushya moon longitudes should be distinct!"
    
    print("\nSUCCESS: Dynamic Ayanamsha selections are mathematically distinct and perfectly configured!")
except Exception as e:
    print(f"\nFAILED verification: {e}")
    sys.exit(1)
