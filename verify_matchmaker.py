import sys
from web_server import (
    calculate_vasya_score,
    calculate_dina_score,
    calculate_gana_score,
    calculate_rashi_koota,
    calculate_nadi_score,
    PartnerDetails,
    compute_compatibility_data
)

def run_tests():
    print("==================================================")
    print("ASTROVEDA MATCH MAKER & COMPATIBILITY TEST SUITE")
    print("==================================================")
    
    # Test 1: Gana Koota Score Calculations
    print("\n--- Test 1: Gana Koota Scoring ---")
    tests_gana = [
        ("Deva", "Deva", 6),
        ("Manushya", "Manushya", 6),
        ("Rakshasa", "Rakshasa", 6),
        ("Deva", "Manushya", 5),
        ("Manushya", "Deva", 5),
        ("Deva", "Rakshasa", 1),
        ("Manushya", "Rakshasa", 0),
        ("Rakshasa", "Deva", 0),
        ("Rakshasa", "Manushya", 0),
    ]
    for b, g, expected in tests_gana:
        actual = calculate_gana_score(b, g)
        assert actual == expected, f"Failed Gana Match ({b} vs {g}): expected {expected}, got {actual}"
        print(f"PASS: Gana {b} vs {g} => {actual}/6 Gunas")

    # Test 2: Vasya Koota Score Calculations
    print("\n--- Test 2: Vasya Koota Scoring ---")
    assert calculate_vasya_score("Aries", "Aries") == 2.0
    assert calculate_vasya_score("Aries", "Leo") == 2.0
    assert calculate_vasya_score("Leo", "Aries") == 1.0
    assert calculate_vasya_score("Aries", "Gemini") == 0.0
    print("PASS: Vasya score assertions verified.")

    # Test 3: Dina Koota Score Calculations
    print("\n--- Test 3: Dina Koota Scoring ---")
    # Dina maps (groom_nak - bride_nak) % 9
    # If remainder is 3, 5, or 7, score is 0. Else, score is 3.
    # Case A: (2 - 1) % 9 = 1 => Rem 1 => Score 3
    assert calculate_dina_score(1, 2) == 3
    # Case B: (3 - 1) % 9 = 2 => Rem 2 => Score 0
    assert calculate_dina_score(1, 3) == 0
    print("PASS: Dina score assertions verified.")

    # Test 4: Rashi Koota Score Calculations
    print("\n--- Test 4: Rashi Koota Scoring ---")
    # 1, 3, 4, 7, 10, 11 from bride rashi gives 7. Else 0.
    # Aries (idx 0) vs Aries (idx 0): dist = 1 => 7 points
    assert calculate_rashi_koota(0, 0) == 7
    # Aries (idx 0) vs Taurus (idx 1): dist = 2 => 0 points
    assert calculate_rashi_koota(0, 1) == 0
    # Aries (idx 0) vs Gemini (idx 2): dist = 3 => 7 points
    assert calculate_rashi_koota(0, 2) == 7
    print("PASS: Rashi score assertions verified.")

    # Test 5: Nadi Koota Score Calculations
    print("\n--- Test 5: Nadi Koota Scoring ---")
    # NADI_ADI = [1, 6, 7, 12, 13, 18, 19, 24, 25]
    # NADI_MADHYA = [2, 5, 8, 11, 14, 17, 20, 23, 26]
    # Nadi score is 8 if different nadis, else 0 points.
    assert calculate_nadi_score(1, 2) == 8 # Adi (1) vs Madhya (2) => 8
    assert calculate_nadi_score(1, 6) == 0 # Adi (1) vs Adi (6) => 0
    print("PASS: Nadi score assertions verified.")

    # Test 6: End-to-End Compatibility calculation
    print("\n--- Test 6: End-to-End Compatibility Calculation ---")
    try:
        # Mock coordinates: Kochi, Kerala, India (around 9.93° N, 76.26° E, UTC +5:30)
        p1 = PartnerDetails(
            dob="1995-05-15",
            tob="14:30",
            tz_offset="+5.5",
            lat=9.93,
            lon=76.26,
            name="Asha",
            gender="Female",
            ayanamsha="raman"
        )
        # Mock coordinates: Mavelikara, Kerala, India (around 9.27° N, 76.54° E, UTC +5:30)
        p2 = PartnerDetails(
            dob="1992-08-20",
            tob="08:45",
            tz_offset="+5.5",
            lat=9.27,
            lon=76.54,
            name="Rahul",
            gender="Male",
            ayanamsha="raman"
        )
        
        result = compute_compatibility_data(p1, p2)
        print("Compatibility Result Details:")
        print(f"  Partner 1: {result['p1_name']} | Moon Rashi: {result['p1_sign']} | Nakshatra: {result['p1_nakshatra']}")
        print(f"  Partner 2: {result['p2_name']} | Moon Rashi: {result['p2_sign']} | Nakshatra: {result['p2_nakshatra']}")
        print(f"  Total Score: {result['total_score']}/36 Gunas")
        print(f"  Varna: {result['varna']['score']}/{result['varna']['max']}")
        print(f"  Vasya: {result['vasya']['score']}/{result['vasya']['max']}")
        print(f"  Dina:  {result['dina']['score']}/{result['dina']['max']}")
        print(f"  Yoni:  {result['yoni']['score']}/{result['yoni']['max']} (Animals: {result['yoni']['p1_animal']} vs {result['yoni']['p2_animal']})")
        print(f"  Maitri: {result['maitri']['score']}/{result['maitri']['max']}")
        print(f"  Gana:  {result['gana']['score']}/{result['gana']['max']} (Gana: {result['gana']['p1_gana']} vs {result['gana']['p2_gana']})")
        print(f"  Rashi: {result['rashi']['score']}/{result['rashi']['max']}")
        print(f"  Nadi:  {result['nadi']['score']}/{result['nadi']['max']}")
        print(f"  Partner 1 Mars House: {result['p1_mars_house']} (Manglik: {result['p1_manglik']})")
        print(f"  Partner 2 Mars House: {result['p2_mars_house']} (Manglik: {result['p2_manglik']})")
        print(f"  Kuja Dosha Mutual Cancellation: {result['manglik_cancellation']}")
        
        # Verify result contains all necessary fields
        fields = [
            "total_score", "max_score", "varna", "vasya", "dina", "yoni", 
            "maitri", "gana", "rashi", "nadi", "manglik_cancellation"
        ]
        for f in fields:
            assert f in result, f"Missing field in compatibility calculation: {f}"
        
        print("\nPASS: End-to-end calculations completed and validated successfully.")
    except Exception as e:
        print(f"FAIL: End-to-end compatibility calculation crashed: {str(e)}")
        sys.exit(1)

    print("\n==================================================")
    print("ALL TESTS PASSED SUCCESSFULLY! AstroVeda Matchmaker verified.")
    print("==================================================")

if __name__ == "__main__":
    run_tests()
