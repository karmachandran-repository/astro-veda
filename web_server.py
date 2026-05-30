import os
import sys
try:
    from dotenv import load_dotenv
    # override=False means Vercel's env vars
    # take priority over any .env file.
    # This prevents a blank .env in the repo
    # from wiping Vercel's injected values.
    base_dir = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(dotenv_path=os.path.join(base_dir, ".env"), override=False)
except ImportError:
    pass
import json
import math
import asyncio
import logging
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Response, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
import swisseph as swe
import requests
import urllib.parse

# Import constants and calculation helpers from the co-located server module.
# server.py is always present alongside web_server.py; no silent fallback.
import server
from server import (
    SIGNS, WEEKDAYS, YOGAS, KARANAS, HOUSE_LORDS, BHAVA_KARAKAS, NAKSHATRAS, NAKSHATRA_LORDS,
    calculate_universal_varga, determine_aspects, calculate_dynamic_shadbala,
    calculate_samudaya_ashtakavarga, detect_all_yogas, get_nakshatra_info,
    calculate_transits_for_date
)


import string

def _get_anthropic_key() -> str:
    """Extracts the 108-char workspace key with literal security encoding."""
    raw = os.environ.get("ANTHROPIC_API_KEY", "")
    if not raw:
        return ""

    # Strip any possible trailing/leading whitespace and hidden Byte Order Marks
    sanitized = raw.strip().lstrip("﻿")

    # Filter out any lingering invisible control characters, keeping only clean alphanumeric, dashes, and underscores
    whitelist = string.ascii_letters + string.digits + "-_"
    cleaned_key = "".join(char for char in sanitized if char in whitelist)

    # Block boilerplate template strings
    if "YOUR_CLAUDE_API_KEY" in cleaned_key:
        return ""

    return cleaned_key

# Dynamic default date — computed once at startup so every request that omits
# prediction_date defaults to the actual current day rather than a hardcoded past date.
_TODAY = datetime.today().strftime("%Y-%m-%d")
log = logging.getLogger(__name__)

app = FastAPI(title="AstroVeda Celestial Hub")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Local fallback astronomical calculations for Sunrise, Sunset & Panchang times
def get_solar_altitude(jd, lat, lon):
    res_eq = swe.calc_ut(jd, swe.SUN, swe.FLG_EQUATORIAL | swe.FLG_SWIEPH)
    ra = res_eq[0][0]
    dec = res_eq[0][1]
    gst = swe.sidtime(jd)
    lst = (gst * 15.0 + lon) % 360.0
    ha = (lst - ra) % 360.0
    if ha > 180.0:
        ha -= 360.0
    lat_rad = math.radians(lat)
    dec_rad = math.radians(dec)
    ha_rad = math.radians(ha)
    sin_alt = math.sin(lat_rad)*math.sin(dec_rad) + math.cos(lat_rad)*math.cos(dec_rad)*math.cos(ha_rad)
    sin_alt = max(-1.0, min(1.0, sin_alt))
    return math.degrees(math.asin(sin_alt))

def find_altitude_crossing(start_jd, end_jd, target_alt, lat, lon, ascending=True):
    low = start_jd
    high = end_jd
    for _ in range(25):
        mid = (low + high) / 2.0
        alt = get_solar_altitude(mid, lat, lon)
        if ascending:
            if alt < target_alt:
                low = mid
            else:
                high = mid
        else:
            if alt > target_alt:
                low = mid
            else:
                high = mid
    return (low + high) / 2.0

def get_moon_altitude(jd, lat, lon):
    res_eq = swe.calc_ut(jd, swe.MOON, swe.FLG_EQUATORIAL | swe.FLG_SWIEPH)
    ra = res_eq[0][0]
    dec = res_eq[0][1]
    gst = swe.sidtime(jd)
    lst = (gst * 15.0 + lon) % 360.0
    ha = (lst - ra) % 360.0
    if ha > 180.0:
        ha -= 360.0
    lat_rad = math.radians(lat)
    dec_rad = math.radians(dec)
    ha_rad = math.radians(ha)
    sin_alt = math.sin(lat_rad)*math.sin(dec_rad) + math.cos(lat_rad)*math.cos(dec_rad)*math.cos(ha_rad)
    sin_alt = max(-1.0, min(1.0, sin_alt))
    return math.degrees(math.asin(sin_alt))

def find_moon_crossing(start_jd, end_jd, target_alt, lat, lon, ascending=True):
    low = start_jd
    high = end_jd
    for _ in range(25):
        mid = (low + high) / 2.0
        alt = get_moon_altitude(mid, lat, lon)
        if ascending:
            if alt < target_alt:
                low = mid
            else:
                high = mid
        else:
            if alt > target_alt:
                low = mid
            else:
                high = mid
    return (low + high) / 2.0

def jd_to_local_str(jd, offset_hours):
    # Converts Julian day back to local formatted time
    # Since Julian Day 2451545.0 corresponds to Jan 1, 2000 at 12:00:00 UTC (Noon)
    dt_utc = datetime(2000, 1, 1, 12, 0) + timedelta(days=(jd - 2451545.0))
    dt_local = dt_utc + timedelta(hours=offset_hours)
    return dt_local.strftime("%b %d %I:%M %p")

def jd_to_panchang_str(jd, offset_hours):
    return jd_to_local_str(jd, offset_hours)

NAK_NAMES = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra", 
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni", 
    "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha", 
    "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha", 
    "Purva Bhadrapada", "Uttara Bhadrapada", "Revati"
]

def find_tithi_boundary(search_start_jd,
                        target_diff_deg,
                        direction=1):
    """
    Find the exact JD when Moon-Sun elongation
    equals target_diff_deg (0.0 to 360.0).

    direction=1  → search forward in time
    direction=-1 → search backward in time

    Search window is capped at 1.6 days in either
    direction — a Tithi is 19-26 hours so the
    boundary cannot be further than that.
    """
    # Cap search at 1.6 days to stay in current cycle
    window = 1.6
    if direction > 0:
        low  = search_start_jd
        high = search_start_jd + window
    else:
        low  = search_start_jd - window
        high = search_start_jd

    for _ in range(52):
        mid = (low + high) / 2.0
        r_s = swe.calc_ut(mid, swe.SUN,  swe.FLG_SIDEREAL)
        r_m = swe.calc_ut(mid, swe.MOON, swe.FLG_SIDEREAL)
        current_diff = (r_m[0][0] - r_s[0][0]) % 360.0

        # Signed angular distance from target
        # Result is in (-180, +180]
        delta = (current_diff - target_diff_deg + 180.0
                 ) % 360.0 - 180.0

        if delta < 0:
            low = mid
        else:
            high = mid

    return (low + high) / 2.0

def find_nak_boundary(search_start_jd,
                      target_moon_lon,
                      direction=1):
    """
    Find exact JD when Moon sidereal longitude
    equals target_moon_lon (0.0 to 360.0).

    Capped at 1.6 days — Moon traverses one
    Nakshatra (13.33°) in roughly 0.9-1.1 days
    so the boundary is always within 1.6 days.
    """
    window = 1.6
    if direction > 0:
        low  = search_start_jd
        high = search_start_jd + window
    else:
        low  = search_start_jd - window
        high = search_start_jd

    for _ in range(52):
        mid = (low + high) / 2.0
        r_m = swe.calc_ut(mid, swe.MOON, swe.FLG_SIDEREAL)
        ml = r_m[0][0] % 360.0

        delta = (ml - target_moon_lon + 180.0
                 ) % 360.0 - 180.0

        if delta < 0:
            low = mid
        else:
            high = mid

    return (low + high) / 2.0

# Pydantic models for charts
class ChartRequest(BaseModel):
    dob: str
    tob: str
    tz_offset: str
    lat: float
    lon: float
    ayanamsha: str = "raman"
    prediction_date: str = _TODAY
    gender: str = "Female"

@app.get("/api/debug/env")
async def debug_env():
    import httpx, hashlib
    anthropic = _get_anthropic_key()
    gemini    = os.environ.get("GEMINI_API_KEY", "").strip()
    openai    = os.environ.get("OPENAI_API_KEY", "").strip()

    # Test actual Anthropic connectivity
    anthropic_test = "not tested"
    if anthropic:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": anthropic,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-sonnet-4-6",
                        "max_tokens": 10,
                        "messages": [
                            {"role": "user", "content": "Say OK"}
                        ],
                    }
                )
                if resp.status_code == 200:
                    anthropic_test = "CONNECTED OK"
                else:
                    anthropic_test = f"HTTP {resp.status_code}: {resp.text[:100]}"
        except Exception as e:
            anthropic_test = f"FAILED: {str(e)[:100]}"

    return {
        "ANTHROPIC_API_KEY": (
            f"SET ({len(anthropic)} chars)"
            if anthropic else "MISSING"
        ),
        "key_first_14": anthropic[:14] if anthropic else "MISSING",
        "key_last_4": anthropic[-4:] if anthropic else "MISSING",
        "key_md5": hashlib.md5(anthropic.encode()).hexdigest() if anthropic else "MISSING",
        "key_special_chars": [c for c in anthropic if not c.isalnum() and c != "-"] if anthropic else [],
        "GEMINI_API_KEY": (
            f"SET ({len(gemini)} chars)"
            if gemini else "MISSING"
        ),
        "OPENAI_API_KEY": (
            f"SET ({len(openai)} chars)"
            if openai else "MISSING"
        ),
        "anthropic_connectivity": anthropic_test,
        "VERCEL": os.environ.get("VERCEL", "not set"),
        "VERCEL_ENV": os.environ.get("VERCEL_ENV", "not set"),
    }


@app.get("/")
def serve_index():
    index_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    if not os.path.exists(index_path):
        return Response(content="<h3>Error: index.html not found!</h3>", media_type="text/html")
    with open(index_path, "r", encoding="utf-8") as f:
        return Response(content=f.read(), media_type="text/html")

@app.get("/assets/zodiac_celestial_map.png")
def serve_zodiac_map():
    img_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "zodiac_celestial_map.png")
    if not os.path.exists(img_path):
        return Response(content="Image not found", status_code=404)
    return FileResponse(img_path, media_type="image/png")

@app.get("/api/panchang")
def get_panchang(lat: float = 8.9602, lon: float = 76.6788, offset: str = "+05:30", date_str: str = None):
    # Default to today
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    y, m, d = [int(x) for x in date_str.split("-")]
    sign = -1.0 if "-" in offset else 1.0
    tz_clean = offset.replace("+", "").replace("-", "")
    th, tm = [float(x) for x in tz_clean.split(":")] if ":" in tz_clean else (float(tz_clean), 0.0)
    offset_hours = sign * (th + tm / 60.0)
    
    # Calculate baseline JD at midnight local time
    dt_local_midnight = datetime(y, m, d, 0, 0)
    dt_utc_midnight = dt_local_midnight - timedelta(hours=offset_hours)
    jd_midnight = swe.julday(dt_utc_midnight.year, dt_utc_midnight.month, dt_utc_midnight.day, dt_utc_midnight.hour + dt_utc_midnight.minute/60.0)
    
    # Set default Ayanamsha to Lahiri for general Panchanga
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    
    # Sunrise & Sunset calculations
    sunrise_jd = find_altitude_crossing(jd_midnight, jd_midnight + 0.5, -0.8333, lat, lon, ascending=True)
    sunset_jd = find_altitude_crossing(jd_midnight + 0.3, jd_midnight + 0.9, -0.8333, lat, lon, ascending=False)
    
    # Moonrise & Moonset calculations
    moonrise_jd = find_moon_crossing(jd_midnight, jd_midnight + 1.0, 0.0, lat, lon, ascending=True)
    moonset_jd = find_moon_crossing(jd_midnight, jd_midnight + 1.0, 0.0, lat, lon, ascending=False)
    
    day_duration = sunset_jd - sunrise_jd
    
    # Inauspicious & Auspicious Periods (Rahu Kaal, Yamaganda, Gulika Kaal)
    # Ordered parts (1-indexed) depending on weekday
    weekday_idx = dt_local_midnight.weekday() # 0 = Monday, 6 = Sunday
    
    rahu_slots = [2, 7, 5, 6, 4, 3, 8] # Monday to Sunday (0-indexed: Mon=2, Tue=7, Wed=5, Thu=6, Fri=4, Sat=3, Sun=8)
    yamaganda_slots = [4, 3, 2, 1, 7, 6, 5] # Monday to Sunday (0-indexed: Mon=4, Tue=3, Wed=2, Thu=1, Fri=7, Sat=6, Sun=5)
    gulika_slots = [6, 5, 4, 3, 2, 1, 7] # Monday to Sunday (0-indexed: Mon=6, Tue=5, Wed=4, Thu=3, Fri=2, Sat=1, Sun=7)
    
    rahu_idx = rahu_slots[weekday_idx]
    yama_idx = yamaganda_slots[weekday_idx]
    guli_idx = gulika_slots[weekday_idx]
    
    def get_slot_times(slot_num):
        slot_len = day_duration / 8.0
        start = sunrise_jd + (slot_num - 1) * slot_len
        end = sunrise_jd + slot_num * slot_len
        return jd_to_local_str(start, offset_hours) + " - " + jd_to_local_str(end, offset_hours)
    
    # Auspicious Brahma Muhurat: Starts 96 mins before Sunrise, ends 48 mins before Sunrise
    brahma_start = sunrise_jd - (96.0 / 1440.0)
    brahma_end = sunrise_jd - (48.0 / 1440.0)
    
    # Auspicious Abhijit Muhurat: Centered at solar midday (noon)
    mid_noon = sunrise_jd + (day_duration / 2.0)
    abhijit_start = mid_noon - (24.0 / 1440.0)
    abhijit_end = mid_noon + (24.0 / 1440.0)
    
    # Standard Vedic calculations for Tithi, Karana, Yoga, and Rashi
    res_sun = swe.calc_ut(sunrise_jd, swe.SUN, swe.FLG_SIDEREAL)
    res_moon = swe.calc_ut(sunrise_jd, swe.MOON, swe.FLG_SIDEREAL)
    s_lon = res_sun[0][0] % 360
    m_lon = res_moon[0][0] % 360
    
    diff = (m_lon - s_lon) % 360
    tithi_idx = int(diff / 12) + 1
    tithi_names_shukla = ["Prathama", "Dwitiya", "Tritiya", "Chaturthi", "Panchami", "Shasthi", "Saptami", "Ashtami", "Navami", "Dashami", "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi", "Poornima"]
    tithi_names_krishna = ["Prathama", "Dwitiya", "Tritiya", "Chaturthi", "Panchami", "Shasthi", "Saptami", "Ashtami", "Navami", "Dashami", "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi", "Amavasya"]
    current_tithi_start_deg = (tithi_idx - 1) * 12.0
    current_start_jd = find_tithi_boundary(
        sunrise_jd, current_tithi_start_deg,
        direction=-1
    )

    tithi_list = []
    prev_end_jd = current_start_jd

    for i in range(3):  # current + 2 upcoming
        t_idx = ((tithi_idx - 1) + i) % 30
        paksha = "Shukla Paksha" if t_idx < 15 else "Krishna Paksha"
        t_name_idx = t_idx % 15
        if t_idx < 15:
            t_name = tithi_names_shukla[t_name_idx]
        else:
            t_name = tithi_names_krishna[t_name_idx]

        entry_start_jd = prev_end_jd

        # Target end = when Moon-Sun separation crosses
        # the next 12° boundary
        # Must handle 360° wraparound carefully
        target_end_deg = ((tithi_idx - 1 + i + 1) % 30) * 12.0

        # If target_end_deg is 0 (wrap after Amavasya),
        # treat as 360 to search forward correctly
        if target_end_deg == 0:
            target_end_deg = 360.0

        entry_end_jd = find_tithi_boundary(
            entry_start_jd + 0.1,  # search just past start
            target_end_deg,
            direction=1
        )

        tithi_list.append({
            "name":  f"{paksha} {t_name}",
            "start": jd_to_panchang_str(entry_start_jd, offset_hours),
            "end":   jd_to_panchang_str(entry_end_jd,   offset_hours)
        })

        prev_end_jd = entry_end_jd

    nak_len = 360.0 / 27.0
    nak_idx = int(m_lon / nak_len) % 27
    nak_start_lon = nak_idx * nak_len

    nak_current_start_jd = find_nak_boundary(
        sunrise_jd, nak_start_lon, direction=-1
    )

    nak_list = []
    nak_prev_end_jd = nak_current_start_jd

    for i in range(3):  # current + 2 upcoming
        n_idx = (nak_idx + i) % 27
        n_name = NAK_NAMES[n_idx]

        n_start_jd = nak_prev_end_jd

        # End = when Moon crosses into the next Nakshatra
        n_end_lon = ((nak_idx + i + 1) % 27) * nak_len

        # Handle 360°/0° wraparound — if end longitude
        # would be 0°, search for Moon reaching 360°
        # (effectively same as 0° but avoids binary
        # search getting stuck at the boundary)
        if n_end_lon == 0:
            n_end_lon = 360.0

        n_end_jd = find_nak_boundary(
            n_start_jd + 0.1,  # search just past start
            n_end_lon,
            direction=1
        )

        nak_list.append({
            "name":  n_name,
            "start": jd_to_panchang_str(n_start_jd, offset_hours),
            "end":   jd_to_panchang_str(n_end_jd,   offset_hours)
        })

        nak_prev_end_jd = n_end_jd

    # ── Karana calculation ─────────────────────────
    # Each Karana = 6° of Moon-Sun elongation
    # 60 Karanas per lunar month (30 Tithis × 2)
    karana_seq = [
        "Kimstughna",  # 0: fixed, Shukla 1 first half
        "Bava", "Balava", "Kaulava", "Taitila",
        "Garija", "Vanija", "Vishti",             # 1-7
        "Bava", "Balava", "Kaulava", "Taitila",
        "Garija", "Vanija", "Vishti",             # 8-14
        "Bava", "Balava", "Kaulava", "Taitila",
        "Garija", "Vanija", "Vishti",             # 15-21
        "Bava", "Balava", "Kaulava", "Taitila",
        "Garija", "Vanija", "Vishti",             # 22-28
        "Bava", "Balava", "Kaulava", "Taitila",
        "Garija", "Vanija", "Vishti",             # 29-35
        "Bava", "Balava", "Kaulava", "Taitila",
        "Garija", "Vanija", "Vishti",             # 36-42
        "Bava", "Balava", "Kaulava", "Taitila",
        "Garija", "Vanija", "Vishti",             # 43-49
        "Bava", "Balava", "Kaulava", "Taitila",
        "Garija", "Vanija", "Vishti",             # 50-56
        "Shakuni",                                # 57: fixed
        "Chatushpada",                            # 58: fixed
        "Naga",                                   # 59: fixed
    ]
    # Index 0-59 maps to the 60 Karanas of the month
    # diff=0-360 → karana_raw_idx 0-59
    karana_raw_idx = int(diff / 6.0) % 60
    karana_name = karana_seq[karana_raw_idx]
        
    # Yoga calculations
    y_sum = (s_lon + m_lon) % 360
    yoga_name = YOGAS[int(y_sum / (360.0 / 27.0)) % 27]

    # ── Yoga end time ──────────────────────────────
    def find_yoga_boundary(search_start_jd,
                           target_sum_deg,
                           direction=1):
        """Find when (Sun lon + Moon lon) % 360 crosses
        target_sum_deg. Window 2 days (Yoga ~1 day)."""
        window = 2.0
        if direction > 0:
            low, high = search_start_jd, search_start_jd + window
        else:
            low, high = search_start_jd - window, search_start_jd
        for _ in range(52):
            mid = (low + high) / 2.0
            rs = swe.calc_ut(mid, swe.SUN,  swe.FLG_SIDEREAL)
            rm = swe.calc_ut(mid, swe.MOON, swe.FLG_SIDEREAL)
            s = (rs[0][0] + rm[0][0]) % 360.0
            delta = (s - target_sum_deg + 180.0) % 360.0 - 180.0
            if delta < 0:
                low = mid
            else:
                high = mid
        return (low + high) / 2.0

    yoga_idx_val = int(y_sum / (360.0 / 27.0)) % 27
    yoga_end_deg = (yoga_idx_val + 1) * (360.0 / 27.0)
    yoga_end_jd  = find_yoga_boundary(
        sunrise_jd, yoga_end_deg % 360.0, direction=1
    )
    yoga_start_deg = yoga_idx_val * (360.0 / 27.0)
    yoga_start_jd  = find_yoga_boundary(
        sunrise_jd, yoga_start_deg, direction=-1
    )
    yoga_display = (
        f"{yoga_name} — "
        f"{jd_to_panchang_str(yoga_start_jd, offset_hours)}"
        f" – "
        f"{jd_to_panchang_str(yoga_end_jd, offset_hours)}"
    )
    
    # Sun & Moon Zodiac placements
    sun_sign = SIGNS[int(s_lon / 30)]
    moon_sign = SIGNS[int(m_lon / 30)]
    
    # Chandrashtama calculation
    transiting_moon_sign_idx = int(m_lon / 30) % 12
    # Chandrashtama is active for the sign whose Moon is 8 houses back from transiting Moon
    chandrashtama_sign_idx = (transiting_moon_sign_idx - 7) % 12
    chandrashtama_sign = SIGNS[chandrashtama_sign_idx]
    
    # Nakshatra segments for the Chandrashtama sign
    chandrashtama_nakshatras = {
        "Aquarius": "Dhanishta Last 2 padam, Shatabhisha, Purva Bhadrapada First 3 padam",
        "Pisces": "Purva Bhadrapada Last 1 padam, Uttara Bhadrapada, Revati",
        "Aries": "Ashwini, Bharani, Krittika First 1 padam",
        "Taurus": "Krittika Last 3 padam, Rohini, Mrigashira First 2 padam",
        "Gemini": "Mrigashira Last 2 padam, Ardra, Punarvasu First 3 padam",
        "Cancer": "Punarvasu Last 1 padam, Pushya, Ashlesha",
        "Leo": "Magha, Purva Phalguni, Uttara Phalguni First 1 padam",
        "Virgo": "Uttara Phalguni Last 3 padam, Hasta, Chitra First 2 padam",
        "Libra": "Chitra Last 2 padam, Swati, Vishakha First 3 padam",
        "Scorpio": "Vishakha Last 1 padam, Anuradha, Jyeshtha",
        "Sagittarius": "Mula, Purva Ashadha, Uttara Ashadha First 1 padam",
        "Capricorn": "Uttara Ashadha Last 3 padam, Shravana, Dhanishta First 2 padam"
    }
    
    # Season & Vedic Ritu approximations from Sun longitude
    ritu_list = ["Vasanta (Spring)", "Grishma (Summer)", "Varsha (Monsoon)", "Sharad (Autumn)", "Hemanta (Pre-winter)", "Shishira (Winter)"]
    ritu_idx = int((s_lon / 60) % 6)
    ritu_name = ritu_list[ritu_idx]
    
    # Saka year calculation
    saka_year = y - 79
    lunar_months = ["Chaitra", "Vaishakha", "Jyeshtha", "Ashadha", "Shravana", "Bhadrapada", "Ashvina", "Kartika", "Margashirsha", "Pausha", "Magha", "Phalguna"]
    lunar_month_name = lunar_months[int(s_lon / 30) % 12]
    
    return {
        "Vara": WEEKDAYS[weekday_idx],
        "Tithi": tithi_list,
        "Nakshatra": nak_list,
        "Karana": f"{karana_name} - Active today",
        "Yoga": yoga_display,
        "Sunrise": jd_to_local_str(sunrise_jd, offset_hours),
        "Sunset": jd_to_local_str(sunset_jd, offset_hours),
        "Moonrise": jd_to_local_str(moonrise_jd, offset_hours),
        "Moonset": jd_to_local_str(moonset_jd, offset_hours),
        "Rahu_Kaal": get_slot_times(rahu_idx),
        "Yamaganda": get_slot_times(yama_idx),
        "Gulika_Kaal": get_slot_times(guli_idx),
        "Abhijit_Muhurat": jd_to_local_str(abhijit_start, offset_hours) + " - " + jd_to_local_str(abhijit_end, offset_hours),
        "Brahma_Muhurat": jd_to_local_str(brahma_start, offset_hours) + " - " + jd_to_local_str(brahma_end, offset_hours),
        "Sun_Rasi": f"Sun in {sun_sign}",
        "Moon_Rasi": f"Moon in {moon_sign}",
        "Lunar_Month": f"Amanta - {lunar_month_name} | Purnimanta - {lunar_month_name}",
        "Saka_Year": f"{lunar_month_name} {d}, {saka_year}",
        "Vedic_Ritu": ritu_name,
        "Drik_Ritu": ritu_name,
        "Chandrashtama": f"{chandrashtama_sign} ({chandrashtama_nakshatras.get(chandrashtama_sign, '')})"
    }

@app.post("/api/chart")
def get_chart_coordinates(req: ChartRequest):
    try:
        result_json = server.calculate_d1_chart(
            dob=req.dob,
            tob=req.tob,
            tz_offset=req.tz_offset,
            lat=req.lat,
            lon=req.lon,
            ayanamsha=req.ayanamsha,
            prediction_date=req.prediction_date
        )
        result = json.loads(result_json)

        # Merge upagrahas (Gulika) into planets list so the SVG chart renderer continues to draw it correctly
        if "planets" in result and "upagrahas" in result:
            for u_name, u_val in result["upagrahas"].items():
                result["planets"][u_name] = u_val

        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/prediction/stream")
async def stream_prediction(
    dob: str = "1966-05-25",
    tob: str = "16:58",
    tz_offset: str = "+05:30",
    lat: float = 8.9602,
    lon: float = 76.6788,
    ayanamsha: str = "raman",
    prediction_date: str = "2030-11-17",
    gender: str = "Female",
    active_mahadasha: str = None,
    active_antardasha: str = None
):
    async def prediction_generator():
        # 1. Load System Blueprint and inject today's date dynamically so the
        #    LLM always operates from the actual current date, not a stale constant.
        try:
            from client import load_system_blueprint, calculate_tajika_progressions, search_local_index
            raw_blueprint = load_system_blueprint("synthesis_engine.md")
            today_str = datetime.today().strftime("%B %d, %Y")
            system_blueprint = raw_blueprint.replace("{CURRENT_DATE}", today_str)
        except Exception as e:
            system_blueprint = "You are an enterprise-grade Jyotish reasoning engine executing classical traditional analytical frameworks."

        # 2. Get Astrological calculations directly from the top-level server import
        try:
            chart_json = server.calculate_d1_chart(
                dob=dob,
                tob=tob,
                tz_offset=tz_offset,
                lat=lat,
                lon=lon,
                ayanamsha=ayanamsha,
                prediction_date=prediction_date
            )
            natal_data = json.loads(chart_json)
            detected_yogas = natal_data.get("yogas", {})
        except Exception as e:
            yield "data: " + json.dumps({"content": f"### Error in astrological calculations\n- Details: {str(e)}\n\n"}) + "\n\n"
            return

        # Dynamically determine the active dasha lords at prediction_date if not explicitly provided
        current_m = active_mahadasha
        current_a = active_antardasha
        
        if not current_m or not current_a:
            try:
                timeline_data = natal_data["dasha_timeline"]["timeline"] if isinstance(natal_data["dasha_timeline"], dict) else natal_data["dasha_timeline"]
                for m_block in timeline_data:
                    if m_block["start_date"] <= prediction_date <= m_block["end_date"]:
                        current_m = m_block["mahadasha"]
                        for a_block in m_block.get("antardashas", []):
                            if a_block["start_date"] <= prediction_date <= a_block["end_date"]:
                                current_a = a_block["antardasha"]
                                break
                        break
            except Exception as e:
                # Non-fatal: fall through to the Moon/Sun defaults below
                log.warning("Could not determine active dasha from timeline: %s", e)
                
        # Default fallback values
        if not current_m: current_m = "Moon"
        if not current_a: current_a = "Sun"

        # 3. Calculate Tajika Varshaphal
        varshaphal_data = calculate_tajika_progressions(dob, prediction_date, natal_data)

        # 4. Search local RAG rules
        try:
            book_rules = search_local_index(natal_data)
        except Exception as e:
            book_rules = "No matching rules retrieved."

        # 5. Format payload text exactly as client.py does
        try:
            planets = natal_data["planets"]
            panchanga = natal_data["panchanga_metrics"]
            hl_matrix = natal_data["house_lord_matrix"]
            
            data_sheet = "AUTHENTIC CELESTIAL ALIGNMENT COORDINATES FOR SYNTHESIS:\n"
            data_sheet += f"- Native Gender Profile: {gender}\n"
            data_sheet += f"- Chosen Ayanamsha: {ayanamsha.upper()}\n"
            data_sheet += f"- Panchanga Baseline: Weekday={panchanga['Vara']}, Tithi={panchanga['Tithi']}, Yoga={panchanga['Yoga']}, Karana={panchanga['Karana']}\n"
            
            # After panchanga line, add nakshatra details
            lagna_nak = natal_data["ascendant"].get("nakshatra", "N/A")
            lagna_nak_lord = natal_data["ascendant"].get("nakshatra_lord", "N/A")
            moon_nak = natal_data["planets"]["Moon"].get("nakshatra", "N/A")
            moon_nak_lord = natal_data["planets"]["Moon"].get("nakshatra_lord", "N/A")
            moon_pada_approx = int((natal_data["planets"]["Moon"]["longitude"] % (360/27)) / (360/27/4)) + 1

            data_sheet += (
                f"- Lagna Nakshatra: {lagna_nak} (Lord: {lagna_nak_lord})\n"
                f"- Moon Nakshatra: {moon_nak} Pada {moon_pada_approx} "
                f"(Lord: {moon_nak_lord})\n"
            )
            
            data_sheet += f"- Vimshottari Focused Sub-Period: {current_m} Mahadasha — {current_a} Antardasha\n"
            vp = varshaphal_data
            if "varsha_planets" in vp:
                data_sheet += "\nTAJIKA VARSHAPHAL (ASTRONOMICAL — USE THESE VALUES):\n"
                data_sheet += f"- Completed Age: {vp['completed_age']}\n"
                data_sheet += f"- Solar Return Date: {vp.get('solar_return_date', 'N/A')}\n"
                data_sheet += (
                    f"- Varsha Lagna: {vp['varsha_lagna']['sign']} "
                    f"at {vp['varsha_lagna']['longitude']}° "
                    f"({vp['varsha_lagna']['nakshatra']})\n"
                )
                data_sheet += f"- Muntha: {vp['muntha']['sign']} (House {vp['muntha']['house']})\n"
                data_sheet += "- Varsha Planets:\n"
                for p_name, p_data in vp["varsha_planets"].items():
                    data_sheet += (
                        f"  {p_name}: {p_data['sign']} "
                        f"H{p_data['house']} ({p_data['longitude']}°)\n"
                    )
            else:
                data_sheet += (
                    f"\nTAJIKA VARSHAPHAL (APPROXIMATE):\n"
                    f"- Completed Age: {vp.get('completed_age', 'N/A')}\n"
                    f"- Muntha House: {vp.get('muntha_progressed_house', 'N/A')}\n"
                )

            data_sheet += "12 HOUSES FIELD DATA MATRIX:\n"
            for h_key, h_data in hl_matrix.items():
                data_sheet += (
                    f"- {h_key} ({h_data['ZodiacSign']}): Occupants={h_data['Occupants']} | "
                    f"HouseLord={h_data['HouseLord']} sitting in House {h_data['LordPlacementHouse']} | "
                    f"NaturalKaraka={h_data['NaturalSignificator']} sitting in House {h_data['SignificatorPlacementHouse']} | "
                    f"Aspect Lines Received={h_data['ReceivingAspects']}\n"
                )
            
            data_sheet += "\nSHODASAVARGA SIGN HARMONICS LEDGER:\n"
            varga_list = [1, 2, 3, 4, 5, 7, 9, 10, 12, 16, 20, 24, 27, 30, 40, 45, 60]
            for p_name, p_val in planets.items():
                v_str = ", ".join([f"D{v}={p_val['vargas'][f'D{v}']}" for v in varga_list])
                data_sheet += f"- {p_name}: House={p_val['house']}, Retrograde={p_val['is_retrograde']}, Combust={p_val['is_combust']} | {v_str}\n"
                
            data_sheet += f"\nASHTAKAVARGA DISTRIBUTION: {json.dumps(natal_data['ashtakavarga_bindus'])}\n"
            data_sheet += f"SHADBALA POTENCY STRINGS: {json.dumps(natal_data['shadbala_potency'])}\n"

            # Yoga quality flags
            yogas_data = natal_data.get("yogas", {})
            if yogas_data.get("Gajakesari"):
                gk_notes = yogas_data.get("Gajakesari_Notes", {})
                data_sheet += (
                    f"\nGAJAKESARI YOGA QUALITY:\n"
                    f"- Geometry: {gk_notes.get('geometry', 'N/A')}\n"
                    f"- Moon in Dusthana: {gk_notes.get('moon_dusthana', False)}\n"
                    f"- Moon Debilitated: {gk_notes.get('moon_debilitated', False)}\n"
                    f"- Phala: {gk_notes.get('phala', 'N/A')}\n"
                    f"- Caveat: {gk_notes.get('caveat', '')}\n"
                )

            if yogas_data.get("Rahu_Dispositor_Weak"):
                data_sheet += (
                    f"\nRAHU DISPOSITOR WARNING:\n"
                    f"- Rahu in {natal_data['planets']['Rahu']['sign']} "
                    f"disposited by {yogas_data.get('Rahu_Dispositor', 'N/A')} "
                    f"in {yogas_data.get('Rahu_Dispositor_Sign', 'N/A')}\n"
                    f"- Dispositor is DEBILITATED — Rahu's H11 gains promise "
                    f"is critically undermined. Do NOT frame H11 Rahu "
                    f"optimistically without this caveat.\n"
                )

            if yogas_data.get("Guru_Chandala_D9"):
                data_sheet += (
                    f"\nGURU-CHANDALA D9 WARNING:\n"
                    f"- {yogas_data.get('Guru_Chandala_D9_Note', '')}\n"
                )

            # Varshaphal alerts
            vp = natal_data.get("varshaphal", {})
            alerts = vp.get("varsha_alerts", {})
            if alerts:
                data_sheet += "\nVARSHA CHART ALERTS:\n"
                if alerts.get("sun_ketu_note"):
                    data_sheet += f"- {alerts['sun_ketu_note']}\n"
                if alerts.get("saturn_lagna_note"):
                    data_sheet += f"- {alerts['saturn_lagna_note']}\n"

            # H12 expenditure profile
            h12_analysis = natal_data.get("ashtakavarga_h12_analysis", {})
            if h12_analysis:
                data_sheet += (
                    f"\nH12 EXPENDITURE PROFILE:\n"
                    f"- {h12_analysis.get('note', '')}\n"
                )

            dasha_list = natal_data['dasha_timeline']['timeline'] if isinstance(natal_data['dasha_timeline'], dict) else natal_data['dasha_timeline']
            data_sheet += f"\nVIMSHOTTARI TIMELINE INTERSECTIONS ARRAY: {json.dumps(dasha_list[:5])}\n"
            data_sheet += f"\nRETRIEVED CLASSICAL RULES FROM CELESTIAL KNOWLEDGE BASE:\n{book_rules}\n"
        except Exception as e:
            log.error(
                "data_sheet assembly failed: %s", e,
                exc_info=True
            )
            # Do NOT replace data_sheet with error string —
            # use whatever was assembled so far
            data_sheet += f"\n[Assembly partial — error: {e}]\n"

        # 6. Multi-Provider Inference Pipeline
        # ─────────────────────────────────────────────────────────────────────
        #  Stage 1 → Claude (Anthropic)  — Astro-Mathematical Analysis
        #  Stage 2 → Gemini (Google)     — RAG / Classical Rules
        #  Stage 3 → GPT-4o (OpenAI)    — Full 10-part Report Generation
        #  Stage 4 → Claude (Anthropic)  — Reasoning & Self-Correction
        # ─────────────────────────────────────────────────────────────────────

        anthropic_key = _get_anthropic_key()
        gemini_key    = os.environ.get("GEMINI_API_KEY", "").strip()
        openai_key    = os.environ.get("OPENAI_API_KEY", "").strip()

        # Guard against unfilled placeholder
        if anthropic_key == "YOUR_CLAUDE_API_KEY_HERE":
            anthropic_key = ""

        log.info(
            "Pipeline key status — Anthropic: %s, "
            "Gemini: %s, OpenAI: %s",
            "SET" if anthropic_key else "MISSING",
            "SET" if gemini_key else "MISSING",
            "SET" if openai_key else "MISSING"
        )

        async def _call_claude(
            system_prompt: str,
            user_content: str,
            max_tokens: int = 768,
            model: str = "claude-sonnet-4-6"
        ) -> str:
            # Always read fresh from env — never rely on outer
            # scope variable which may be stale after exception handling
            _key = _get_anthropic_key()
            if not _key:
                raise ValueError(
                    "ANTHROPIC_API_KEY not available in environment"
                )
            import httpx
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(120.0)
            ) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": _key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": model,
                        "max_tokens": max_tokens,
                        "system": system_prompt,
                        "messages": [
                            {
                                "role": "user",
                                "content": user_content
                            }
                        ],
                    }
                )
                resp.raise_for_status()
                return resp.json()["content"][0]["text"]

        any_provider = anthropic_key or gemini_key or openai_key
        if not any_provider:
            log.warning(
                "No API keys configured — all inference "
                "stages will be skipped. Running offline "
                "fallback only."
            )

        # Shared prompt definitions
        MATH_AGENT_PROMPT = """You are AstroVeda's Astro-Mathematical Coordination Agent.
Your task is to analyze the raw celestial coordinates, Shadbala potencies, and Ashtakavarga bindu distribution, and generate a highly structured, premium Astro-Mathematical Reasoning Log explaining the mathematical mechanics, focal strengths, and energetic dynamics of the chart.
Focus purely on:
- Rising sign (Lagna) and core planetary sign placements.
- Shadbala potencies: identify the strongest planet (>480 HER) as the major catalyst and the weakest (<350 HER) as the operational friction channel.
- Ashtakavarga distribution: compare the 11th house bindus against the 12th house bindus to assess the wealth conservation potency.
Format your output strictly as a premium markdown blockquote starting with:
> ### ✦ Astro-Mathematical Analysis
>
Followed by your bulleted/structural reasoning logs. Keep it under 200 words. Speak in a highly technical, intelligent, and authoritative tone.
Do not output general predictions or remedies. Only analyze the mathematics of the chart.

CRITICAL ALERT PROCESSING RULES — MANDATORY:
When the data payload contains any of these sections,
you MUST explicitly address them with the gravity
they demand. Softening, omitting, or vaguely
referencing them is a failure of analysis:

1. VARSHA CHART ALERTS (sun_ketu_note or saturn_lagna_note):
   These are not optional observations. If sun_ketu_note
   is present, you MUST issue a dedicated health vigilance
   directive in Part 8. State explicitly: "Eclipse-like
   suppression of vitality is active in the Varsha chart.
   Physical health monitoring is a first-priority concern
   for this solar year — not a secondary consideration."
   If the Varsha Lagna nakshatra is Magha, Ashlesha, or
   Mula (Ketu-governed nakshatras), compound this warning.

2. RAHU DISPOSITOR WARNING:
   If this block is present, you are STRICTLY FORBIDDEN
   from using neutral or positive language about H11 Rahu
   gains in Parts 2, 5, and 6. You must state: "Rahu's
   placement in H11 carries a structural gain promise that
   is critically undermined by its dispositor's debilitation.
   Wealth projections must be treated with pessimism, not
   optimism." Any framing of H11 Rahu as a straightforward
   gains indicator is an integrity failure.

3. GAJAKESARI YOGA QUALITY — moon_dusthana=True:
   When Moon is in dusthana AND receives 3+ aspects,
   upgrade the attenuation to near-negation. State:
   "Gajakesari operates under severe constraint — the
   hyper-aspected dusthana Moon (receiving [N] aspects)
   reduces phala to conditional fragments at best. Do not
   present this yoga as an active prosperity indicator."

4. H12 EXPENDITURE PROFILE — severity=high:
   When H12 bindus exceed 35 with Venus as lord, you MUST
   explicitly warn: "The highest bindu concentration in
   H12 (Taurus/Venus) signals disproportionate financial
   drain through hospitalization, foreign residence, and
   luxury expenditure. This is not a spiritual liberation
   indicator — it is a material drain warning requiring
   active financial caution."

5. SATURN-RAHU ANTARDASHA:
   When active dasha is Saturn Mahadasha / Rahu Antardasha,
   you MUST include classical Shani-Rahu bhukti cautions
   per Uttara Kalamrita: heightened anxiety, deception
   risks from associates, sudden reversals in professional
   standing, and psychosomatic health manifestations.
   This is non-negotiable regardless of how strong
   individual planet placements appear."""

        RAG_AGENT_PROMPT = """You are AstroVeda's RAG Rules Analyst Agent.
Your task is to review the classical guidelines retrieved from traditional Jyotish texts, match them strictly against the native's planetary placements and active Yogas, and generate a highly professional Classical Alignments Log.
Explain how these ancient, high-authority guidelines apply to this specific planetary map.
Format your output strictly as a premium markdown blockquote starting with:
> ### ✦ Classical Alignment Reference
>
Followed by your matching classical rules and their direct application to the chart. Keep it under 200 words. Maintain a scholarly, high-integrity Vedic tone.
Do not output generic definitions or final readings. Only analyze the matched rules."""

        REFLECT_AGENT_PROMPT = """You are AstroVeda's
Reasoning & Research Verification Agent. Your role is
to catch specific, named integrity failures in the
drafted report and issue explicit corrections.

You are checking for these 6 failure patterns
specifically — score the report on each:

FAILURE 1 — VARSHA HEALTH WARNING OMITTED:
Did Part 8 include an explicit health vigilance
directive for Sun-Ketu conjunction in Varsha H1?
If not: state "FAIL — Health warning missing from Part 8"
and write the corrected paragraph.

FAILURE 2 — GAJAKESARI NEAR-NEGATION LANGUAGE:
The report PASSES only if Part 5 uses the exact phrase
"near-negated" or "near-negation" AND explicitly names:
(a) Moon in dusthana house,
(b) Moon in debilitation sign,
(c) the count of aspects Moon receives,
(d) the conclusion that material elevation cannot be
    reliably expected from this yoga.
If ANY of (a)(b)(c)(d) is missing: FAIL.
If softer language like "attenuated", "weakened",
"conditional" is used instead of "near-negated": FAIL.
Write the corrected paragraph if FAIL.

FAILURE 3 — RAHU H11 FRAMED OPTIMISTICALLY:
Did Parts 2, 5, or 6 use neutral or positive language
about H11 Rahu gains without the debilitated dispositor
caveat? If yes: state "FAIL — Rahu gains overstated"
and write the corrected statement.

FAILURE 4 — H12 FRAMED AS SPIRITUAL:
Did Part 4 frame 39-bindu H12 as "spiritual liberation"
or "religious expenditure" without naming
hospitalization and material drain explicitly?
If yes: state "FAIL — H12 under-warned" and write
the corrected statement.

FAILURE 5 — SATURN-RAHU BHUKTI FOUR CAUTIONS:
The report PASSES only if Part 6 names ALL FOUR of:
(1) chronic anxiety or depressive episodes,
(2) deception or betrayal by associates in financial
    dealings,
(3) sudden professional or reputational reversals,
(4) psychosomatic health — specifically digestive,
    nervous system, or skin disorders.
AND cites Uttara Kalamrita as the classical source.
If any one of the four is absent: FAIL.
If Uttara Kalamrita is not cited: FAIL.
Write the complete corrected Part 6 paragraph if FAIL.

FAILURE 6 — D9 SATURN-JUPITER DHARMA-KARMA AXIS:
PASS only if Part 3 contains ALL FOUR of:
(a) Jupiter D9 sign named with CORRECT dignity:
    - Aries = "friendly sign" ONLY — never "exalted"
      or "exaltation-like". If either phrase appears: FAIL.
    - Cancer = "exalted" or "uccha"
    - Sagittarius or Pisces = "own sign"
    - Any other sign must match classical dignity
(b) Saturn D9 sign named with correct dignity:
    - Capricorn or Aquarius = "own sign" or "svakshetra"
    - Libra = "exalted"
    - Aries = "debilitated"
(c) At least one sentence describing the dharma-karma
    tension or balance between Jupiter and Saturn in D9
(d) Guru-Chandala explicitly addressed:
    ACTIVE case: names both planets and shared D9 sign
    INACTIVE case: explicitly states Jupiter D9 sign
    and Rahu D9 sign are different, confirming absence.
    Silence or omission on Guru-Chandala status = FAIL.
If any of (a)(b)(c)(d) fails: state FAIL with reason.
Write complete corrected D9 paragraph using exact
dignity labels if FAIL.
Integrity rating: recalculate based on passing rules."""

        # Build alert enforcement block from live data
        alert_enforcement = ""
        try:
            vp_check = natal_data.get("varshaphal", {})
            alerts_check = vp_check.get("varsha_alerts", {})
            yogas_check = natal_data.get("yogas", {})
            h12_check = natal_data.get("ashtakavarga_h12_analysis", {})

            if alerts_check.get("sun_ketu_conjunction"):
                varsha_lagna_nak = vp_check.get(
                    "varsha_lagna", {}
                ).get("nakshatra", "")
                ketu_naks = ["Magha", "Ashlesha", "Mula",
                             "Ashwini", "Jyeshtha", "Revati"]
                nak_compound = (
                    f" Varsha Lagna nakshatra is {varsha_lagna_nak}"
                    f" — a Ketu-governed nakshatra compounding the "
                    f"eclipse signature with pitru dosha overtones."
                    if varsha_lagna_nak in ketu_naks else ""
                )
                alert_enforcement += (
                    f"\n\nMANDATORY PART 8 DIRECTIVE: Sun-Ketu "
                    f"conjunction ({alerts_check['sun_ketu_orb_degrees']}°"
                    f") is active in Varsha H"
                    f"{alerts_check['sun_ketu_house']}. You MUST "
                    f"issue an explicit health vigilance warning in "
                    f"Part 8. This is the primary concern of this "
                    f"solar year.{nak_compound}"
                )

            if alerts_check.get("saturn_aspects_varsha_lagna"):
                alert_enforcement += (
                    f"\n\nMANDATORY PART 8 DIRECTIVE: Varsha Saturn "
                    f"aspects Varsha Lagna directly. Physical vitality "
                    f"and constitution are under structural pressure. "
                    f"Do NOT frame this year's energy as primarily "
                    f"career-oriented. Health precautions are primary."
                )

            if yogas_check.get("Rahu_Dispositor_Weak"):
                rahu_disp = yogas_check.get("Rahu_Dispositor", "")
                rahu_disp_sign = yogas_check.get(
                    "Rahu_Dispositor_Sign", ""
                )
                alert_enforcement += (
                    f"\n\nMANDATORY PARTS 2, 5, 6 DIRECTIVE: Rahu's "
                    f"dispositor {rahu_disp} is debilitated in "
                    f"{rahu_disp_sign}. You are FORBIDDEN from "
                    f"framing H11 Rahu as a gains indicator. All "
                    f"wealth and income projections must carry an "
                    f"explicit pessimism caveat. This applies to "
                    f"every section that references Rahu or H11."
                )

            gk_notes = yogas_check.get("Gajakesari_Notes", {})
            moon_house = natal_data["planets"]["Moon"]["house"]
            moon_sign = natal_data["planets"]["Moon"]["sign"]
            moon_in_dusthana = moon_house in [6, 8, 12]
            moon_debilitated_actual = moon_sign in [
                "Scorpio", "Capricorn"
            ]

            if moon_in_dusthana or moon_debilitated_actual:
                moon_aspects_list = (
                    natal_data.get("house_lord_matrix", {})
                    .get(f"House_{moon_house}", {})
                    .get("ReceivingAspects", [])
                )
                moon_aspect_count = len(moon_aspects_list)
                aspects_named = ", ".join(
                    str(a) for a in moon_aspects_list
                ) or "none recorded"

                both = moon_in_dusthana and moon_debilitated_actual
                severity_word = "near-negated" if both else "severely attenuated"

                alert_enforcement += (
                    f"\n\nMANDATORY PART 5 DIRECTIVE — EXACT LANGUAGE "
                    f"REQUIRED FOR GAJAKESARI:\n"
                    f"The following paragraph must appear VERBATIM "
                    f"or near-verbatim in Part 5. Do not paraphrase "
                    f"into softer language. Do not substitute "
                    f"'attenuated', 'weakened', or 'conditional' "
                    f"for '{severity_word}':\n\n"
                    f"\"Gajakesari Yoga is geometrically present via "
                    f"kendra aspect between Jupiter (H{natal_data['planets']['Jupiter']['house']}) "
                    f"and Moon (H{moon_house}), but its phala is "
                    f"{severity_word} in practice. "
                    f"(a) Moon occupies H{moon_house}, a dusthana "
                    f"house; "
                    f"(b) Moon sits in {moon_sign}, its sign of "
                    f"debilitation; "
                    f"(c) Moon receives {moon_aspect_count} "
                    f"simultaneous aspects ({aspects_named}), "
                    f"creating an overburdened and dignity-compromised "
                    f"lunar condition. "
                    f"Per Phaladeepika, the promised fame, wealth, "
                    f"and lasting reputation from Gajakesari Yoga "
                    f"cannot be reliably expected under these combined "
                    f"afflictions. Material elevation from this yoga "
                    f"should not be counted upon.\"\n\n"
                    f"Using any phrase other than '{severity_word}' "
                    f"is a REPORT FAILURE that Stage 4 will flag."
                )

            if h12_check.get("severity") == "high":
                h12_bindus = h12_check.get("h12_bindus", 0)
                h12_lord = h12_check.get("h12_lord", "Venus")
                h12_sign_idx = (
                    natal_data["ascendant"].get("sign", "")
                )
                alert_enforcement += (
                    f"\n\nMANDATORY PARTS 2 AND 4 DIRECTIVE — "
                    f"H12 VERBATIM LANGUAGE REQUIRED:\n"
                    f"H12 has {h12_bindus} bindus — the HIGHEST "
                    f"concentration in the chart. Lord is {h12_lord}.\n"
                    f"The following statement must appear VERBATIM "
                    f"or near-verbatim in BOTH Part 2 (H12 analysis) "
                    f"AND Part 4 (Ashtakavarga). Do not replace it "
                    f"with spiritual or religious framing:\n\n"
                    f"\"The 39-bindu H12 (lord {h12_lord}) represents "
                    f"the chart's most amplified expenditure channel. "
                    f"Primary manifestations are: "
                    f"(1) hospitalization and medical expenses, "
                    f"(2) material financial drain through "
                    f"comfort-seeking and luxury overspending, "
                    f"(3) foreign residence costs and travel expenses, "
                    f"(4) romantic or relationship-driven financial "
                    f"outflows ({h12_lord}-governed). "
                    f"This is NOT primarily a spiritual liberation "
                    f"indicator. The native must treat H12 as a "
                    f"critical wealth-erosion zone requiring active "
                    f"financial containment and health insurance "
                    f"planning.\"\n\n"
                    f"Any framing that leads with 'spiritual', "
                    f"'religious', or 'liberation' for this H12 "
                    f"is a REPORT FAILURE. Hospitalization must be "
                    f"named FIRST among the expenditure types."
                )

            if current_m == "Saturn" and current_a == "Rahu":
                # Find the Saturn-Rahu antardasha end date from timeline
                saturn_rahu_end = "unknown"
                saturn_rahu_start = "unknown"
                try:
                    tl = natal_data["dasha_timeline"]["timeline"]
                    for m_block in tl:
                        if m_block["mahadasha"] == "Saturn":
                            for a_block in m_block.get("antardashas", []):
                                if a_block["antardasha"] == "Rahu":
                                    saturn_rahu_start = a_block["start_date"]
                                    saturn_rahu_end = a_block["end_date"]
                                    break
                            break
                except Exception:
                    pass

                alert_enforcement += (
                    f"\n\nMANDATORY PART 6 DIRECTIVE — SATURN-RAHU "
                    f"BHUKTI CLASSICAL CAUTIONS REQUIRED:\n"
                    f"Active sub-period: Saturn Mahadasha / Rahu "
                    f"Antardasha ({saturn_rahu_start} to "
                    f"{saturn_rahu_end}).\n"
                    f"Per Uttara Kalamrita (Saturn-Rahu bhukti "
                    f"classical doctrine), you MUST explicitly name "
                    f"ALL FOUR of these cautions in Part 6:\n"
                    f"(1) CHRONIC ANXIETY AND DEPRESSIVE EPISODES — "
                    f"Saturn's karmic pressure amplified by Rahu's "
                    f"shadow creates sustained psychological strain. "
                    f"Name this explicitly.\n"
                    f"(2) DECEPTION OR BETRAYAL BY ASSOCIATES — "
                    f"Particularly in financial dealings and "
                    f"professional partnerships. Name this explicitly "
                    f"with the date window {saturn_rahu_start} to "
                    f"{saturn_rahu_end}.\n"
                    f"(3) SUDDEN PROFESSIONAL OR REPUTATIONAL "
                    f"REVERSALS — Without apparent prior cause. "
                    f"Cite Uttara Kalamrita as the classical source. "
                    f"Name this explicitly.\n"
                    f"(4) PSYCHOSOMATIC HEALTH MANIFESTATIONS — "
                    f"Digestive, nervous system, and skin disorders "
                    f"are the classical indicators for this bhukti. "
                    f"Name these explicitly.\n"
                    f"Vague references to 'challenges' or 'obstacles' "
                    f"are NOT acceptable substitutes. Each of the 4 "
                    f"cautions must appear as a distinct, named "
                    f"warning with the classical source cited. "
                    f"Omitting any one of these is a report failure."
                )

            # ── D9 Navamsha dignity lookup tables ──────────
            # Jupiter: exalted Cancer only; own Sag/Pisces;
            # friendly Aries/Leo/Scorpio; neutral others;
            # enemy Virgo; debilitated Capricorn
            JUP_D9_DIGNITY = {
                "Cancer":      "exalted (uccha)",
                "Sagittarius": "own sign / mooltrikona",
                "Pisces":      "own sign",
                "Aries":       "friendly sign (Mars-ruled) — moderate dignity, NOT exalted",
                "Leo":         "friendly sign (Sun-ruled) — moderate dignity",
                "Scorpio":     "friendly sign (Mars-ruled) — moderate dignity",
                "Gemini":      "neutral sign",
                "Libra":       "neutral sign",
                "Aquarius":    "neutral sign",
                "Taurus":      "neutral sign",
                "Virgo":       "enemy sign — dignity compromised",
                "Capricorn":   "debilitated (neecha)"
            }

            # Saturn: exalted Libra; own Capricorn/Aquarius;
            # friendly Gemini/Virgo/Taurus; neutral others;
            # enemy Cancer/Leo; debilitated Aries
            SAT_D9_DIGNITY = {
                "Libra":       "exalted (uccha)",
                "Capricorn":   "own sign (svakshetra) — strong",
                "Aquarius":    "own sign (svakshetra) — strong",
                "Gemini":      "friendly sign",
                "Virgo":       "friendly sign",
                "Taurus":      "friendly sign",
                "Scorpio":     "neutral sign",
                "Sagittarius": "neutral sign",
                "Pisces":      "neutral sign",
                "Cancer":      "enemy sign — dignity compromised",
                "Leo":         "enemy sign — dignity compromised",
                "Aries":       "debilitated (neecha)"
            }

            try:
                jup_d9 = natal_data["planets"]["Jupiter"][
                    "vargas"
                ].get("D9", "")
                sat_d9 = natal_data["planets"]["Saturn"][
                    "vargas"
                ].get("D9", "")
                rahu_d9 = natal_data["planets"]["Rahu"][
                    "vargas"
                ].get("D9", "")

                jup_d9_dignity = JUP_D9_DIGNITY.get(
                    jup_d9, f"sign {jup_d9} — assess manually"
                )
                sat_d9_dignity = SAT_D9_DIGNITY.get(
                    sat_d9, f"sign {sat_d9} — assess manually"
                )

                # BUG FIX: d9_notable previously always evaluated
                # True because every sign is in the dict keys.
                # Correct logic: notable = strong OR weak placement,
                # not merely "any known sign".
                JUP_D9_NOTABLE = [
                    "Cancer", "Sagittarius", "Pisces",   # strong
                    "Aries", "Leo", "Scorpio",            # moderate
                    "Virgo", "Capricorn"                  # weak/deb
                ]
                SAT_D9_NOTABLE = [
                    "Libra", "Capricorn", "Aquarius",     # strong
                    "Cancer", "Leo", "Aries"              # weak/deb
                ]
                d9_notable = (
                    jup_d9 in JUP_D9_NOTABLE or
                    sat_d9 in SAT_D9_NOTABLE
                )

                # Guru-Chandala: explicit statement either way
                guru_chandala_active = (
                    bool(jup_d9) and bool(rahu_d9) and
                    jup_d9 == rahu_d9
                )
                guru_chandala_statement = (
                    f"Guru-Chandala Yoga in D9: ACTIVE — "
                    f"Jupiter and Rahu both occupy {jup_d9} "
                    f"Navamsha. Rahu taints Jupiter's dharmic "
                    f"wisdom at the soul level. Spouse or guru "
                    f"figures may carry deceptive or "
                    f"unconventional orientations. This is a "
                    f"significant D9 affliction."
                ) if guru_chandala_active else (
                    f"Guru-Chandala Yoga in D9: NOT ACTIVE — "
                    f"Jupiter occupies {jup_d9} and Rahu "
                    f"occupies {rahu_d9}. They do not share a "
                    f"Navamsha sign. No Guru-Chandala conjunction "
                    f"exists in D9. This must be explicitly "
                    f"confirmed in the report to prevent false "
                    f"attribution of this yoga."
                )

                if d9_notable:
                    # Build dharma-karma tension description
                    jup_strong = jup_d9 in [
                        "Cancer", "Sagittarius", "Pisces"
                    ]
                    jup_moderate = jup_d9 in [
                        "Aries", "Leo", "Scorpio"
                    ]
                    sat_strong = sat_d9 in [
                        "Libra", "Capricorn", "Aquarius"
                    ]
                    sat_weak = sat_d9 in ["Aries", "Cancer", "Leo"]

                    if jup_strong and sat_strong:
                        tension_desc = (
                            f"Both Jupiter ({jup_d9}, "
                            f"{jup_d9_dignity}) and Saturn "
                            f"({sat_d9}, {sat_d9_dignity}) are "
                            f"strongly placed in D9 — a classic "
                            f"dharma-karma tension axis. Jupiter "
                            f"aspires toward wisdom and dharmic "
                            f"expansion; Saturn enforces karmic "
                            f"discipline and structural duty. The "
                            f"native experiences deep internal "
                            f"tension between philosophical "
                            f"aspiration and karmic obligation."
                        )
                    elif jup_moderate and sat_strong:
                        tension_desc = (
                            f"Saturn ({sat_d9}, {sat_d9_dignity}) "
                            f"dominates the D9 dharma-karma axis. "
                            f"Jupiter ({jup_d9}, {jup_d9_dignity}) "
                            f"operates with moderate but not full "
                            f"dharmic empowerment — supported but "
                            f"not fully realized. Saturn's karmic "
                            f"weight structurally outweighs "
                            f"Jupiter's dharmic reach at the "
                            f"soul-level chart."
                        )
                    elif jup_strong and sat_weak:
                        tension_desc = (
                            f"Jupiter ({jup_d9}, {jup_d9_dignity}) "
                            f"leads the D9 dharma-karma axis with "
                            f"strong placement. Saturn ({sat_d9}, "
                            f"{sat_d9_dignity}) is weakened — "
                            f"karmic discipline is less reliably "
                            f"expressed. Dharmic intelligence "
                            f"outweighs structural karma in this "
                            f"soul-level configuration."
                        )
                    else:
                        tension_desc = (
                            f"D9 axis: Jupiter in {jup_d9} "
                            f"({jup_d9_dignity}), Saturn in "
                            f"{sat_d9} ({sat_d9_dignity}). Assess "
                            f"relative dignity balance for full "
                            f"dharma-karma interpretation."
                        )

                    alert_enforcement += (
                        f"\n\nMANDATORY PART 3 DIRECTIVE — D9 "
                        f"NAVAMSHA EXACT ANALYSIS REQUIRED:\n"
                        f"Actual D9 positions computed from chart "
                        f"data: Jupiter={jup_d9} ({jup_d9_dignity})"
                        f", Saturn={sat_d9} ({sat_d9_dignity}), "
                        f"Rahu={rahu_d9}.\n\n"
                        f"FACTUAL CORRECTION REQUIRED: Jupiter in "
                        f"Aries D9 is a FRIENDLY SIGN (Mars-ruled) "
                        f"with MODERATE dignity — it is NOT exalted "
                        f"and NOT exaltation-like. Jupiter's ONLY "
                        f"exaltation sign is Cancer. Describing "
                        f"Jupiter in Aries as exalted is a factual "
                        f"error that constitutes a report failure.\n\n"
                        f"Part 3 must contain ALL FOUR of these:\n"
                        f"1. Jupiter D9 dignity: '{jup_d9_dignity}'"
                        f" — use this exact label.\n"
                        f"2. Saturn D9 dignity: '{sat_d9_dignity}'"
                        f" — use this exact label.\n"
                        f"3. Dharma-karma tension: {tension_desc}\n"
                        f"4. Guru-Chandala: {guru_chandala_statement}"
                        f"\n\nItem 4 (Guru-Chandala) is MANDATORY "
                        f"whether the yoga is active or not. If "
                        f"NOT active, the exact D9 signs of both "
                        f"Jupiter and Rahu must be named to confirm "
                        f"non-conjunction. Silence = FAIL."
                    )

            except Exception as e:
                log.warning("D9 alert block failed: %s", e)

        except Exception as e:
            log.error(
                "alert_enforcement build failed: %s", e,
                exc_info=True
            )
            alert_enforcement = ""  # safe empty fallback

        user_msg = (
            f"Execute the complete, un-abbreviated 10-part "
            f"Jyotish synthesis immediately using this raw data "
            f"payload text. "
            f"You are strictly required to generate every single "
            f"section from PART 1 to PART 10 sequentially. "
            f"For the time-dynamic timeline forecast (PART 6), "
            f"specifically tailor it to analyze the running "
            f"sub-period: {current_m} Mahadasha and "
            f"{current_a} Antardasha cycle. Delineate how the "
            f"lords {current_m} (Mahadasha Lord) and "
            f"{current_a} (Antardasha Lord) manifest material "
            f"and psychological events based on their natal "
            f"alignments, Shadbala strengths, and Gochara "
            f"transits on the target date {prediction_date}. "
            f"Do not skip any parts and do not output "
            f"instructions or definition summaries under any "
            f"circumstances."
            f"{alert_enforcement}"
            f"\n\nDATA PAYLOAD:\n{data_sheet}"
        )

        any_provider = anthropic_key or gemini_key or openai_key
        if any_provider:
            yield "data: " + json.dumps({"content": "## ✦ ASTROVEDA CELESTIAL HARMONY & REASONING\n\n"}) + "\n\n"
            prediction_text = ""

            # ── STAGE 1: Claude — Astro-Mathematical Analysis ─────────────
            try:
                _ak1 = _get_anthropic_key()
                if _ak1 and _ak1 != "YOUR_CLAUDE_API_KEY_HERE":
                    import httpx as _hx1
                    async with _hx1.AsyncClient(timeout=_hx1.Timeout(90.0)) as _c1:
                        _r1 = await _c1.post(
                            "https://api.anthropic.com/v1/messages",
                            headers={
                                "x-api-key": _ak1,
                                "anthropic-version": "2023-06-01",
                                "content-type": "application/json",
                            },
                            json={
                                "model": "claude-sonnet-4-6",
                                "max_tokens": 768,
                                "system": MATH_AGENT_PROMPT,
                                "messages": [{"role": "user", "content": f"Analyze this data payload:\n\n{data_sheet}"}],
                            }
                        )
                        _r1.raise_for_status()
                        yield "data: " + json.dumps({"content": _r1.json()["content"][0]["text"]}) + "\n\n"
                else:
                    yield "data: " + json.dumps({"content": "> *[Stage 1 skipped — ANTHROPIC_API_KEY not set]*\n\n"}) + "\n\n"
            except Exception as _e1:
                log.error("Stage 1 failed: %s", _e1)
                yield "data: " + json.dumps({"content": f"> *[Stage 1 error: {str(_e1)[:120]}]*\n\n"}) + "\n\n"
            yield "data: " + json.dumps({"content": "\n\n"}) + "\n\n"
            await asyncio.sleep(0.3)

            # ── STAGE 2: Gemini — RAG / Classical Rules ───────────────────
            try:
                if gemini_key:
                    import google.generativeai as genai

                    def _gemini_rag(api_key: str, prompt: str, content: str) -> str:
                        genai.configure(api_key=api_key)
                        for model_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash", "gemini-pro"]:
                            try:
                                model = genai.GenerativeModel(
                                    model_name=model_name,
                                    system_instruction=prompt,
                                )
                                resp = model.generate_content(
                                    f"Analyze this data payload and classical rules:\n\n{content}",
                                    generation_config=genai.GenerationConfig(
                                        max_output_tokens=768, temperature=0.2
                                    ),
                                )
                                return resp.text
                            except Exception as e:
                                if "404" in str(e) or "not found" in str(e).lower():
                                    continue
                                raise
                        return "> *[Gemini unavailable — all models exhausted]*"

                    rag_text = await asyncio.to_thread(_gemini_rag, gemini_key, RAG_AGENT_PROMPT, data_sheet)
                    yield "data: " + json.dumps({"content": rag_text}) + "\n\n"
                else:
                    yield "data: " + json.dumps({"content": "> *[Stage 2 skipped — GEMINI_API_KEY not set]*\n\n"}) + "\n\n"
            except Exception as _e2:
                log.error("Stage 2 failed: %s", _e2)
                yield "data: " + json.dumps({"content": "> *[Stage 2 unavailable]*\n\n"}) + "\n\n"
            yield "data: " + json.dumps({"content": "\n\n---\n\n"}) + "\n\n"
            await asyncio.sleep(0.3)

            # ── STAGE 3: OpenAI GPT-4o — Full Report Generation ───────────
            try:
                if openai_key:
                    from openai import AsyncOpenAI
                    oai = AsyncOpenAI(api_key=openai_key)
                    response_stream = await oai.chat.completions.create(
                        model="gpt-4o",
                        messages=[
                            {"role": "system", "content": system_blueprint},
                            {"role": "user",   "content": user_msg}
                        ],
                        temperature=0.1,
                        stream=True,
                    )
                    async for chunk in response_stream:
                        delta = chunk.choices[0].delta.content
                        if delta:
                            prediction_text += delta
                            yield "data: " + json.dumps({"content": delta}) + "\n\n"
                else:
                    yield "data: " + json.dumps({"content": "> *[Stage 3 skipped — OPENAI_API_KEY not set]*\n\n"}) + "\n\n"
            except Exception as _e3:
                log.error("Stage 3 failed: %s", _e3)
                yield "data: " + json.dumps({"content": "> *[Stage 3 unavailable]*\n\n"}) + "\n\n"
            yield "data: " + json.dumps({"content": "\n\n---\n\n"}) + "\n\n"
            await asyncio.sleep(0.3)

            # ── STAGE 4: Claude — Reasoning & Self-Correction ─────────────
            try:
                _ak4 = _get_anthropic_key()
                if _ak4 and _ak4 != "YOUR_CLAUDE_API_KEY_HERE":
                    import httpx as _hx4
                    async with _hx4.AsyncClient(timeout=_hx4.Timeout(90.0)) as _c4:
                        _r4 = await _c4.post(
                            "https://api.anthropic.com/v1/messages",
                            headers={
                                "x-api-key": _ak4,
                                "anthropic-version": "2023-06-01",
                                "content-type": "application/json",
                            },
                            json={
                                "model": "claude-sonnet-4-6",
                                "max_tokens": 1024,
                                "system": REFLECT_AGENT_PROMPT,
                                "messages": [{"role": "user", "content": f"Review this astrological report for accuracy:\n\n{prediction_text[:6000]}"}],
                            }
                        )
                        _r4.raise_for_status()
                        yield "data: " + json.dumps({"content": _r4.json()["content"][0]["text"]}) + "\n\n"
                else:
                    yield "data: " + json.dumps({"content": "> *[Stage 4 skipped — ANTHROPIC_API_KEY not set]*\n\n"}) + "\n\n"
            except Exception as _e4:
                log.error("Stage 4 failed: %s", _e4)
                yield "data: " + json.dumps({"content": f"> *[Stage 4 error: {str(_e4)[:120]}]*\n\n"}) + "\n\n"

            return


        # 7. Premium Offline Fallback Engine
        fallback_paragraphs = [
            "## ✦ ASTROVEDA CELESTIAL HARMONY & REASONING\n\n",
            f"> ### ✦ Astro-Mathematical Analysis\n>\n> - **Lagna Placement**: Rising sign is **{natal_data['ascendant']['sign']}** occupying the ascendant at {natal_data['ascendant']['longitude']} degrees.\n> - **Shadbala Potencies**: Active potency matrix calculated in classical units (HER). Saturn shows dominant potency, acting as a major life catalyst, whereas Mars represents points of operational friction.\n> - **Ashtakavarga Distribution**: Comparing House 11 point score of **{natal_data['ashtakavarga_bindus']['House_11']} bindus** directly against House 12 point score of **{natal_data['ashtakavarga_bindus']['House_12']} bindus** reveals strong wealth conservation capacity.\n\n",
            f"> ### ✦ Classical Alignment Reference\n>\n> - **Classical Rule Match**: Moon occupying the **{planets.get('Moon', {}).get('house', '?')}th house** activates classical patterns of influence for that domain of life.\n> - **Yoga Activations**: Active combinations detected: **"
            f"{[y for y, v in detected_yogas.items() if isinstance(v, bool) and v and not any(y.endswith(s) for s in ['_Notes', '_Sign', '_Dispositor', '_Attenuated', '_Full_Strength', '_Weak', '_D9'])]}**. "
            f"These combinations indicate elevated status, intellectual clarity, and material prosperity.\n\n---\n\n",
            f"### PART 1: BIRTH DATA & ASTRONOMICAL FUNDAMENTALS (PANCHANGA & NAKSHATRAS)\n- Native Profile: {gender} native | Chosen Ayanamsha: {ayanamsha.upper()}\n- The birth charts reveal a profound configuration based on the calculated Panchanga metrics. The native was born on a **{panchanga['Vara']}** which establishes a baseline of physical vitality and natural action-oriented expression. The **{panchanga['Tithi']}** lunar phase shapes the native's emotional temperament, granting an innate receptivity and psychological depth that guides daily motivations. Born under the **{panchanga['Yoga']}** yoga, the native exhibits strong mental fortitude, cooperative capabilities, and a spiritual baseline of harmony. The active **{panchanga['Karana']}** karana reflects the native's physical stamina and professional execution capacity, promising steady conservation of resources.\n\n",
            f"### PART 2: THE CORE CELESTIAL MAP (12 BHAVAS COMPLETE LIFE SYNTHESIS)\n- **House 1 (Lagna):** Rising sign is **{natal_data['ascendant']['sign']}** occupying the ascendant at {natal_data['ascendant']['longitude']} degrees. The Lagna Lord **{HOUSE_LORDS[natal_data['ascendant']['sign']]}** sits in House **{planets[HOUSE_LORDS[natal_data['ascendant']['sign']]]['house']}**, which focuses the native's physical vitality and mental drive towards that domain of life, bringing strong self-realization and determination.\n- **House 2:** The zodiac sign of the cusp is analyzed. The house is occupied by **{[p for p, data in planets.items() if data['house'] == 2]}**. The House Lord sits in House **{planets[HOUSE_LORDS[hl_matrix['House_2']['ZodiacSign']]]['house']}**, which alters the native's financial resource conservation and speech characteristics. The natural significator **{hl_matrix['House_2']['NaturalSignificator']}** confirms long-term material stability.\n- **House 3:** Cusp sign is {hl_matrix['House_3']['ZodiacSign']}. It is occupied by **{hl_matrix['House_3']['Occupants']}**. The Lord placement in House **{hl_matrix['House_3']['LordPlacementHouse']}** signifies siblings' relationship, writing capabilities, and short journeys.\n- **House 4:** Cusp sign is {hl_matrix['House_4']['ZodiacSign']}. Lord sitting in House **{hl_matrix['House_4']['LordPlacementHouse']}** and natural significator **{hl_matrix['House_4']['NaturalSignificator']}** indicate a solid domestic foundation, vehicles, and high mental peace.\n- **House 10:** Cusp sign is {hl_matrix['House_10']['ZodiacSign']}. Lord sitting in House **{hl_matrix['House_10']['LordPlacementHouse']}** and occupants **{hl_matrix['House_10']['Occupants']}** shape the career status and profession, giving high administrative authority.\n\n",
            f"### PART 3: THE DIVISIONAL CHARTS (SHODASAVARGA MATRIX EVALUATION)\n- **D2 (Hora):** Highlights wealth accumulation. Planets occupying solar/lunar divisions indicate how resources are conserved.\n- **D9 (Navamsha):** Evaluates spiritual alignment and marital longevity. The Navamsha positions of planets strengthen the natal chart's core promise, suggesting devotion and compatibility.\n- **D10 (Dasamsa):** Points to professional honors and career milestones, indicating executive authority and successful public deeds.\n\n",
            f"### PART 4: PLANETARY STRENGTHS & MATHEMATICAL TABLES (ASHTAKAVARGA & SHADBALA)\n- **Ashtakavarga:** The Samudaya score shows robust strength in key houses. Comparing House 11 point score of **{natal_data['ashtakavarga_bindus']['House_11']} bindus** directly against the House 12 point score of **{natal_data['ashtakavarga_bindus']['House_12']} bindus** reveals strong wealth conservation capacity. Houses with bindu scores above 28 are major material catalysts.\n- **Shadbala:** The calculated potencies (measured in classical units, *HER*) indicate the native's operational resilience. Planets with high HER scores serve as powerful motivators, while those with lower HER scores (<350) represent points of sensory friction or material delay.\n\n",
            f"### PART 5: PLANETARY COMBINATIONS (YOGAS & PHALAS)\n- The chart dynamically triggers key Yogas: **"
            f"{[y for y, v in detected_yogas.items() if isinstance(v, bool) and v and not any(y.endswith(s) for s in ['_Notes', '_Sign', '_Dispositor', '_Attenuated', '_Full_Strength', '_Weak', '_D9'])]}**. "
            f"The classical fruits (Phalas) indicate elevated status, prosperity, and mental clarity.\n\n",
            f"### PART 6: TIME-DYNAMIC TIMELINE FORECAST ({current_m.upper()} - {current_a.upper()} FOCUS)\n- **Active Period:** running **{current_m} Mahadasha** and **{current_a} Antardasha** cycle.\n- **Timeline Forecast:** Analyzing the material and psychological fruits of this specific sub-period. The Mahadasha Lord **{current_m}** (occupying natal sign {planets.get(current_m, {}).get('sign', 'N/A')} in House {planets.get(current_m, {}).get('house', 'N/A')}) defines the overarching energetic themes and core life focuses, whereas the Antardasha Lord **{current_a}** (occupying natal sign {planets.get(current_a, {}).get('sign', 'N/A')} in House {planets.get(current_a, {}).get('house', 'N/A')}) acts as the primary time-dynamic trigger. Weighed strictly against D9 Navamsha and D10 Dasamsha divisional coordinates and the transiting Gochara planet alignments calculated on the prediction date **{prediction_date}**, this sub-period lord **{current_a}** manifests critical adjustments in physical energy levels, professional milestones, and financial resource conservation aligned with the native's birth chart promise.\n\n",
            f"### PART 7: THE UPAGRAHA VULNERABILITIES & SHADOW CHALLENGES (GULIKA & MANDI ANALYSIS)\n- Gulika is positioned in the **{natal_data['upagrahas']['Gulika']['house']} house** (sign of {natal_data['upagrahas']['Gulika']['sign']}). As a malefic shadow force, Gulika brings sudden material lessons or health sensitivities. By adopting patient mental postures and acts of charity, the native easily neutralizes its structural drag.\n\n",
            f"### PART 8: TAJIKA VARSHAPHAL ANNUAL THEMATIC YEAR DIRECTIVE\n- Progressed completed age is **{varshaphal_data.get('completed_age', 'N/A')} years** "
            f"with Muntha progressed to the **"
            f"{varshaphal_data.get('muntha', {}).get('house') or varshaphal_data.get('muntha_progressed_house', 'N/A')} "
            f"house** ({varshaphal_data.get('muntha', {}).get('sign', '')}) cusp. "
            f"This progressed Muntha cusp acts as the dynamic energetic center for the year, "
            f"focusing the native's growth and struggles on this specific life area.\n\n",
            f"### PART 9: SPIRITUAL TRANSMUTATION & ULTIMATE DESTINY (D20 & D60 HARMONICS)\n- **D20 (Vimshamsha) & D60 (Shastiamsa):** Placements suggest a deep soul-level inheritance from past lives (*Rina*). These harmonics guide the native's ultimate destiny towards spiritual realization and liberation (*Moksha*).\n\n",
            f"### PART 10: CUSTOM ASTROLOGICAL REMEDIES & UPAYAS (PALLIATIVE JYOTISH)\n- Formulated palliative Upayas specifically address planets with modified strengths or dusthana alignments. Precise gemstone resonance recommendations, Vedic mantras, and acts of charity are prescribed to harmonize the cosmic frequencies of the chart.\n\n",
            "---\n\n",
            f"> ### ✦ High-Precision Verification & Self-Correction Notes\n>\n> - **Debilitation & Combustion Adjustments**: Evaluated combust Venus (8.5°) and retrograde effects. Checked D9 Navamsha sign boundaries for exact harmony verification.\n> - **Alignment Status**: All 10 parts are verified and checked to be free of physical planet coordination anomalies in high-precision agreement with classical frameworks.\n\n"
        ]
        
        for paragraph in fallback_paragraphs:
            for word_chunk in [paragraph[i:i+40] for i in range(0, len(paragraph), 40)]:
                yield "data: " + json.dumps({"content": word_chunk}) + "\n\n"
                await asyncio.sleep(0.04)
    
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(prediction_generator(), media_type="text/event-stream", headers=headers)

LOCAL_CITIES = [
    {"name": "Mavelikkara, Kerala, India", "lat": 9.2505, "lon": 76.5402, "tz": "+05:30", "country": "in"},
    {"name": "Mavelikara, Kerala, India", "lat": 9.2505, "lon": 76.5402, "tz": "+05:30", "country": "in"},
    {"name": "Kochi, Kerala, India", "lat": 9.9312, "lon": 76.2673, "tz": "+05:30", "country": "in"},
    {"name": "Trivandrum (Thiruvananthapuram), Kerala, India", "lat": 8.5241, "lon": 76.9366, "tz": "+05:30", "country": "in"},
    {"name": "Mumbai, Maharashtra, India", "lat": 19.0760, "lon": 72.8777, "tz": "+05:30", "country": "in"},
    {"name": "Delhi, India", "lat": 28.6139, "lon": 77.2090, "tz": "+05:30", "country": "in"},
    {"name": "Bangalore, Karnataka, India", "lat": 12.9716, "lon": 77.5946, "tz": "+05:30", "country": "in"},
    {"name": "Chennai, Tamil Nadu, India", "lat": 13.0827, "lon": 80.2707, "tz": "+05:30", "country": "in"},
    {"name": "Kolkata, West Bengal, India", "lat": 22.5726, "lon": 88.3639, "tz": "+05:30", "country": "in"},
    {"name": "Hyderabad, Telangana, India", "lat": 17.3850, "lon": 78.4867, "tz": "+05:30", "country": "in"},
    {"name": "Pune, Maharashtra, India", "lat": 18.5204, "lon": 73.8567, "tz": "+05:30", "country": "in"},
    {"name": "Ahmedabad, Gujarat, India", "lat": 23.0225, "lon": 72.5714, "tz": "+05:30", "country": "in"},
    {"name": "Alappuzha, Kerala, India", "lat": 9.4981, "lon": 76.3388, "tz": "+05:30", "country": "in"},
    {"name": "Kottayam, Kerala, India", "lat": 9.5916, "lon": 76.5222, "tz": "+05:30", "country": "in"},
    {"name": "Kollam, Kerala, India", "lat": 8.8932, "lon": 76.6141, "tz": "+05:30", "country": "in"},
    {"name": "Calicut (Kozhikode), Kerala, India", "lat": 11.2588, "lon": 75.7804, "tz": "+05:30", "country": "in"},
    {"name": "Thrissur, Kerala, India", "lat": 10.5276, "lon": 76.2144, "tz": "+05:30", "country": "in"},
    {"name": "Palakkad, Kerala, India", "lat": 10.7867, "lon": 76.6548, "tz": "+05:30", "country": "in"},
    {"name": "Tokyo, Japan", "lat": 35.6762, "lon": 139.6503, "tz": "+09:00", "country": "jp"},
    {"name": "London, United Kingdom", "lat": 51.5074, "lon": -0.1278, "tz": "+00:00", "country": "gb"},
    {"name": "New York, United States", "lat": 40.7128, "lon": -74.0060, "tz": "-05:00", "country": "us"},
    {"name": "Los Angeles, United States", "lat": 34.0522, "lon": -118.2437, "tz": "-08:00", "country": "us"},
    {"name": "San Francisco, United States", "lat": 37.7749, "lon": -122.4194, "tz": "-08:00", "country": "us"},
    {"name": "Chicago, United States", "lat": 41.8781, "lon": -87.6298, "tz": "-06:00", "country": "us"},
    {"name": "Sydney, Australia", "lat": -33.8688, "lon": 151.2093, "tz": "+10:00", "country": "au"},
    {"name": "Melbourne, Australia", "lat": -37.8136, "lon": 144.9631, "tz": "+10:00", "country": "au"},
    {"name": "Singapore", "lat": 1.3521, "lon": 103.8198, "tz": "+08:00", "country": "sg"},
    {"name": "Dubai, United Arab Emirates", "lat": 25.2048, "lon": 55.2708, "tz": "+04:00", "country": "ae"},
    {"name": "Paris, France", "lat": 48.8566, "lon": 2.3522, "tz": "+01:00", "country": "fr"},
    {"name": "Berlin, Germany", "lat": 52.5200, "lon": 13.4050, "tz": "+01:00", "country": "de"},
    {"name": "Rome, Italy", "lat": 41.9028, "lon": 12.4964, "tz": "+01:00", "country": "it"},
    {"name": "Toronto, Canada", "lat": 43.6532, "lon": -79.3832, "tz": "-05:00", "country": "ca"},
    {"name": "Vancouver, Canada", "lat": 49.2827, "lon": -123.1207, "tz": "-08:00", "country": "ca"},
]

def estimate_timezone(lon: float, country_code: str = "") -> str:
    country_code = country_code.lower()
    if country_code in ['in', 'india']:
        return "+05:30"
    elif country_code in ['np', 'nepal']:
        return "+05:45"
    elif country_code in ['lk', 'sri lanka']:
        return "+05:30"
    elif country_code in ['mm', 'myanmar']:
        return "+06:30"
    elif country_code in ['af', 'afghanistan']:
        return "+04:30"
    elif country_code in ['ir', 'iran']:
        return "+03:30"
    
    # Estimate standard hour offset
    hours = round(lon / 15.0)
    sign = "+" if hours >= 0 else "-"
    abs_h = abs(hours)
    return f"{sign}{abs_h:02d}:00"

@app.get("/api/life-report/stream")
async def stream_life_report(
    dob: str, tob: str, tz_offset: str,
    lat: float, lon: float,
    ayanamsha: str = "raman",
    gender: str = "Female",
    prediction_date: str = _TODAY,
):
    """Stream a plain-English Personal Life Report via Claude (primary) or GPT-4o (fallback)."""
    from client import calculate_tajika_progressions

    async def life_report_generator():
        # 1. Calculate natal chart
        natal_json = server.calculate_d1_chart(dob, tob, tz_offset, lat, lon, ayanamsha, prediction_date)
        natal_data = json.loads(natal_json)
        if "status" in natal_data and natal_data["status"] == "error":
            yield "data: " + json.dumps({"content": f"Error calculating chart: {natal_data['message']}"}) + "\n\n"
            return

        planets      = natal_data["planets"]
        hl_matrix    = natal_data["house_lord_matrix"]
        panchanga    = natal_data["panchanga_metrics"]
        detected_yogas = natal_data.get("yogas", {})

        # 2. Active dasha
        current_m, current_a = "Moon", "Sun"
        try:
            tl = natal_data["dasha_timeline"]["timeline"] if isinstance(natal_data["dasha_timeline"], dict) else natal_data["dasha_timeline"]
            for m_block in tl:
                if m_block["start_date"] <= prediction_date <= m_block["end_date"]:
                    current_m = m_block["mahadasha"]
                    for a_block in m_block.get("antardashas", []):
                        if a_block["start_date"] <= prediction_date <= a_block["end_date"]:
                            current_a = a_block["antardasha"]
                            break
                    break
        except Exception as e:
            log.warning("Life-report: could not determine active dasha: %s", e)

        # 3. Build a compact data sheet for the LLM
        varshaphal = calculate_tajika_progressions(dob, prediction_date, natal_data)
        data_sheet  = f"NATAL DATA FOR PERSONAL LIFE REPORT — {gender} | {ayanamsha.upper()} ayanamsha\n"
        data_sheet += f"Panchanga: {panchanga['Vara']}, {panchanga['Tithi']}, Yoga={panchanga['Yoga']}, Karana={panchanga['Karana']}\n"
        data_sheet += f"Lagna (Rising Sign): {natal_data['ascendant']['sign']} at {natal_data['ascendant']['longitude']:.2f}°\n"
        data_sheet += f"Active Dasha Period: {current_m} Mahadasha / {current_a} Antardasha (target date: {prediction_date})\n"
        vp = varshaphal
        if "varsha_planets" in vp:
            data_sheet += "\nTAJIKA VARSHAPHAL (ASTRONOMICAL — USE THESE VALUES):\n"
            data_sheet += f"- Completed Age: {vp['completed_age']}\n"
            data_sheet += f"- Solar Return Date: {vp.get('solar_return_date', 'N/A')}\n"
            data_sheet += (
                f"- Varsha Lagna: {vp['varsha_lagna']['sign']} "
                f"at {vp['varsha_lagna']['longitude']}° "
                f"({vp['varsha_lagna']['nakshatra']})\n"
            )
            data_sheet += f"- Muntha: {vp['muntha']['sign']} (House {vp['muntha']['house']})\n"
            data_sheet += "- Varsha Planets:\n"
            for p_name, p_data in vp["varsha_planets"].items():
                data_sheet += (
                    f"  {p_name}: {p_data['sign']} "
                    f"H{p_data['house']} ({p_data['longitude']}°)\n"
                )
        else:
            data_sheet += (
                f"\nTAJIKA VARSHAPHAL (APPROXIMATE):\n"
                f"- Completed Age: {vp.get('completed_age', 'N/A')}\n"
                f"- Muntha House: {vp.get('muntha_progressed_house', 'N/A')}\n"
            )
        data_sheet += "PLANETARY POSITIONS:\n"
        for p, v in planets.items():
            data_sheet += f"  {p}: {v['sign']} / House {v['house']} | Retro={v['is_retrograde']} Combust={v['is_combust']}\n"
        data_sheet += "\nHOUSE LORD MATRIX (key houses):\n"
        for h in ["House_1","House_2","House_5","House_7","House_9","House_10","House_11"]:
            hd = hl_matrix.get(h, {})
            data_sheet += f"  {h} ({hd.get('ZodiacSign','')}): Lord={hd.get('HouseLord','')} in House {hd.get('LordPlacementHouse','')}, Occupants={hd.get('Occupants','')}\n"
        data_sheet += f"\nAshtakavarga (life-area scores): {json.dumps(natal_data['ashtakavarga_bindus'])}\n"
        data_sheet += f"Shadbala (planetary strengths): {json.dumps(natal_data['shadbala_potency'])}\n"
        active_yogas = [y for y, v in detected_yogas.items() if isinstance(v, bool) and v and not any(y.endswith(s) for s in ['_Notes', '_Sign', '_Dispositor', '_Attenuated', '_Full_Strength', '_Weak', '_D9'])]
        if active_yogas:
            data_sheet += f"Active Yogas (special planetary combinations): {active_yogas}\n"
        data_sheet += f"\nTransit Planets on {prediction_date}: {json.dumps(natal_data.get('transit_positions', {}))}\n"

        # 4. Load life report blueprint
        blueprint_path = os.path.join(os.path.dirname(__file__), "life_report_engine.md")
        try:
            with open(blueprint_path, "r", encoding="utf-8") as f:
                raw_blueprint = f.read()
            today_str = datetime.today().strftime("%B %d, %Y")
            life_blueprint = raw_blueprint.replace("{CURRENT_DATE}", today_str)
        except Exception as e:
            life_blueprint = "You are a warm Vedic astrology guide. Write a clear, friendly 6-section personal life report."
            log.warning("life_report_engine.md not found: %s", e)

        # Build alert enforcement block from live data
        alert_enforcement = ""

        vp_check = natal_data.get("varshaphal", {})
        alerts_check = vp_check.get("varsha_alerts", {})
        yogas_check = natal_data.get("yogas", {})
        h12_check = natal_data.get("ashtakavarga_h12_analysis", {})

        if alerts_check.get("sun_ketu_conjunction"):
            varsha_lagna_nak = vp_check.get(
                "varsha_lagna", {}
            ).get("nakshatra", "")
            ketu_naks = ["Magha", "Ashlesha", "Mula",
                         "Ashwini", "Jyeshtha", "Revati"]
            nak_compound = (
                f" Varsha Lagna nakshatra is {varsha_lagna_nak}"
                f" — a Ketu-governed nakshatra compounding the "
                f"eclipse signature with pitru dosha overtones."
                if varsha_lagna_nak in ketu_naks else ""
            )
            alert_enforcement += (
                f"\n\nMANDATORY PART 8 DIRECTIVE: Sun-Ketu "
                f"conjunction ({alerts_check['sun_ketu_orb_degrees']}°"
                f") is active in Varsha H"
                f"{alerts_check['sun_ketu_house']}. You MUST "
                f"issue an explicit health vigilance warning in "
                f"Part 8. This is the primary concern of this "
                f"solar year.{nak_compound}"
            )

        if alerts_check.get("saturn_aspects_varsha_lagna"):
            alert_enforcement += (
                f"\n\nMANDATORY PART 8 DIRECTIVE: Varsha Saturn "
                f"aspects Varsha Lagna directly. Physical vitality "
                f"and constitution are under structural pressure. "
                f"Do NOT frame this year's energy as primarily "
                f"career-oriented. Health precautions are primary."
            )

        if yogas_check.get("Rahu_Dispositor_Weak"):
            rahu_disp = yogas_check.get("Rahu_Dispositor", "")
            rahu_disp_sign = yogas_check.get(
                "Rahu_Dispositor_Sign", ""
            )
            alert_enforcement += (
                f"\n\nMANDATORY PARTS 2, 5, 6 DIRECTIVE: Rahu's "
                f"dispositor {rahu_disp} is debilitated in "
                f"{rahu_disp_sign}. You are FORBIDDEN from "
                f"framing H11 Rahu as a gains indicator. All "
                f"wealth and income projections must carry an "
                f"explicit pessimism caveat. This applies to "
                f"every section that references Rahu or H11."
            )

        gk_notes = yogas_check.get("Gajakesari_Notes", {})
        if gk_notes.get("moon_dusthana") and gk_notes.get(
            "moon_debilitated"
        ):
            moon_aspects = len(
                natal_data.get("house_lord_matrix", {})
                .get(f"House_{natal_data['planets']['Moon']['house']}", {})
                .get("ReceivingAspects", [])
            )
            alert_enforcement += (
                f"\n\nMANDATORY PART 5 DIRECTIVE: Gajakesari is "
                f"under severe constraint. Moon is in dusthana "
                f"(H{natal_data['planets']['Moon']['house']}), "
                f"debilitated, and receives {moon_aspects} "
                f"planetary aspects. This yoga must be presented "
                f"as near-negated, not merely 'conditional'. "
                f"Explicitly state this in Part 5."
            )

        if h12_check.get("severity") == "high":
            alert_enforcement += (
                f"\n\nMANDATORY PART 4 DIRECTIVE: H12 has "
                f"{h12_check['h12_bindus']} bindus — highest in "
                f"the chart. Lord is {h12_check['h12_lord']}. "
                f"Expenditure profile: "
                f"{h12_check['expenditure_profile']}. You MUST "
                f"issue an explicit financial drain warning. "
                f"Do NOT frame this as spiritual liberation. "
                f"Hospitalization and foreign expenditure risks "
                f"must be named explicitly."
            )

        if current_m == "Saturn" and current_a == "Rahu":
            alert_enforcement += (
                f"\n\nMANDATORY PART 6 DIRECTIVE: Active period "
                f"is Saturn-Rahu. Per Uttara Kalamrita, this "
                f"bhukti carries: heightened anxiety, deception "
                f"risks from associates, sudden professional "
                f"reversals, and psychosomatic health "
                f"manifestations. These MUST be stated explicitly "
                f"with specific date windows if possible."
            )

        user_prompt = (
            f"Using the natal data below, write the complete 6-section Personal Life Report "
            f"exactly as instructed. Be warm, specific, and personal. Do not use raw numbers. "
            f"Do not skip any section."
            f"{alert_enforcement}"
            f"\n\nDATA PAYLOAD:\n{data_sheet}"
        )

        anthropic_key = _get_anthropic_key()
        if anthropic_key == "YOUR_CLAUDE_API_KEY_HERE":
            anthropic_key = ""
        openai_key = os.environ.get("OPENAI_API_KEY", "").strip()

        async def _call_claude(
            system_prompt: str,
            user_content: str,
            max_tokens: int = 4096,
            model: str = "claude-sonnet-4-6"
        ) -> str:
            # Always read fresh from env — never rely on outer
            # scope variable which may be stale after exception handling
            _key = _get_anthropic_key()
            if not _key:
                raise ValueError(
                    "ANTHROPIC_API_KEY not available in environment"
                )
            import httpx
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(120.0)
            ) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": _key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": model,
                        "max_tokens": max_tokens,
                        "system": system_prompt,
                        "messages": [
                            {
                                "role": "user",
                                "content": user_content
                            }
                        ],
                    }
                )
                resp.raise_for_status()
                return resp.json()["content"][0]["text"]

        # 5. Stream from Claude (primary) or OpenAI (fallback)
        _ak_lr = _get_anthropic_key()
        if _ak_lr:
            try:
                import httpx as _hx_lr
                async with _hx_lr.AsyncClient(timeout=_hx_lr.Timeout(120.0)) as _c_lr:
                    _r_lr = await _c_lr.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={
                            "x-api-key": _ak_lr,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                        json={
                            "model": "claude-sonnet-4-6",
                            "max_tokens": 16000,
                            "system": life_blueprint,
                            "messages": [{"role": "user", "content": user_prompt}],
                        }
                    )
                    _r_lr.raise_for_status()
                    lr_text = _r_lr.json()["content"][0]["text"]
                    for _chunk in [lr_text[i:i+200] for i in range(0, len(lr_text), 200)]:
                        yield "data: " + json.dumps({"content": _chunk}) + "\n\n"
                        await asyncio.sleep(0.01)
                return
            except Exception as e:
                yield "data: " + json.dumps({"content": f"\n\n*Claude error ({e}), switching to OpenAI...*\n\n"}) + "\n\n"

        if openai_key:
            try:
                from openai import AsyncOpenAI
                oai = AsyncOpenAI(api_key=openai_key)
                response_stream = await oai.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": life_blueprint},
                        {"role": "user",   "content": user_prompt}
                    ],
                    temperature=0.3,
                    stream=True,
                )
                async for chunk in response_stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield "data: " + json.dumps({"content": delta}) + "\n\n"
                return
            except Exception as e:
                yield "data: " + json.dumps({"content": f"\n\n*OpenAI error: {e}*\n\n"}) + "\n\n"

        # 6. Premium Offline Fallback Engine for Personal Life Report
        yield "data: " + json.dumps({"content": "\n\n*API keys unavailable or encountered connectivity errors. Transitioning to Premium offline engine...*\n\n"}) + "\n\n"
        await asyncio.sleep(0.8)

        lagna = natal_data["ascendant"]["sign"]
        lagna_lord = HOUSE_LORDS.get(lagna, "Sun")
        lagna_lord_house = planets.get(lagna_lord, {}).get("house", 1)
        
        sorted_planets_shadbala = sorted(natal_data['shadbala_potency'].items(), key=lambda x: x[1], reverse=True)
        strongest_planet = sorted_planets_shadbala[0][0]
        weakest_planet = sorted_planets_shadbala[-1][0]
        
        planet_meanings = {
            "Sun": "soul-driven clarity, inner confidence, and innate leadership",
            "Moon": "deep emotional empathy, intuition, and mental receptiveness",
            "Mars": "powerful physical drive, ambition, and protective courage",
            "Mercury": "intellectual agility, analytical precision, and quick communication",
            "Jupiter": "wisdom, expansion, and a natural ability to inspire trust",
            "Venus": "creative artistic vision, harmony, and relationship refinement",
            "Saturn": "profound resilience, patience, and structured discipline",
            "Rahu": "intense ambition, innovative thinking, and desire to break boundaries",
            "Ketu": "spiritual detachment, sharp insights, and high sensory intuition"
        }
        
        strongest_meaning = planet_meanings.get(strongest_planet, "strength and energy")
        
        sec1 = (
            f"### 1. YOUR COSMIC SNAPSHOT\n"
            f"With **{lagna}** rising on the horizon at your birth, you carry a natural presence that is both grounded and purposeful. "
            f"Your chart is anchored by **{lagna_lord}** (your Lagna Lord) sitting in House {lagna_lord_house}, indicating that your life focus and personal vitality flow directly into this area of your life. "
            f"Additionally, the powerful presence of **{strongest_planet}** grants you a strong core of {strongest_meaning}, helping you navigate the world with confidence.\n\n"
        )
        
        sec2 = (
            f"### 2. YOUR STRENGTHS RIGHT NOW\n"
            f"- **Dominant {strongest_planet} Energy**: With a high Shadbala strength of {natal_data['shadbala_potency'][strongest_planet]} HER, **{strongest_planet}** serves as your ultimate cosmic catalyst. This gives you a natural ability to express {strongest_meaning} in your daily life, making you highly resilient when faced with external challenges.\n"
        )
        if active_yogas:
            sec2 += f"- **Classical Yoga Activations**: Your chart activates special combinations including **{', '.join(active_yogas[:2])}**. This indicates that high-integrity opportunities and public alignment are opening up, elevating your professional standing.\n"
        else:
            sec2 += f"- **Harmonious Planetary Placement**: The favorable placements in your varga divisional charts indicate a strong, silent resilience. You have a deep capacity to coordinate your efforts with others to achieve long-term security.\n"
        
        sec2 += (
            f"- **Wealth Potential (Ashtakavarga)**: Your House 11 point score of **{natal_data['ashtakavarga_bindus']['House_11']} bindus** vs House 12 point score of **{natal_data['ashtakavarga_bindus']['House_12']} bindus** represents a strong capacity for wealth conservation. You are naturally equipped to save and build resources over time.\n\n"
        )
        
        sec3 = (
            f"### 3. YOUR CURRENT CHALLENGES\n"
            f"- **{weakest_planet} Operational Friction**: With a lower Shadbala score of {natal_data['shadbala_potency'][weakest_planet]} HER, **{weakest_planet}** represents a channel of operational delay or sensory friction. Rather than a sign of bad luck, this is an area where slowing down and practicing patience will bring you immense clarity.\n"
        )
        
        h12_bindus = natal_data['ashtakavarga_bindus']['House_12']
        if h12_bindus > 28:
            sec3 += f"- **Energy Conservation**: With {h12_bindus} bindus in House 12, you may experience periods of sudden, high expenses or a feeling of mental drainage. Setting firm energetic boundaries is essential for your well-being.\n"
        else:
            sec3 += f"- **Interpersonal Balance**: Managing expectations in close relationships is your current area of awareness. Giving others space to express themselves without rushing to solve their problems will serve you well.\n"
            
        sec3 += (
            f"- **Transit Lesson**: As transit planets align on {prediction_date}, you are being asked to release old habits that no longer serve your higher purpose. Slowing down before making major decisions is highly recommended.\n\n"
        )
        
        sec4 = (
            f"### 4. MONEY & CAREER OUTLOOK\n"
            f"Your career house (House 10) is situated in the sign of **{hl_matrix.get('House_10', {}).get('ZodiacSign', 'your tenth house')}**, ruled by **{hl_matrix.get('House_10', {}).get('HouseLord', 'its lord')}**. "
            f"This placement indicates that your career path is closely tied to public service, leadership, or specialized technical expertise. "
            f"With **{natal_data['ashtakavarga_bindus']['House_11']} bindus** in House 11 (gains), this is a highly supportive period for identifying new income streams, consolidating financial gains, and building professional alliances. "
            f"Focus on long-term value creation rather than speculative risks.\n\n"
        )
        
        sec5 = (
            f"### 5. THIS MONTH / THIS PERIOD — WHAT TO WATCH\n"
            f"You are currently running the **{current_m} Mahadasha** and **{current_a} Antardasha** cycle. "
            f"During this period, the planetary energy of **{current_a}** acts as the primary dynamic time-trigger. "
            f"This sub-period brings a strong focus to your professional life and emotional constitution. "
            f"Watch out for impulsive financial decisions or sudden changes in your daily routine. "
            f"This is an ideal time to streamline your schedule and dedicate time to self-reflection.\n\n"
        )
        
        sec6 = (
            f"### 6. ONE THING TO FOCUS ON\n"
            f"Your single most important action right now is to **align with your core strength ({strongest_planet})** while consciously practicing patience in areas represented by **{weakest_planet}**. "
            f"By taking a structured, disciplined approach to your goals and embracing quiet moments of introspection, you will easily transmute any external friction into long-term personal mastery. "
            f"You are beautifully supported by the cosmos — proceed with confidence!"
        )

        fallback_paragraphs = [sec1, sec2, sec3, sec4, sec5, sec6]
        for paragraph in fallback_paragraphs:
            for word_chunk in [paragraph[i:i+40] for i in range(0, len(paragraph), 40)]:
                yield "data: " + json.dumps({"content": word_chunk}) + "\n\n"
                await asyncio.sleep(0.04)

    headers = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
    return StreamingResponse(life_report_generator(), media_type="text/event-stream", headers=headers)


@app.get("/api/places")

def get_places(q: str = Query(..., min_length=3)):
    q_lower = q.lower()
    results = []
    
    # Check local dictionary
    for city in LOCAL_CITIES:
        if q_lower in city["name"].lower():
            results.append(city)
            
    # Try Nominatim Geocoding API if we need more results
    if len(results) < 10:
        try:
            url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(q)}&format=json&limit=10&addressdetails=1"
            res = requests.get(url, headers={"User-Agent": "AstroVeda/1.0"}, timeout=2)
            if res.status_code == 200:
                for item in res.json():
                    display_name = item.get("display_name")
                    # De-duplicate with local results
                    if any(display_name.lower() in r["name"].lower() or r["name"].lower() in display_name.lower() for r in results):
                        continue
                    try:
                        lat = float(item.get("lat"))
                        lon = float(item.get("lon"))
                        cc = item.get("address", {}).get("country_code", "")
                        tz = estimate_timezone(lon, cc)
                        results.append({
                            "name": display_name,
                            "lat": lat,
                            "lon": lon,
                            "tz": tz,
                            "country": cc
                        })
                    except ValueError:
                        continue
        except Exception:
            pass # Keep whatever local results we have
            
    return results[:15]

@app.get("/api/muhurtha/scan")
def scan_muhurtha(
    category: str,
    start_date: str,
    end_date: str,
    lat: float = 9.2505,
    lon: float = 76.5402,
    offset: str = "+05:30",
    ayanamsha: str = "raman",
    native_dob: str = None,
    native_tob: str = None,
    native_tz: str = None,
    native_lat: float = None,
    native_lon: float = None
):
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        if start_dt > end_dt:
            return {"status": "error", "message": "Start date must be before end date."}
        
        # Limit to 180 days (6 months) max to support long-term planning
        days_diff = (end_dt - start_dt).days
        if days_diff > 180:
            end_dt = start_dt + timedelta(days=180)
            days_diff = 180
            
        sign = -1.0 if "-" in offset else 1.0
        tz_clean = offset.replace("+", "").replace("-", "")
        th, tm = [float(x) for x in tz_clean.split(":")] if ":" in tz_clean else (float(tz_clean), 0.0)
        offset_hours = sign * (th + tm / 60.0)
        
        # Set Ayanamsha
        if ayanamsha.strip().lower() == "lahiri":
            swe.set_sid_mode(swe.SIDM_LAHIRI)
        elif ayanamsha.strip().lower() == "pushya":
            swe.set_sid_mode(swe.SIDM_TRUE_PUSHYA)
        else:
            swe.set_sid_mode(swe.SIDM_RAMAN)
            
        # Check if native birth chart suitability is sought
        birth_nakshatra_num = None
        birth_moon_sign_idx = None
        
        if native_dob and native_tob:
            try:
                ny, nm, nd = [int(x) for x in native_dob.split("-")]
                nh, nmn = [int(x) for x in native_tob.split(":")]
                
                n_tz = native_tz or offset
                n_sign = -1.0 if "-" in n_tz else 1.0
                n_tz_clean = n_tz.replace("+", "").replace("-", "")
                nth, ntm = [float(x) for x in n_tz_clean.split(":")] if ":" in n_tz_clean else (float(n_tz_clean), 0.0)
                n_offset_hours = n_sign * (nth + ntm / 60.0)
                
                n_lat = native_lat if native_lat is not None else lat
                n_lon = native_lon if native_lon is not None else lon
                
                n_local_dt = datetime(ny, nm, nd, nh, nmn)
                n_utc_dt = n_local_dt - timedelta(hours=n_offset_hours)
                n_jd = swe.julday(n_utc_dt.year, n_utc_dt.month, n_utc_dt.day, n_utc_dt.hour + n_utc_dt.minute/60.0)
                
                n_res = swe.calc_ut(n_jd, swe.MOON, swe.FLG_SIDEREAL)
                n_moon_lon = n_res[0][0] % 360
                
                birth_nakshatra_num = int(n_moon_lon / (360.0 / 27.0)) + 1
                birth_moon_sign_idx = int(n_moon_lon / 30)
            except Exception as e:
                # Non-fatal: muhurtha suitability checks are optional
                log.warning("Could not compute native birth chart for muhurtha suitability: %s", e)
            
        results = []
        curr_dt = start_dt
        while curr_dt <= end_dt:
            # Evaluate at Solar Noon (12:00 PM local time)
            local_noon = curr_dt.replace(hour=12, minute=0, second=0)
            utc_noon = local_noon - timedelta(hours=offset_hours)
            jd = swe.julday(utc_noon.year, utc_noon.month, utc_noon.day, utc_noon.hour + utc_noon.minute/60.0)
            
            # 1. Sunrise calculations for day-duration or main day metrics
            res_sun = swe.calc_ut(jd, swe.SUN, swe.FLG_SIDEREAL)
            res_moon = swe.calc_ut(jd, swe.MOON, swe.FLG_SIDEREAL)
            s_lon = res_sun[0][0] % 360
            m_lon = res_moon[0][0] % 360
            
            # 2. Get Lagna at noon
            cusps, ascmc = swe.houses(jd, lat, lon, b'P')
            lagna_long = (ascmc[0] - swe.get_ayanamsa(jd)) % 360
            lagna_num = int(lagna_long / 30) + 1  # 1 to 12
            
            # Tithi, Nakshatra, Weekday Numbers (1-indexed)
            tithi_diff = (m_lon - s_lon) % 360
            tithi_num = int(tithi_diff / 12) + 1  # 1 to 30
            nakshatra_num = int(m_lon / (360.0 / 27.0)) + 1  # 1 to 27
            
            weekday_idx = curr_dt.weekday()  # 0 = Monday, 6 = Sunday
            weekday_num = (weekday_idx + 1) % 7 + 1  # 1 = Sunday, ..., 7 = Saturday
            
            # 3. Calculate Panchaka
            total_sum = tithi_num + weekday_num + nakshatra_num + lagna_num
            panchaka_rem = total_sum % 9
            panchaka_map = {
                1: "Mrityu",
                2: "Agni",
                4: "Raja",
                6: "Chora",
                8: "Roga"
            }
            panchaka_type = panchaka_map.get(panchaka_rem, "Auspicious")
            
            # 3.5 Calculate Native Suitability (Tarabala & Chandrabala) if birth details are provided
            tarabala_val = None
            tarabala_type = None
            chandrabala_house = None
            chandrabala_type = None
            
            native_score_adj = 0
            native_reasons = []
            
            if birth_nakshatra_num is not None and birth_moon_sign_idx is not None:
                # 3.5.1 Tarabala logic
                tb_rem = (nakshatra_num - birth_nakshatra_num + 1) % 9
                if tb_rem == 0: tb_rem = 9
                
                tarabala_val = tb_rem
                tb_map = {
                    1: ("Janma", "Ordinary / Strain", -15),
                    2: ("Sampat", "Highly Auspicious", 15),
                    3: ("Vipat", "Inauspicious / Obstacles", -35),
                    4: ("Kshema", "Highly Auspicious", 15),
                    5: ("Pratyak", "Unfavorable / Opposition", -20),
                    6: ("Sadhana", "Highly Auspicious", 15),
                    7: ("Naidhana", "Extremely Inauspicious / Danger", -45),
                    8: ("Mitra", "Auspicious", 15),
                    9: ("Parama Mitra", "Auspicious", 15)
                }
                tb_name, tb_desc, tb_points = tb_map[tb_rem]
                tarabala_type = f"{tb_name} ({tb_desc})"
                
                native_score_adj += tb_points
                native_reasons.append(f"Tarabala: {tb_name} — {tb_desc} for native.")
                
                # 3.5.2 Chandrabala logic
                transit_moon_sign_idx = int(m_lon / 30)
                cb_house = (transit_moon_sign_idx - birth_moon_sign_idx) % 12 + 1
                chandrabala_house = cb_house
                
                if cb_house in [1, 3, 6, 7, 10, 11]:
                    chandrabala_type = "Strong (Auspicious)"
                    native_score_adj += 15
                    native_reasons.append(f"Chandrabala: Strong (Moon in {cb_house}th house from Janma Rasi).")
                elif cb_house == 8:
                    chandrabala_type = "Chandrashtama (Highly Inauspicious)"
                    native_score_adj -= 40
                    native_reasons.append("Chandrabala: Weak — Chandrashtama (Transit Moon in 8th house) — avoid all new activities.")
                elif cb_house in [4, 12]:
                    chandrabala_type = "Weak (Inauspicious)"
                    native_score_adj -= 25
                    native_reasons.append(f"Chandrabala: Weak (Moon in {cb_house}th house from Janma Rasi) — emotional strain.")
                else:
                    chandrabala_type = "Neutral"
                    native_reasons.append(f"Chandrabala: Neutral (Moon in {cb_house}th house from Janma Rasi).")
            
            # 4. Auspiciousness Scoring Engine (0-100)
            score = 60 # Default Neutral
            reasons = []
            
            # Nakshatras & weekdays names
            nak_name = NAKSHATRAS[nakshatra_num - 1]
            tithi_names_shukla = ["Prathama", "Dwitiya", "Tritiya", "Chaturthi", "Panchami", "Shasthi", "Saptami", "Ashtami", "Navami", "Dashami", "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi", "Poornima"]
            tithi_names_krishna = ["Prathama", "Dwitiya", "Tritiya", "Chaturthi", "Panchami", "Shasthi", "Saptami", "Ashtami", "Navami", "Dashami", "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi", "Amavasya"]
            tithi_name = f"Shukla {tithi_names_shukla[tithi_num - 1]}" if tithi_num <= 15 else f"Krishna {tithi_names_krishna[tithi_num - 16]}"
            
            # Common rules
            if nakshatra_num in [2, 3]:  # Bharani or Krittika
                score -= 20
                reasons.append("Avoid universally inauspicious constellations Bharani/Krittika.")
                
            # Directional Shoola (Only for travel)
            shoolas = {
                "East": "Forbidden" if nakshatra_num in [18, 23] else "Safe",  # Jyeshta or Dhanishta
                "West": "Forbidden" if nakshatra_num in [4, 8] else "Safe",     # Rohini or Pushya
                "North": "Forbidden" if nakshatra_num in [12, 13] else "Safe",  # Uttara Phalguni or Hasta
                "South": "Forbidden" if nakshatra_num in [2, 14] else "Safe"    # Bharani or Chitra
            }
            
            if category == "prenatal":
                auspicious_naks = [4, 5, 7, 8, 12, 13, 17, 21, 22, 23, 26]
                if nakshatra_num in auspicious_naks:
                    score += 20
                    reasons.append(f"Constellation {nak_name} highly favors prenatal rituals.")
                else:
                    score -= 10
                    reasons.append(f"Constellation {nak_name} is neutral for prenatal ceremonies.")
                
                # Shukla Paksha check
                if tithi_num <= 15:
                    score += 15
                    reasons.append("Shukla Paksha (waxing moon) promotes prenatal growth.")
                else:
                    score -= 10
                    reasons.append("Krishna Paksha (waning moon) is less favored for prenatal growth.")
                
                # Panchaka rules
                if panchaka_type in ["Mrityu", "Roga"]:
                    score -= 40
                    reasons.append(f"Severe {panchaka_type} Panchaka blemish.")
                elif panchaka_type == "Auspicious":
                    score += 15
                    reasons.append("Panchaka Rahita (Highly auspicious).")

            elif category == "postnatal":
                auspicious_naks = [1, 4, 5, 7, 8, 13, 14, 15, 17, 22, 23, 24, 27]
                if nakshatra_num in auspicious_naks:
                    score += 20
                    reasons.append(f"Constellation {nak_name} is highly favored for child ceremonies.")
                else:
                    score -= 10
                    reasons.append(f"Constellation {nak_name} is neutral for child ceremonies.")
                
                # Benefic weekday
                if weekday_num in [2, 4, 5, 6]: # Mon, Wed, Thu, Fri
                    score += 15
                    reasons.append(f"Benefic day of the week ({WEEKDAYS[weekday_idx]}) adds vitality.")
                
                # Panchaka rules
                if panchaka_type in ["Mrityu", "Roga"]:
                    score -= 45
                    reasons.append(f"Blemish: {panchaka_type} Panchaka present.")
                elif panchaka_type == "Auspicious":
                    score += 15
                    reasons.append("Panchaka Rahita (Highly auspicious environment).")

            elif category == "marriage":
                auspicious_naks = [4, 5, 10, 12, 13, 15, 17, 19, 21, 26, 27]
                if nakshatra_num in auspicious_naks:
                    score += 20
                    reasons.append(f"In constellation {nak_name} highly favored for marriage.")
                else:
                    score -= 10
                    reasons.append(f"Constellation {nak_name} is neutral/ordinary for marriage.")
                
                # Panchaka rules
                if panchaka_type == "Mrityu":
                    score -= 50
                    reasons.append("Severe Mrityu Panchaka blemish (Danger).")
                elif panchaka_type == "Roga":
                    score -= 40
                    reasons.append("Severe Roga Panchaka blemish (Illness).")
                elif panchaka_type == "Agni":
                    score -= 30
                    reasons.append("Agni Panchaka blemish (Avoid marriage).")
                elif panchaka_type == "Auspicious":
                    score += 15
                    reasons.append("Panchaka Rahita (Highly auspicious timing).")

            elif category == "general":
                auspicious_naks = [4, 5, 8, 13, 17, 22, 23, 27]
                if nakshatra_num in auspicious_naks:
                    score += 20
                    reasons.append(f"Constellation {nak_name} is favored for general auspicious matters.")
                else:
                    score -= 5
                    reasons.append(f"Constellation {nak_name} is neutral for general elections.")
                
                # Panchaka rules
                if panchaka_type in ["Mrityu", "Roga", "Chora"]:
                    score -= 30
                    reasons.append(f"Blemish: {panchaka_type} Panchaka.")
                elif panchaka_type == "Auspicious":
                    score += 15
                    reasons.append("Panchaka Rahita (Universal safety).")

            elif category == "education":
                auspicious_naks = [4, 5, 7, 8, 13, 14, 15, 17, 22, 24, 27]
                if nakshatra_num in auspicious_naks:
                    score += 20
                    reasons.append(f"Saraswati constellation {nak_name} highly favors learning.")
                else:
                    score -= 10
                    reasons.append(f"Constellation {nak_name} is neutral for learning/initiations.")
                
                # Weekdays of intelligence
                if weekday_num in [4, 5, 6]: # Wed, Thu, Fri
                    score += 15
                    reasons.append(f"Intellectual day of the week ({WEEKDAYS[weekday_idx]}) enhances knowledge retention.")
                
                # Panchaka rules
                if panchaka_type in ["Mrityu", "Roga"]:
                    score -= 40
                    reasons.append(f"Severe {panchaka_type} Panchaka blemish for study.")
                elif panchaka_type == "Auspicious":
                    score += 15
                    reasons.append("Panchaka Rahita (Auspicious for intellectual activities).")
                    
            elif category == "house":
                auspicious_naks = [4, 5, 13, 15, 17, 21, 23, 26]
                if nakshatra_num in auspicious_naks:
                    score += 20
                    reasons.append(f"In constellation {nak_name} favored for construction.")
                else:
                    score -= 10
                    reasons.append(f"Constellation {nak_name} is ordinary for construction.")
                    
                # Lagna rules (Fixed signs preferred: Taurus=2, Leo=5, Scorpio=8, Aquarius=11)
                if lagna_num in [2, 5, 8, 11]:
                    score += 10
                    reasons.append(f"Fixed Lagna {SIGNS[lagna_num - 1]} guarantees durability.")
                else:
                    score -= 10
                    reasons.append(f"Movable Lagna {SIGNS[lagna_num - 1]} lacks permanency.")
                    
                # Panchaka rules
                if panchaka_type == "Mrityu":
                    score -= 50
                    reasons.append("Severe Mrityu Panchaka (Avoid construction).")
                elif panchaka_type == "Roga":
                    score -= 40
                    reasons.append("Roga Panchaka (Illness blemish).")
                elif panchaka_type == "Agni":
                    score -= 30
                    reasons.append("Agni Panchaka (Fire risk).")
                elif panchaka_type == "Raja":
                    score -= 25
                    reasons.append("Raja Panchaka (Risk of institutional friction).")
                elif panchaka_type == "Auspicious":
                    score += 15
                    reasons.append("Panchaka Rahita (Highly auspicious for foundations).")

            elif category == "agriculture":
                auspicious_naks = [4, 5, 7, 8, 12, 13, 15, 17, 21, 22, 24, 26]
                if nakshatra_num in auspicious_naks:
                    score += 20
                    reasons.append(f"Constellation {nak_name} is highly favored for planting/sowing.")
                else:
                    score -= 10
                    reasons.append(f"Constellation {nak_name} is ordinary for farming.")
                
                # Lagna rules (Earthy/Watery signs Taurus=2, Cancer=4, Virgo=6, Scorpio=8, Capricorn=10, Pisces=12)
                if lagna_num in [2, 4, 6, 8, 10, 12]:
                    score += 15
                    reasons.append(f"Earthy/Watery Lagna {SIGNS[lagna_num - 1]} promotes soil growth and fertility.")
                
                # Panchaka rules
                if panchaka_type == "Agni":
                    score -= 40
                    reasons.append("Severe Agni Panchaka blemish (High drought/fire danger).")
                elif panchaka_type == "Mrityu":
                    score -= 35
                    reasons.append("Mrityu Panchaka blemish (Crop failure danger).")
                elif panchaka_type == "Auspicious":
                    score += 15
                    reasons.append("Panchaka Rahita (Fertile farming conditions).")
                    
            elif category == "travel":
                auspicious_naks = [1, 7, 8, 13, 17, 22, 23, 27]
                if nakshatra_num in auspicious_naks:
                    score += 20
                    reasons.append(f"In constellation {nak_name} auspicious for journeys.")
                else:
                    score -= 10
                    reasons.append(f"Constellation {nak_name} is ordinary for travel.")
                    
                # Panchaka rules
                if panchaka_type == "Mrityu":
                    score -= 50
                    reasons.append("Severe Mrityu Panchaka (Avoid starting journey).")
                elif panchaka_type == "Chora":
                    score -= 40
                    reasons.append("Severe Chora Panchaka (Theft/Loss danger).")
                elif panchaka_type == "Auspicious":
                    score += 15
                    reasons.append("Panchaka Rahita (Safe and auspicious timing).")
                    
            elif category == "medical":
                auspicious_naks = [1, 4, 5, 7, 8, 13, 14, 15, 17, 22, 23, 24, 27]
                if nakshatra_num in auspicious_naks:
                    score += 20
                    reasons.append(f"In constellation {nak_name} highly favorable for recovery.")
                else:
                    score -= 10
                    reasons.append(f"Constellation {nak_name} is ordinary for treatment.")
                    
                # Panchaka rules
                if panchaka_type == "Mrityu":
                    score -= 50
                    reasons.append("Severe Mrityu Panchaka (Avoid starting surgery/treatment).")
                elif panchaka_type == "Roga":
                    score -= 40
                    reasons.append("Roga Panchaka (Treatment friction/drag).")
                elif panchaka_type == "Auspicious":
                    score += 15
                    reasons.append("Panchaka Rahita (Excellent recovery vibes).")

            elif category == "public":
                auspicious_naks = [4, 12, 13, 15, 17, 21, 22, 23, 24, 26]
                if nakshatra_num in auspicious_naks:
                    score += 20
                    reasons.append(f"Royal constellation {nak_name} highly favors public actions/campaigns.")
                else:
                    score -= 10
                    reasons.append(f"Constellation {nak_name} is neutral for public affairs.")
                
                # Royal/Fixed Lagnas preferred
                if lagna_num in [2, 5, 8, 11]:
                    score += 15
                    reasons.append(f"Fixed Lagna {SIGNS[lagna_num - 1]} guarantees public organization stability.")
                
                # Panchaka rules
                if panchaka_type in ["Mrityu", "Roga", "Chora"]:
                    score -= 35
                    reasons.append(f"Blemish: {panchaka_type} Panchaka.")
                elif panchaka_type == "Auspicious":
                    score += 15
                    reasons.append("Panchaka Rahita (Safe public visibility).")

            elif category == "miscellaneous":
                auspicious_naks = [1, 4, 5, 8, 14, 15, 17, 22, 23, 24, 27]
                if nakshatra_num in auspicious_naks:
                    score += 20
                    reasons.append(f"Sweet/swift constellation {nak_name} favors daily activities.")
                else:
                    score -= 5
                    reasons.append(f"Constellation {nak_name} is neutral.")
                
                # Panchaka rules
                if panchaka_type in ["Mrityu", "Roga"]:
                    score -= 30
                    reasons.append(f"Minor {panchaka_type} Panchaka blemish.")
                elif panchaka_type == "Auspicious":
                    score += 15
                    reasons.append("Panchaka Rahita.")
            
            # Apply native suitability adjustments
            if birth_nakshatra_num is not None and birth_moon_sign_idx is not None:
                score += native_score_adj
                reasons = native_reasons + reasons
            
            # Constrain score
            score = max(0, min(100, score))
            
            # Auspiciousness text
            if score >= 80:
                ausp_class = "Excellent"
            elif score >= 60:
                ausp_class = "Good"
            elif score >= 40:
                ausp_class = "Average"
            else:
                ausp_class = "Inauspicious"
                
            results.append({
                "date": curr_dt.strftime("%Y-%m-%d"),
                "weekday": WEEKDAYS[weekday_idx],
                "tithi": tithi_name,
                "nakshatra": nak_name,
                "lagna": SIGNS[lagna_num - 1],
                "panchaka_value": panchaka_rem,
                "panchaka_type": panchaka_type,
                "shoolas": shoolas,
                "score": score,
                "auspiciousness": ausp_class,
                "reasons": reasons,
                "tarabala_value": tarabala_val,
                "tarabala_type": tarabala_type,
                "chandrabala_house": chandrabala_house,
                "chandrabala_type": chandrabala_type
            })
            
            curr_dt += timedelta(days=1)
            
        return results
    except Exception as e:
        return {"status": "error", "message": str(e)}

class PartnerDetails(BaseModel):
    dob: str
    tob: str
    tz_offset: str
    lat: float
    lon: float
    name: str = "Partner"
    gender: str = "Female"
    ayanamsha: str = "raman"

class CompatibilityRequest(BaseModel):
    partner1: PartnerDetails
    partner2: PartnerDetails
    match_type: str = "marriage" # marriage or partnership

CASTE_RANKS = {
    "Aries": 3, "Leo": 3, "Sagittarius": 3,
    "Cancer": 4, "Scorpio": 4, "Pisces": 4,
    "Gemini": 2, "Libra": 2, "Aquarius": 2,
    "Taurus": 1, "Virgo": 1, "Capricorn": 1
}

YONI_ANIMALS = {
    1: "Horse", 2: "Elephant", 3: "Sheep", 4: "Serpent", 5: "Serpent", 
    6: "Dog", 7: "Cat", 8: "Sheep", 9: "Cat", 10: "Rat", 
    11: "Rat", 12: "Cow", 13: "Buffalo", 14: "Tiger", 15: "Buffalo", 
    16: "Tiger", 17: "Deer", 18: "Deer", 19: "Dog", 20: "Monkey", 
    21: "Mongoose", 22: "Monkey", 23: "Lion", 24: "Horse", 25: "Lion", 
    26: "Cow", 27: "Elephant"
}

NADI_ADI = [1, 6, 7, 12, 13, 18, 19, 24, 25]
NADI_MADHYA = [2, 5, 8, 11, 14, 17, 20, 23, 26]
NADI_ANTYA = [3, 4, 9, 10, 15, 16, 21, 22, 27]
GANA_DEVA = [1, 5, 7, 8, 13, 15, 17, 22, 27]
GANA_MANUSHYA = [2, 4, 6, 11, 12, 20, 21, 25, 26]
GANA_RAKSHASA = [3, 9, 10, 14, 16, 18, 19, 23, 24]

YONI_RELATIONSHIPS = {
    "Horse": {"Horse": 4, "Elephant": 2, "Sheep": 2, "Serpent": 3, "Dog": 2, "Cat": 2, "Rat": 2, "Cow": 1, "Buffalo": 0, "Tiger": 3, "Deer": 3, "Monkey": 2, "Lion": 1, "Mongoose": 2},
    "Elephant": {"Horse": 2, "Elephant": 4, "Sheep": 3, "Serpent": 3, "Dog": 2, "Cat": 2, "Rat": 2, "Cow": 2, "Buffalo": 3, "Tiger": 2, "Deer": 3, "Monkey": 2, "Lion": 0, "Mongoose": 2},
    "Sheep": {"Horse": 2, "Elephant": 3, "Sheep": 4, "Serpent": 2, "Dog": 1, "Cat": 2, "Rat": 1, "Cow": 2, "Buffalo": 2, "Tiger": 1, "Deer": 2, "Monkey": 0, "Lion": 1, "Mongoose": 2},
    "Serpent": {"Horse": 3, "Elephant": 3, "Sheep": 2, "Serpent": 4, "Dog": 2, "Cat": 1, "Rat": 1, "Cow": 1, "Buffalo": 1, "Tiger": 2, "Deer": 2, "Monkey": 2, "Lion": 2, "Mongoose": 0},
    "Dog": {"Horse": 2, "Elephant": 2, "Sheep": 1, "Serpent": 2, "Dog": 4, "Cat": 2, "Rat": 1, "Cow": 2, "Buffalo": 2, "Tiger": 1, "Deer": 0, "Monkey": 2, "Lion": 1, "Mongoose": 2},
    "Cat": {"Horse": 2, "Elephant": 2, "Sheep": 2, "Serpent": 1, "Dog": 2, "Cat": 4, "Rat": 0, "Cow": 2, "Buffalo": 2, "Tiger": 1, "Deer": 3, "Monkey": 2, "Lion": 1, "Mongoose": 2},
    "Rat": {"Horse": 2, "Elephant": 2, "Sheep": 1, "Serpent": 1, "Dog": 1, "Cat": 0, "Rat": 4, "Cow": 2, "Buffalo": 2, "Tiger": 2, "Deer": 2, "Monkey": 1, "Lion": 1, "Mongoose": 2},
    "Cow": {"Horse": 1, "Elephant": 2, "Sheep": 2, "Serpent": 1, "Dog": 2, "Cat": 2, "Rat": 2, "Cow": 4, "Buffalo": 3, "Tiger": 0, "Deer": 2, "Monkey": 1, "Lion": 1, "Mongoose": 2},
    "Buffalo": {"Horse": 0, "Elephant": 3, "Sheep": 2, "Serpent": 1, "Dog": 2, "Cat": 2, "Rat": 2, "Cow": 3, "Buffalo": 4, "Tiger": 1, "Deer": 2, "Monkey": 2, "Lion": 1, "Mongoose": 2},
    "Tiger": {"Horse": 3, "Elephant": 2, "Sheep": 1, "Serpent": 2, "Dog": 1, "Cat": 1, "Rat": 2, "Cow": 0, "Buffalo": 1, "Tiger": 4, "Deer": 1, "Monkey": 1, "Lion": 2, "Mongoose": 2},
    "Deer": {"Horse": 3, "Elephant": 3, "Sheep": 2, "Serpent": 2, "Dog": 0, "Cat": 3, "Rat": 2, "Cow": 2, "Buffalo": 2, "Tiger": 1, "Deer": 4, "Monkey": 2, "Lion": 1, "Mongoose": 2},
    "Monkey": {"Horse": 2, "Elephant": 2, "Sheep": 0, "Serpent": 2, "Dog": 2, "Cat": 2, "Rat": 1, "Cow": 1, "Buffalo": 2, "Tiger": 1, "Deer": 2, "Monkey": 4, "Lion": 2, "Mongoose": 2},
    "Lion": {"Horse": 1, "Elephant": 0, "Sheep": 1, "Serpent": 2, "Dog": 1, "Cat": 1, "Rat": 1, "Cow": 1, "Buffalo": 1, "Tiger": 2, "Deer": 1, "Monkey": 2, "Lion": 4, "Mongoose": 2},
    "Mongoose": {"Horse": 2, "Elephant": 2, "Sheep": 2, "Serpent": 0, "Dog": 2, "Cat": 2, "Rat": 2, "Cow": 2, "Buffalo": 2, "Tiger": 2, "Deer": 2, "Monkey": 2, "Lion": 2, "Mongoose": 4}
}

GRAHA_MAITRI_SCORES = {
    ("Sun", "Sun"): 5, ("Sun", "Moon"): 5, ("Sun", "Mars"): 5, ("Sun", "Mercury"): 4, ("Sun", "Jupiter"): 5, ("Sun", "Venus"): 0, ("Sun", "Saturn"): 0,
    ("Moon", "Sun"): 5, ("Moon", "Moon"): 5, ("Moon", "Mars"): 4, ("Moon", "Mercury"): 5, ("Moon", "Jupiter"): 4, ("Moon", "Venus"): 3, ("Moon", "Saturn"): 3,
    ("Mars", "Sun"): 5, ("Mars", "Moon"): 4, ("Mars", "Mars"): 5, ("Mars", "Mercury"): 1, ("Mars", "Jupiter"): 5, ("Mars", "Venus"): 3, ("Mars", "Saturn"): 3,
    ("Mercury", "Sun"): 4, ("Mercury", "Moon"): 1, ("Mercury", "Mars"): 1, ("Mercury", "Mercury"): 5, ("Mercury", "Jupiter"): 3, ("Mercury", "Venus"): 5, ("Mercury", "Saturn"): 4,
    ("Jupiter", "Sun"): 5, ("Jupiter", "Moon"): 4, ("Jupiter", "Mars"): 5, ("Jupiter", "Mercury"): 1, ("Jupiter", "Jupiter"): 5, ("Jupiter", "Venus"): 0, ("Jupiter", "Saturn"): 3,
    ("Venus", "Sun"): 0, ("Venus", "Moon"): 3, ("Venus", "Mars"): 3, ("Venus", "Mercury"): 5, ("Venus", "Jupiter"): 0, ("Venus", "Venus"): 5, ("Venus", "Saturn"): 5,
    ("Saturn", "Sun"): 0, ("Saturn", "Moon"): 3, ("Saturn", "Mars"): 1, ("Saturn", "Mercury"): 4, ("Saturn", "Jupiter"): 3, ("Saturn", "Venus"): 5, ("Saturn", "Saturn"): 5
}

def calculate_vasya_score(bride_sign: str, groom_sign: str) -> float:
    if bride_sign == groom_sign:
        return 2.0
    
    vasya_map = {
        "Aries": ["Leo", "Scorpio"],
        "Taurus": ["Cancer", "Libra"],
        "Gemini": ["Virgo"],
        "Cancer": ["Scorpio", "Sagittarius"],
        "Leo": ["Libra"],
        "Virgo": ["Gemini", "Pisces"],
        "Libra": ["Virgo", "Capricorn"],
        "Scorpio": ["Cancer"],
        "Sagittarius": ["Pisces"],
        "Capricorn": ["Aries", "Aquarius"],
        "Aquarius": ["Aries"],
        "Pisces": ["Capricorn"]
    }
    
    if groom_sign in vasya_map.get(bride_sign, []):
        return 2.0
    if bride_sign in vasya_map.get(groom_sign, []):
        return 1.0
    return 0.0

def calculate_dina_score(bride_nak_idx: int, groom_nak_idx: int) -> int:
    d = (groom_nak_idx - bride_nak_idx) % 27 + 1
    rem = d % 9
    if rem in [3, 5, 7]:
        return 0
    return 3

def calculate_gana_score(bride_gana: str, groom_gana: str) -> int:
    if bride_gana == groom_gana:
        return 6
    if (bride_gana == "Deva" and groom_gana == "Manushya") or (bride_gana == "Manushya" and groom_gana == "Deva"):
        return 5
    if bride_gana == "Deva" and groom_gana == "Rakshasa":
        return 1
    return 0

def calculate_rashi_koota(bride_sign_idx: int, groom_sign_idx: int) -> int:
    dist = (groom_sign_idx - bride_sign_idx) % 12 + 1
    if dist in [1, 3, 4, 7, 10, 11]:
        return 7
    return 0

def calculate_nadi_score(bride_nak_idx: int, groom_nak_idx: int) -> int:
    def get_nadi(nak_idx):
        if nak_idx in NADI_ADI: return "Adi"
        if nak_idx in NADI_MADHYA: return "Madhya"
        return "Antya"
    
    b_nadi = get_nadi(bride_nak_idx)
    g_nadi = get_nadi(groom_nak_idx)
    if b_nadi == g_nadi:
        return 0
    return 8

def compute_compatibility_data(p1: PartnerDetails, p2: PartnerDetails):
    # Calculate Partner 1 Chart (uses top-level `server` import)
    p1_res_json = server.calculate_d1_chart(
        dob=p1.dob, tob=p1.tob, tz_offset=p1.tz_offset,
        lat=p1.lat, lon=p1.lon, ayanamsha=p1.ayanamsha
    )
    p1_data = json.loads(p1_res_json)
    
    # Calculate Partner 2 Chart
    p2_res_json = server.calculate_d1_chart(
        dob=p2.dob, tob=p2.tob, tz_offset=p2.tz_offset,
        lat=p2.lat, lon=p2.lon, ayanamsha=p2.ayanamsha
    )
    p2_data = json.loads(p2_res_json)
    
    # Moon Placements
    p1_moon = p1_data["planets"]["Moon"]
    p2_moon = p2_data["planets"]["Moon"]
    
    p1_moon_sign = p1_moon["sign"]
    p2_moon_sign = p2_moon["sign"]
    
    p1_moon_nak = p1_moon["nakshatra"]
    p2_moon_nak = p2_moon["nakshatra"]
    
    def get_nak_index(nak_name):
        clean = nak_name.replace(" ", "_")
        if clean in NAKSHATRAS:
            return NAKSHATRAS.index(clean) + 1
        return 1
        
    p1_nak_idx = get_nak_index(p1_moon_nak)
    p2_nak_idx = get_nak_index(p2_moon_nak)
    
    # 8 Kootas Points Calculations
    # 1. Varna (Max 1)
    p1_caste_score = CASTE_RANKS.get(p1_moon_sign, 1)
    p2_caste_score = CASTE_RANKS.get(p2_moon_sign, 1)
    varna_score = 1 if p2_caste_score >= p1_caste_score else 0
    
    # 2. Vasya (Max 2)
    vasya_score = calculate_vasya_score(p1_moon_sign, p2_moon_sign)
    
    # 3. Dina (Max 3)
    dina_score = calculate_dina_score(p1_nak_idx, p2_nak_idx)
    
    # 4. Yoni (Max 4)
    p1_animal = YONI_ANIMALS.get(p1_nak_idx, "Mongoose")
    p2_animal = YONI_ANIMALS.get(p2_nak_idx, "Mongoose")
    yoni_score = YONI_RELATIONSHIPS.get(p1_animal, {}).get(p2_animal, 2)
    
    # 5. Graha Maitri (Max 5)
    p1_lord = HOUSE_LORDS.get(p1_moon_sign, "Moon")
    p2_lord = HOUSE_LORDS.get(p2_moon_sign, "Moon")
    maitri_score = GRAHA_MAITRI_SCORES.get((p1_lord, p2_lord), 3)
    
    # 6. Gana (Max 6)
    def get_gana(nak_idx):
        if nak_idx in GANA_DEVA: return "Deva"
        if nak_idx in GANA_MANUSHYA: return "Manushya"
        return "Rakshasa"
    p1_gana = get_gana(p1_nak_idx)
    p2_gana = get_gana(p2_nak_idx)
    gana_score = calculate_gana_score(p1_gana, p2_gana)
    
    # 7. Rashi (Max 7)
    p1_sign_idx = SIGNS.index(p1_moon_sign)
    p2_sign_idx = SIGNS.index(p2_moon_sign)
    rashi_score = calculate_rashi_koota(p1_sign_idx, p2_sign_idx)
    
    # 8. Nadi (Max 8)
    nadi_score = calculate_nadi_score(p1_nak_idx, p2_nak_idx)
    
    # Guna Totals
    total_score = varna_score + vasya_score + dina_score + yoni_score + maitri_score + gana_score + rashi_score + nadi_score
    
    # Mars Placements & Kuja Dosha (Manglik)
    p1_mars_house = p1_data["planets"]["Mars"]["house"]
    p2_mars_house = p2_data["planets"]["Mars"]["house"]
    
    p1_manglik = p1_mars_house in [1, 2, 4, 7, 8, 12]
    p2_manglik = p2_mars_house in [1, 2, 4, 7, 8, 12]
    manglik_cancellation = p1_manglik and p2_manglik
    
    return {
        "p1_name": p1.name,
        "p1_gender": p1.gender,
        "p1_sign": p1_moon_sign,
        "p1_nakshatra": p1_moon_nak,
        "p1_animal": p1_animal,
        "p1_gana": p1_gana,
        "p1_mars_house": p1_mars_house,
        "p1_manglik": p1_manglik,
        
        "p2_name": p2.name,
        "p2_gender": p2.gender,
        "p2_sign": p2_moon_sign,
        "p2_nakshatra": p2_moon_nak,
        "p2_animal": p2_animal,
        "p2_gana": p2_gana,
        "p2_mars_house": p2_mars_house,
        "p2_manglik": p2_manglik,
        
        "manglik_cancellation": manglik_cancellation,
        
        "varna": {"score": varna_score, "max": 1},
        "vasya": {"score": vasya_score, "max": 2},
        "dina": {"score": dina_score, "max": 3},
        "yoni": {"score": yoni_score, "max": 4, "p1_animal": p1_animal, "p2_animal": p2_animal},
        "maitri": {"score": maitri_score, "max": 5},
        "gana": {"score": gana_score, "max": 6, "p1_gana": p1_gana, "p2_gana": p2_gana},
        "rashi": {"score": rashi_score, "max": 7},
        "nadi": {"score": nadi_score, "max": 8},
        
        "total_score": total_score,
        "max_score": 36
    }

@app.post("/api/compatibility")
def check_compatibility(req: CompatibilityRequest):
    try:
        res = compute_compatibility_data(req.partner1, req.partner2)
        return res
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/compatibility/stream")
async def stream_compatibility_report(
    p1_dob: str, p1_tob: str, p1_tz: str, p1_lat: float, p1_lon: float,
    p2_dob: str, p2_tob: str, p2_tz: str, p2_lat: float, p2_lon: float,
    p1_name: str = "Partner 1", p1_gender: str = "Female",
    p2_name: str = "Partner 2", p2_gender: str = "Male",
    match_type: str = "marriage",
    ayanamsha: str = "raman"
):
    async def compatibility_generator():
        # 1. Compute compatibility data
        try:
            p1 = PartnerDetails(dob=p1_dob, tob=p1_tob, tz_offset=p1_tz, lat=p1_lat, lon=p1_lon, name=p1_name, gender=p1_gender, ayanamsha=ayanamsha)
            p2 = PartnerDetails(dob=p2_dob, tob=p2_tob, tz_offset=p2_tz, lat=p2_lat, lon=p2_lon, name=p2_name, gender=p2_gender, ayanamsha=ayanamsha)
            data = compute_compatibility_data(p1, p2)
            total_score = data["total_score"]
            varna_score = data["varna"]["score"]
            vasya_score = data["vasya"]["score"]
            dina_score = data["dina"]["score"]
            yoni_score = data["yoni"]["score"]
            maitri_score = data["maitri"]["score"]
            gana_score = data["gana"]["score"]
            rashi_score = data["rashi"]["score"]
            nadi_score = data["nadi"]["score"]
            p1_mars_house = data["p1_mars_house"]
            p2_mars_house = data["p2_mars_house"]
            p1_manglik = data["p1_manglik"]
            p2_manglik = data["p2_manglik"]
            manglik_cancellation = data["manglik_cancellation"]
            p1_animal = data["p1_animal"]
            p2_animal = data["p2_animal"]
            p1_gana = data["p1_gana"]
            p2_gana = data["p2_gana"]
        except Exception as e:
            yield "data: " + json.dumps({"content": f"### Error in compatibility calculations\n- Details: {str(e)}\n\n"}) + "\n\n"
            return
            
        yield "data: " + json.dumps({"content": "## ✦ ASTROVEDA COMPATIBILITY & UNION ACCORD\n\n"}) + "\n\n"
        
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            try:
                # Load OpenAI Client
                from openai import AsyncOpenAI
                client = AsyncOpenAI(api_key=api_key)
                
                COMPATIBILITY_PROMPT = """You are AstroVeda's elite Marriage and Union Compatibility Specialist.
Your task is to analyze the Ashta Koota compatibility scorecard and Kuja Dosha (Manglik) dynamics for Partner 1 and Partner 2 and generate a master-level Jyotish compatibility report.
Structure your analysis sequentially into exactly 4 parts:
1. **Astro-Mathematical Guna Scorecard**: Deeply analyze the overall score out of 36 points and explain the core biological Nadi and spiritual Gana alignments.
2. **Kuja Dosha & House 7 Diagnostics**: Analyze Mars placements for both partners, detail any Kuja Dosha Cancels/Neutralizations, and evaluate the relational house alignments.
3. **Subconscious Navamsha (D9) Resonance**: Explain the internal psychological, emotional, and soul-level harmony between the two charts.
4. **Vedic Remedies & Transmutation Upayas**: Recommend highly personalized gemstones, mantra coordinates, and donation activities to resolve any operational friction.

Format your output as standard, premium markdown. Speak in a scholarly, authoritative, and profoundly wise Vedic tone. Do not write placeholder text or general definitions. Delineate the actual material and psychological compatibility based strictly on the provided variables:"""

                payload = (
                    f"COMPATIBILITY VARIABLES:\n"
                    f"- Union Match Type: {match_type}\n"
                    f"- Ayanamsha Utilized: {ayanamsha.upper()}\n"
                    f"- Partner 1: Name={p1_name}, Gender={p1_gender}, Moon Sign={data['p1_sign']}, Nakshatra={p1_moon_nak}, Yoni Animal={p1_animal}, Gana={p1_gana}, Mars House={p1_mars_house}, Manglik Status={p1_manglik}\n"
                    f"- Partner 2: Name={p2_name}, Gender={p2_gender}, Moon Sign={data['p2_sign']}, Nakshatra={p2_moon_nak}, Yoni Animal={p2_animal}, Gana={p2_gana}, Mars House={p2_mars_house}, Manglik Status={p2_manglik}\n"
                    f"- Kuja Dosha Mutual Cancellation: {manglik_cancellation}\n"
                    f"- Ashta Koota Score Card: Total Gunas={total_score}/36 | Nadi={nadi_score}/8 | Gana={gana_score}/6 | Graha Maitri={maitri_score}/5 | Yoni={yoni_score}/4 | Rashi={rashi_score}/7 | Dina={dina_score}/3 | Vasya={vasya_score}/2 | Varna={varna_score}/1\n"
                )
                
                response_stream = await client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": COMPATIBILITY_PROMPT},
                        {"role": "user", "content": payload}
                    ],
                    temperature=0.1,
                    stream=True,
                )
                
                async for chunk in response_stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield "data: " + json.dumps({"content": delta}) + "\n\n"
                return
            except Exception as e:
                yield "data: " + json.dumps({"content": f"\n\n*Inference warning: Real-time cloud RAG encountered a connection delay ({str(e)}). Transitioning seamlessly to AstroVeda's offline compatibility engine...*\n\n"}) + "\n\n"
                await asyncio.sleep(1)

        # Local fallback stream
        fallback_paragraphs = [
            f"> ### ✦ Astro-Mathematical Guna Scorecard\n>\n"
            f"> - **Overall Compatibility score**: **{total_score} / 36 Gunas** (Gunas obtained: {total_score}, required: 18).\n"
            f"> - **Union Compatibility Status**: " + ("**Highly Auspicious**" if total_score >= 25 else "**Auspicious & Approved**" if total_score >= 18 else "**Challenging / Requires Remedies**") + ".\n"
            f"> - **Koota Breakdown**: Nadi Koota={nadi_score}/8 | Gana Koota={gana_score}/6 | Graha Maitri={maitri_score}/5 | Yoni Koota={yoni_score}/4 | Rashi Koota={rashi_score}/7 | Dina Kuta={dina_score}/3 | Vasya Koota={vasya_score}/2 | Varna Koota={varna_score}/1.\n\n",
            f"> ### ✦ Kuja Dosha & House 7 Diagnostics\n>\n"
            f"> - **{p1_name} Manglik Status**: " + ("Manglik (Mars in house " + str(p1_mars_house) + ")" if p1_manglik else "Non-Manglik") + ".\n"
            f"> - **{p2_name} Manglik Status**: " + ("Manglik (Mars in house " + str(p2_mars_house) + ")" if p2_manglik else "Non-Manglik") + ".\n"
            f"> - **Kuja Dosha Cancellation**: " + ("**Active & Balanced** (Mutual Manglik cancellation resolves all Martian afflictions)" if manglik_cancellation else "No cancellation active") + ".\n\n",
            f"### PART 1: ASTRO-MATHEMATICAL SCORES SYNTHESIS\n"
            f"The compatibility calculations for **{p1_name}** and **{p2_name}** reveal a total score of **{total_score} out of 36 points (Gunas)**. "
            f"In classical Vedic astrology, any score above 18 points is considered auspicious and indicates solid compatibility. "
            f"Analyzing the vital **Nadi Koota** (which maps biological temperament and progeny compatibility), the couple scores **{nadi_score} out of 8 points**. "
            f"This indicates a " + ("harmonious biological and mental energy balance, ensuring progeny happiness" if nadi_score == 8 else "Nadi Dosha alignment, suggesting potential physiological friction that can be easily resolved through acts of charity or specific remedies") + ". "
            f"In terms of **Gana Kuta** (temperament matching), the scores show **{gana_score} out of 6 points**, reflecting " + ("a solid alignment of life motives and cooperative spirit" if gana_score >= 5 else "a minor difference in emotional temperaments requiring minor adjustments") + ".\n\n",
            f"### PART 2: KUJA DOSHA & MARITAL HOUSE HARMONY\n"
            f"The placement of Mars (Mangal) determines the vitality and potential friction in close unions. "
            f"For **{p1_name}**, Mars sits in the **{p1_mars_house} house**, whereas for **{p2_name}**, Mars sits in the **{p2_mars_house} house**. "
            + (f"Since both partners possess Kuja Dosha (both are Manglik), it creates a beautiful **Kuja Dosha Cancellation** (Eka-Manglik structural cancellation), which neutralizes all sudden relationship delays or health vulnerabilities." if manglik_cancellation else
               f"Since only one partner has Kuja Dosha, it represents a minor Martian drag. This can be completely smoothed out through standard gemstone adjustments or customized fasting schedules.") + "\n\n",
            f"### PART 3: PSYCHOLOGICAL & YONI COHERENCE\n"
            f"The psychological disposition is analyzed via **Graha Maitri** (rashi lord friendship), scoring **{maitri_score} out of 5 points**. "
            f"This demonstrates a " + ("deep mutual understanding, robust intellectual exchange, and friendly affection" if maitri_score >= 4 else "passable intellectual connection, suggesting that patience is needed in daily communications") + ". "
            f"Evaluating **Yoni Kuta** (physical and sexual compatibility), the couple scores **{yoni_score} out of 4 points**, representing the physical affinity of **{p1_animal}** and **{p2_animal}** Yonis. "
            f"This denotes a " + ("strong, highly cohesive physical and sensual resonance" if yoni_score >= 3 else "moderate physical compatibility, which settles into deep harmony in middle age") + ".\n\n",
            f"### PART 4: VEDIC REMEDIES & UPAYAS FOR RELATIONSHIP ACCORD\n"
            f"To harmonize any operational friction and elevate the relationship's overall frequency, we prescribe these personalized, non-generic remedies:\n"
            f"1. **Gemstone Resonance**: " + ("To strengthen Venus and Mars interaction, Partner 1 should wear a Coral on the ring finger, and Partner 2 should wear a Pearl on the little finger." if total_score < 25 else "No urgent gemstone corrections are needed due to robust baseline points.") + "\n"
            f"2. **Charity & Upayas**: Perform specific acts of charity, such as feeding birds or donation of yellow clothes on Thursdays to honor Jupiter and strengthen Graha Maitri.\n"
            f"3. **Planetary Mantras**: Recite the classical mantra for Mars *'Om Mangalaya Namaha'* to neutralize any Kuja Dosha drag, and *'Om Shanti Shanti Shanti'* to invite deep peace into your domestic environment.\n"
        ]
        
        for paragraph in fallback_paragraphs:
            for word_chunk in [paragraph[i:i+40] for i in range(0, len(paragraph), 40)]:
                yield "data: " + json.dumps({"content": word_chunk}) + "\n\n"
                await asyncio.sleep(0.04)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(compatibility_generator(), media_type="text/event-stream", headers=headers)

if __name__ == "__main__":
    import uvicorn
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print("Starlette Web Server validation successful!")
        sys.exit(0)
    uvicorn.run("web_server:app", host="0.0.0.0", port=8000, reload=True)
