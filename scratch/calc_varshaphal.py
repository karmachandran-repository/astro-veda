import swisseph as swe
import json
from datetime import datetime, timedelta
import math

# Target Native: Karma Chandran
# Born: May 25, 1990, 16:58:00 local time
# Place: Mavelikara, Kerala, India (Lat: 9.2505, Lon: 76.5402)
# Timezone offset: +05:30 (5.5 hours)
# Gender: Male

lat = 9.2505
lon = 76.5402
offset = 5.5
dob_local = datetime(1990, 5, 25, 16, 58, 0)
dob_utc = dob_local - timedelta(hours=offset)

swe.set_sid_mode(swe.SIDM_LAHIRI)

# Julian day of birth
jd_birth = swe.julday(dob_utc.year, dob_utc.month, dob_utc.day, dob_utc.hour + dob_utc.minute/60.0 + dob_utc.second/3600.0)
ayan_birth = swe.get_ayanamsa(jd_birth)

# Calculate birth planet positions
planets = {
    "Sun": swe.SUN, "Moon": swe.MOON, "Mars": swe.MARS, "Mercury": swe.MERCURY,
    "Jupiter": swe.JUPITER, "Venus": swe.VENUS, "Saturn": swe.SATURN, "Rahu": swe.MEAN_NODE
}

print("--- BIRTH DETAILS (Chitrapaksha Lahiri Ayanamsha: %.6f) ---" % ayan_birth)

birth_pos = {}
for p_name, p_id in planets.items():
    res = swe.calc_ut(jd_birth, p_id, swe.FLG_SIDEREAL)
    lon_val = res[0][0] % 360
    birth_pos[p_name] = lon_val

# Ketu is 180 degrees from Rahu
birth_pos["Ketu"] = (birth_pos["Rahu"] + 180.0) % 360

# Lagna (Ascendant)
cusps, ascmc = swe.houses(jd_birth, lat, lon, b'P')
lagna_lon = (ascmc[0] - swe.get_ayanamsa(jd_birth)) % 360
birth_pos["Lagna"] = lagna_lon

SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
PLANET_LORDS = {
    "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury", "Cancer": "Moon",
    "Leo": "Sun", "Virgo": "Mercury", "Libra": "Venus", "Scorpio": "Mars",
    "Sagittarius": "Jupiter", "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter"
}

def get_rasi_info(longitude):
    sign_idx = int(longitude / 30.0)
    sign_deg = longitude % 30.0
    sign_name = SIGNS[sign_idx]
    lord = PLANET_LORDS[sign_name]
    return sign_name, sign_deg, lord

NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra", 
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni", 
    "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha", 
    "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha", 
    "Purva Bhadrapada", "Uttara Bhadrapada", "Revati"
]
NAK_LORDS = ["Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury"]

def get_nak_info(longitude):
    nak_len = 360.0 / 27.0
    nak_idx = int(longitude / nak_len) % 27
    traversed = longitude % nak_len
    pada = int(traversed / (nak_len / 4.0)) + 1
    nak_name = NAKSHATRAS[nak_idx]
    nak_lord = NAK_LORDS[nak_idx % 9]
    return nak_name, pada, nak_lord

for name, lon_val in birth_pos.items():
    sign_name, sign_deg, lord = get_rasi_info(lon_val)
    nak_name, pada, nak_lord = get_nak_info(lon_val)
    print("%s | Absolute: %.4f | Rasi: %s (%.2f) | Lord: %s | Nak: %s (Pada %d) | Nak Lord: %s" % (
        name, lon_val, sign_name, sign_deg, lord, nak_name, pada, nak_lord
    ))

# ----------------- VARSHAPRAVESH SOLAR RETURN -----------------
# Varshapravesh occurs when the transit Sun reaches the exact absolute sidereal longitude of the birth Sun.
birth_sun_lon = birth_pos["Sun"]
print("\n--- Varshapravesh Calculations for birth Sun longitude: %.6f ---" % birth_sun_lon)

# We want to find the solar return for:
# Nth year = 35 completed (entering 36th year in 2025)
# N+1th year = 36 completed (entering 37th year in 2026)

def find_solar_return(target_year, birth_sun):
    # Search around target_year May 20-30
    start_dt = datetime(target_year, 5, 20, 0, 0, 0)
    end_dt = datetime(target_year, 5, 30, 23, 59, 59)
    start_jd = swe.julday(start_dt.year, start_dt.month, start_dt.day, start_dt.hour)
    end_jd = swe.julday(end_dt.year, end_dt.month, end_dt.day, end_dt.hour)
    
    # Binary search to find exact JD where transit Sun == birth_sun
    low = start_jd
    high = end_jd
    for _ in range(35):
        mid = (low + high) / 2.0
        res = swe.calc_ut(mid, swe.SUN, swe.FLG_SIDEREAL)
        sun_lon = res[0][0] % 360
        # Handle wrap-around if necessary (not needed for May Sun)
        diff = sun_lon - birth_sun
        if diff > 180: diff -= 360
        if diff < -180: diff += 360
        if diff < 0:
            low = mid
        else:
            high = mid
            
    return (low + high) / 2.0

for age in [35, 36]:
    ret_year = 1990 + age
    jd_ret = find_solar_return(ret_year, birth_sun_lon)
    dt_utc = datetime(2000, 1, 1, 12, 0) + timedelta(days=(jd_ret - 2451545.0))
    dt_local = dt_utc + timedelta(hours=offset)
    
    # Muntha calculations
    # Muntha is in Lagna at birth, moves 1 house per year.
    # Muntha sign at birth = Lagna sign = Libra (or whichever was calculated).
    birth_lagna_sign_idx = int(birth_pos["Lagna"] / 30.0)
    muntha_sign_idx = (birth_lagna_sign_idx + age) % 12
    muntha_sign = SIGNS[muntha_sign_idx]
    
    # Varsha Lagna
    cusps, ascmc = swe.houses(jd_ret, lat, lon, b'P')
    varsha_lagna_lon = (ascmc[0] - swe.get_ayanamsa(jd_ret)) % 360
    varsha_lagna_sign = SIGNS[int(varsha_lagna_lon / 30.0)]
    
    print("Age %d Return (%d): Local Time: %s | Varsha Lagna: %s (%.2f°) | Muntha Sign: %s" % (
        age, ret_year, dt_local.strftime("%Y-%m-%d %H:%M:%S"), varsha_lagna_sign, varsha_lagna_lon % 30, muntha_sign
    ))
    
    # Planetary positions at Varshapravesh
    print("Planetary Positions at age %d solar return:" % age)
    ret_pos = {}
    for p_name, p_id in planets.items():
        res = swe.calc_ut(jd_ret, p_id, swe.FLG_SIDEREAL)
        lon_val = res[0][0] % 360
        ret_pos[p_name] = lon_val
    ret_pos["Ketu"] = (ret_pos["Rahu"] + 180.0) % 360
    ret_pos["Lagna"] = varsha_lagna_lon
    
    for p_name, lon_val in ret_pos.items():
        s_name, s_deg, _ = get_rasi_info(lon_val)
        p_house = (int(lon_val / 30.0) - int(varsha_lagna_lon / 30.0)) % 12 + 1
        print("  %s | Sign: %s (%.2f°) | House: %d" % (p_name, s_name, s_deg, p_house))
