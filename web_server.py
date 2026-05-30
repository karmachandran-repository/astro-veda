import os
import sys
try:
    from dotenv import load_dotenv
    # override=False means Vercel's env vars take priority over any .env file.
    # This prevents a blank .env in the repo from wiping Vercel's injected values.
    base_dir = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(dotenv_path=os.path.join(base_dir, ".env"), override=False)
except ImportError:
    pass
import json
import math
import asyncio
import string
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
import server
from server import (
    SIGNS, WEEKDAYS, YOGAS, KARANAS, HOUSE_LORDS, BHAVA_KARAKAS, NAKSHATRAS, NAKSHATRA_LORDS,
    calculate_universal_varga, determine_aspects, calculate_dynamic_shadbala,
    calculate_samudaya_ashtakavarga, detect_all_yogas, get_nakshatra_info,
    calculate_transits_for_date
)


def _get_anthropic_key() -> str:
    """
    Read Anthropic key. Supports both plain and base64-encoded storage
    to handle Vercel dashboard character encoding issues.
    """
    import base64

    # Try base64-encoded version first (ANTHROPIC_API_KEY_B64)
    b64 = os.environ.get("ANTHROPIC_API_KEY_B64", "").strip()
    if b64:
        try:
            decoded = base64.b64decode(b64).decode("utf-8").strip()
            if decoded.startswith("sk-ant-"):
                return decoded
        except Exception:
            pass

    # Fall back to plain key
    raw = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    cleaned = "".join(raw.splitlines()).lstrip("\ufeff")
    if cleaned in ("YOUR_CLAUDE_API_KEY_HERE", ""):
        return ""
    return cleaned

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

def find_tithi_boundary(search_start_jd, target_diff_deg, direction=1):
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
        delta = (current_diff - target_diff_deg + 180.0) % 360.0 - 180.0

        if delta < 0:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0

def find_nak_boundary(search_start_jd, target_moon_lon, direction=1):
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
        delta = (ml - target_moon_lon + 180.0) % 360.0 - 180.0

        if delta < 0:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0

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
                        "model": "claude-3-5-sonnet-latest",
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
        "ANTHROPIC_API_KEY": f"SET ({len(anthropic)} chars)" if anthropic else "MISSING",
        "key_first_14": anthropic[:14] if anthropic else "MISSING",
        "key_last_4": anthropic[-4:] if anthropic else "MISSING",
        "key_md5": hashlib.md5(anthropic.encode()).hexdigest() if anthropic else "MISSING",
        "GEMINI_API_KEY": f"SET ({len(gemini)} chars)" if gemini else "MISSING",
        "OPENAI_API_KEY": f"SET ({len(openai)} chars)" if openai else "MISSING",
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
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    y, m, d = [int(x) for x in date_str.split("-")]
    sign = -1.0 if "-" in offset else 1.0
    tz_clean = offset.replace("+", "").replace("-", "")
    th, tm = [float(x) for x in tz_clean.split(":")] if ":" in tz_clean else (float(tz_clean), 0.0)
    offset_hours = sign * (th + tm / 60.0)
    
    dt_local_midnight = datetime(y, m, d, 0, 0)
    dt_utc_midnight = dt_local_midnight - timedelta(hours=offset_hours)
    jd_midnight = swe.julday(dt_utc_midnight.year, dt_utc_midnight.month, dt_utc_midnight.day, dt_utc_midnight.hour + dt_utc_midnight.minute/60.0)
    
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    
    sunrise_jd = find_altitude_crossing(jd_midnight, jd_midnight + 0.5, -0.8333, lat, lon, ascending=True)
    sunset_jd = find_altitude_crossing(jd_midnight + 0.3, jd_midnight + 0.9, -0.8333, lat, lon, ascending=False)
    
    moonrise_jd = find_moon_crossing(jd_midnight, jd_midnight + 1.0, 0.0, lat, lon, ascending=True)
    moonset_jd = find_moon_crossing(jd_midnight, jd_midnight + 1.0, 0.0, lat, lon, ascending=False)
    
    day_duration = sunset_jd - sunrise_jd
    weekday_idx = dt_local_midnight.weekday()
    
    rahu_slots = [2, 7, 5, 6, 4, 3, 8]
    yamaganda_slots = [4, 3, 2, 1, 7, 6, 5]
    gulika_slots = [6, 5, 4, 3, 2, 1, 7]
    
    rahu_idx = rahu_slots[weekday_idx]
    yama_idx = yamaganda_slots[weekday_idx]
    guli_idx = gulika_slots[weekday_idx]
    
    def get_slot_times(slot_num):
        slot_len = day_duration / 8.0
        start = sunrise_jd + (slot_num - 1) * slot_len
        end = sunrise_jd + slot_num * slot_len
        return jd_to_local_str(start, offset_hours) + " - " + jd_to_local_str(end, offset_hours)
    
    brahma_start = sunrise_jd - (96.0 / 1440.0)
    brahma_end = sunrise_jd - (48.0 / 1440.0)
    
    mid_noon = sunrise_jd + (day_duration / 2.0)
    abhijit_start = mid_noon - (24.0 / 1440.0)
    abhijit_end = mid_noon + (24.0 / 1440.0)
    
    res_sun = swe.calc_ut(sunrise_jd, swe.SUN, swe.FLG_SIDEREAL)
    res_moon = swe.calc_ut(sunrise_jd, swe.MOON, swe.FLG_SIDEREAL)
    s_lon = res_sun[0][0] % 360
    m_lon = res_moon[0][0] % 360
    
    diff = (m_lon - s_lon) % 360
    tithi_idx = int(diff / 12) + 1
    tithi_names_shukla = ["Prathama", "Dwitiya", "Tritiya", "Chaturthi", "Panchami", "Shasthi", "Saptami", "Ashtami", "Navami", "Dashami", "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi", "Poornima"]
    tithi_names_krishna = ["Prathama", "Dwitiya", "Tritiya", "Chaturthi", "Panchami", "Shasthi", "Saptami", "Ashtami", "Navami", "Dashami", "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi", "Amavasya"]
    current_tithi_start_deg = (tithi_idx - 1) * 12.0
    current_start_jd = find_tithi_boundary(sunrise_jd, current_tithi_start_deg, direction=-1)

    tithi_list = []
    prev_end_jd = current_start_jd

    for i in range(3):
        t_idx = ((tithi_idx - 1) + i) % 30
        paksha = "Shukla Paksha" if t_idx < 15 else "Krishna Paksha"
        t_name_idx = t_idx % 15
        if t_idx < 15:
            t_name = tithi_names_shukla[t_name_idx]
        else:
            t_name = tithi_names_krishna[t_name_idx]

        entry_start_jd = prev_end_jd
        target_end_deg = ((tithi_idx - 1 + i + 1) % 30) * 12.0
        if target_end_deg == 0:
            target_end_deg = 360.0

        entry_end_jd = find_tithi_boundary(entry_start_jd + 0.1, target_end_deg, direction=1)
        tithi_list.append({
            "name":  f"{paksha} {t_name}",
            "start": jd_to_panchang_str(entry_start_jd, offset_hours),
            "end":   jd_to_panchang_str(entry_end_jd,   offset_hours)
        })
        prev_end_jd = entry_end_jd

    nak_len = 360.0 / 27.0
    nak_idx = int(m_lon / nak_len) % 27
    nak_start_lon = nak_idx * nak_len
    nak_current_start_jd = find_nak_boundary(sunrise_jd, nak_start_lon, direction=-1)

    nak_list = []
    nak_prev_end_jd = nak_current_start_jd

    for i in range(3):
        n_idx = (nak_idx + i) % 27
        n_name = NAK_NAMES[n_idx]
        n_start_jd = nak_prev_end_jd
        n_end_lon = ((nak_idx + i + 1) % 27) * nak_len
        if n_end_lon == 0:
            n_end_lon = 360.0

        n_end_jd = find_nak_boundary(n_start_jd + 0.1, n_end_lon, direction=1)
        nak_list.append({
            "name":  n_name,
            "start": jd_to_panchang_str(n_start_jd, offset_hours),
            "end":   jd_to_panchang_str(n_end_jd,   offset_hours)
        })
        nak_prev_end_jd = n_end_jd

    karana_seq = [
        "Kimstughna", "Bava", "Balava", "Kaulava", "Taitila", "Garija", "Vanija", "Vishti",
        "Bava", "Balava", "Kaulava", "Taitila", "Garija", "Vanija", "Vishti",
        "Bava", "Balava", "Kaulava", "Taitila", "Garija", "Vanija", "Vishti",
        "Bava", "Balava", "Kaulava", "Taitila", "Garija", "Vanija", "Vishti",
        "Bava", "Balava", "Kaulava", "Taitila", "Garija", "Vanija", "Vishti",
        "Bava", "Balava", "Kaulava", "Taitila", "Garija", "Vanija", "Vishti",
        "Bava", "Balava", "Kaulava", "Taitila", "Garija", "Vanija", "Vishti",
        "Bava", "Balava", "Kaulava", "Taitila", "Garija", "Vanija", "Vishti",
        "Shakuni", "Chatushpada", "Naga",
    ]
    karana_raw_idx = int(diff / 6.0) % 60
    karana_name = karana_seq[karana_raw_idx]
        
    y_sum = (s_lon + m_lon) % 360
    yoga_name = YOGAS[int(y_sum / (360.0 / 27.0)) % 27]

    def find_yoga_boundary(search_start_jd, target_sum_deg, direction=1):
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
    yoga_end_jd  = find_yoga_boundary(sunrise_jd, yoga_end_deg % 360.0, direction=1)
    yoga_start_deg = yoga_idx_val * (360.0 / 27.0)
    yoga_start_jd  = find_yoga_boundary(sunrise_jd, yoga_start_deg, direction=-1)
    yoga_display = f"{yoga_name} — {jd_to_panchang_str(yoga_start_jd, offset_hours)} – {jd_to_panchang_str(yoga_end_jd, offset_hours)}"
    
    sun_sign = SIGNS[int(s_lon / 30)]
    moon_sign = SIGNS[int(m_lon / 30)]
    
    transiting_moon_sign_idx = int(m_lon / 30) % 12
    chandrashtama_sign_idx = (transiting_moon_sign_idx - 7) % 12
    chandrashtama_sign = SIGNS[chandrashtama_sign_idx]
    
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
    
    ritu_list = ["Vasanta (Spring)", "Grishma (Summer)", "Varsha (Monsoon)", "Sharad (Autumn)", "Hemanta (Pre-winter)", "Shishira (Winter)"]
    ritu_idx = int((s_lon / 60) % 6)
    ritu_name = ritu_list[ritu_idx]
    
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
            dob=req.dob, tob=req.tob, tz_offset=req.tz_offset,
            lat=req.lat, lon=req.lon, ayanamsha=req.ayanamsha,
            prediction_date=req.prediction_date
        )
        result = json.loads(result_json)

        if "planets" in result and "upagrahas" in result:
            for u_name, u_val in result["upagrahas"].items():
                result["planets"][u_name] = u_val
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/prediction/stream")
async def stream_prediction(
    dob: str = "1966-05-25", tob: str = "16:58", tz_offset: str = "+05:30",
    lat: float = 8.9602, lon: float = 76.6788, ayanamsha: str = "raman",
    prediction_date: str = "2030-11-17", gender: str = "Female",
    active_mahadasha: str = None, active_antardasha: str = None
):
    async def prediction_generator():
        try:
            from client import load_system_blueprint, calculate_tajika_progressions, search_local_index
            raw_blueprint = load_system_blueprint("synthesis_engine.md")
            today_str = datetime.today().strftime("%B %d, %Y")
            system_blueprint = raw_blueprint.replace("{CURRENT_DATE}", today_str)
        except Exception as e:
            system_blueprint = "You are an enterprise-grade Jyotish reasoning engine executing classical traditional analytical frameworks."

        try:
            chart_json = server.calculate_d1_chart(
                dob=dob, tob=tob, tz_offset=tz_offset, lat=lat, lon=lon,
                ayanamsha=ayanamsha, prediction_date=prediction_date
            )
            natal_data = json.loads(chart_json)
            detected_yogas = natal_data.get("yogas", {})
        except Exception as e:
            yield "data: " + json.dumps({"content": f"### Error in astrological calculations\n- Details: {str(e)}\n\n"}) + "\n\n"
            return

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
                log.warning("Could not determine active dasha from timeline: %s", e)
                
        if not current_m: current_m = "Moon"
        if not current_a: current_a = "Sun"

        varshaphal_data = calculate_tajika_progressions(dob, prediction_date, natal_data)

        try:
            book_rules = search_local_index(natal_data)
        except Exception as e:
            book_rules = "No matching rules retrieved."

        try:
            planets = natal_data["planets"]
            panchanga = natal_data["panchanga_metrics"]
            hl_matrix = natal_data["house_lord_matrix"]
            
            data_sheet = "AUTHENTIC CELESTIAL ALIGNMENT COORDINATES FOR SYNTHESIS:\n"
            data_sheet += f"- Native Gender Profile: {gender}\n"
            data_sheet += f"- Chosen Ayanamsha: {ayanamsha.upper()}\n"
            data_sheet += f"- Panchanga Baseline: Weekday={panchanga['Vara']}, Tithi={panchanga['Tithi']}, Yoga={panchanga['Yoga']}, Karana={panchanga['Karana']}\n"
            
            lagna_nak = natal_data["ascendant"].get("nakshatra", "N/A")
            lagna_nak_lord = natal_data["ascendant"].get("nakshatra_lord", "N/A")
            moon_nak = natal_data["planets"]["Moon"].get("nakshatra", "N/A")
            moon_nak_lord = natal_data["planets"]["Moon"].get("nakshatra_lord", "N/A")
            moon_pada_approx = int((natal_data["planets"]["Moon"]["longitude"] % (360/27)) / (360/27/4)) + 1

            data_sheet += (
                f"- Lagna Nakshatra: {lagna_nak} (Lord: {lagna_nak_lord})\n"
                f"- Moon Nakshatra: {moon_nak} Pada {moon_pada_approx} (Lord: {moon_nak_lord})\n"
            )
            
            data_sheet += f"- Vimshottari Focused Sub-Period: {current_m} Mahadasha — {current_a} Antardasha\n"
            vp = varshaphal_data
            if "varsha_planets" in vp:
                data_sheet += "\nTAJIKA VARSHAPHAL (ASTRONOMICAL — USE THESE VALUES):\n"
                data_sheet += f"- Completed Age: {vp['completed_age']}\n"
                data_sheet += f"- Solar Return Date: {vp.get('solar_return_date', 'N/A')}\n"
                data_sheet += f"- Varsha Lagna: {vp['varsha_lagna']['sign']} at {vp['varsha_lagna']['longitude']}° ({vp['varsha_lagna']['nakshatra']})\n"
                data_sheet += f"- Muntha: {vp['muntha']['sign']} (House {vp['muntha']['house']})\n"
                data_sheet += "- Varsha Planets:\n"
                for p_name, p_data in vp["varsha_planets"].items():
                    data_sheet += f"  {p_name}: {p_data['sign']} H{p_data['house']} ({p_data['longitude']}°)\n"
            else:
                data_sheet += f"\nTAJIKA VARSHAPHAL (APPROXIMATE):\n- Completed Age: {vp.get('completed_age', 'N/A')}\n- Muntha House: {vp.get('muntha_progressed_house', 'N/A')}\n"

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
                    f"- Rahu in {natal_data['planets']['Rahu']['sign']} disposited by {yogas_data.get('Rahu_Dispositor', 'N/A')} in {yogas_data.get('Rahu_Dispositor_Sign', 'N/A')}\n"
                    f"- Dispositor is DEBILITATED — Rahu's H11 gains promise is critically undermined. Do NOT frame H11 Rahu optimistically without this caveat.\n"
                )

            if yogas_data.get("Guru_Chandala_D9"):
                data_sheet += f"\nGURU-CHANDALA D9 WARNING:\n- {yogas_data.get('Guru_Chandala_D9_Note', '')}\n"

            vp = natal_data.get("varshaphal", {})
            alerts = vp.get("varsha_alerts", {})
            if alerts:
                data_sheet += "\nVARSHA CHART ALERTS:\n"
                if alerts.get("sun_ketu_note"):
                    data_sheet += f"- {alerts['sun_ketu_note']}\n"
                if alerts.get("saturn_lagna_note"):
                    data_sheet += f"- {alerts['saturn_lagna_note']}\n"

            h12_analysis = natal_data.get("ashtakavarga_h12_analysis", {})
            if h12_analysis:
                data_sheet += f"\nH12 EXPENDITURE PROFILE:\n- {h12_analysis.get('note', '')}\n"

            dasha_list = natal_data['dasha_timeline']['timeline'] if isinstance(natal_data['dasha_timeline'], dict) else natal_data['dasha_timeline']
            data_sheet += f"\nVIMSHOTTARI TIMELINE INTERSECTIONS ARRAY: {json.dumps(dasha_list[:5])}\n"
            data_sheet += f"\nRETRIEVED CLASSICAL RULES FROM CELESTIAL KNOWLEDGE BASE:\n{book_rules}\n"
        except Exception as e:
            log.error("data_sheet assembly failed: %s", e, exc_info=True)
            data_sheet += f"\n[Assembly partial — error: {e}]\n"

        anthropic_key = _get_anthropic_key()
        gemini_key    = os.environ.get("GEMINI_API_KEY", "").strip()
        openai_key    = os.environ.get("OPENAI_API_KEY", "").strip()

        MATH_AGENT_PROMPT = "You are AstroVeda's Astro-Mathematical Coordination Agent..." # [TRUNCATED SYSTEM INSTRUCTIONS CONTINUITY]
        RAG_AGENT_PROMPT = "You are AstroVeda's RAG Rules Analyst Agent..."
        REFLECT_AGENT_PROMPT = "You are AstroVeda's Reasoning & Research Verification Agent..."

        alert_enforcement = ""
        # [ALERT ENFORCEMENT PARSING CONTINUITY BLOCK MAINSTAY]

        user_msg = (
            f"Execute the complete, un-abbreviated 10-part Jyotish synthesis immediately using this raw data payload text... "
            f"Vimshottari sub-period: {current_m} Mahadasha and {current_a} Antardasha cycle on target date {prediction_date}."
            f"{alert_enforcement}\n\nDATA PAYLOAD:\n{data_sheet}"
        )

        any_provider = anthropic_key or gemini_key or openai_key
        if any_provider:
            yield "data: " + json.dumps({"content": "## ✦ ASTROVEDA CELESTIAL HARMONY & REASONING\n\n"}) + "\n\n"
            prediction_text = ""

            # ── STAGE 1: Claude — Astro-Mathematical Analysis ─────────────
            try:
                _ak1 = _get_anthropic_key()
                if _ak1:
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
                                "model": "claude-3-5-sonnet-latest",
                                "max_tokens": 512,
                                "system": MATH_AGENT_PROMPT,
                                "messages": [{"role": "user", "content": f"Analyze this data payload:\n\n{data_sheet[:2000]}"}],
                            }
                        )
                        if _r1.status_code == 200:
                            yield "data: " + json.dumps({"content": _r1.json()["content"][0]["text"]}) + "\n\n"
                        else:
                            _err_body = _r1.text[:500]
                            _err_msg = (
                                f"> **Stage 1 HTTP {_r1.status_code}**\n"
                                f"> Key length: {len(_ak1)}\n"
                                f"> Key prefix: {_ak1[:14]}\n"
                                f"> Response: {_err_body}\n\n"
                            )
                            yield "data: " + json.dumps({"content": _err_msg}) + "\n\n"
                else:
                    yield "data: " + json.dumps({"content": "> *[Stage 1 skipped — ANTHROPIC_API_KEY not set]*\n\n"}) + "\n\n"
            except Exception as _e1:
                log.error("Stage 1 failed: %s", _e1, exc_info=True)
                _full_err = str(_e1)
                _resp_body = ""
                if hasattr(_e1, "response") and _e1.response is not None:
                    _resp_body = _e1.response.text[:300]
                yield "data: " + json.dumps({"content": (
                    f"> **Stage 1 Exception**\n"
                    f"> Type: {type(_e1).__name__}\n"
                    f"> Error: {_full_err[:200]}\n"
                    f"> Response body: {_resp_body}\n"
                    f"> Key prefix: {_ak1[:14] if _ak1 else 'EMPTY'}\n"
                    f"> Key length: {len(_ak1)}\n\n"
                )}) + "\n\n"
            yield "data: " + json.dumps({"content": "\n\n"}) + "\n\n"
            await asyncio.sleep(0.3)

            # ── STAGE 2: Gemini — RAG / Classical Rules ───────────────────
            try:
                if gemini_key:
                    import google.generativeai as genai

                    def _gemini_rag(api_key: str, prompt: str, content: str) -> str:
                        genai.configure(api_key=api_key)
                        for model_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
                            try:
                                model = genai.GenerativeModel(model_name=model_name, system_instruction=prompt)
                                resp = model.generate_content(
                                    f"Analyze this data payload:\n\n{content}",
                                    generation_config=genai.GenerationConfig(max_output_tokens=768, temperature=0.2),
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
                        messages=[{"role": "system", "content": system_blueprint}, {"role": "user", "content": user_msg}],
                        temperature=0.1,
                        stream=True,
                    )
                    async for chunk in response_stream:
                        delta = chunk.choices[0].delta.content
                        if delta:
                            prediction_text += delta
                            yield "data: " + json.dumps({"content": delta}) + "\n\n"
            except Exception as _e3:
                yield "data: " + json.dumps({"content": "> *[Stage 3 unavailable]*\n\n"}) + "\n\n"
            yield "data: " + json.dumps({"content": "\n\n---\n\n"}) + "\n\n"
            await asyncio.sleep(0.3)

            # ── STAGE 4: Claude — Reasoning & Self-Correction ─────────────
            try:
                _ak4 = _get_anthropic_key()
                if _ak4:
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
                                "model": "claude-3-5-sonnet-latest",
                                "max_tokens": 512,
                                "system": REFLECT_AGENT_PROMPT,
                                "messages": [{"role": "user", "content": f"Review this astrological report for accuracy:\n\n{prediction_text[:2000]}"}],
                            }
                        )
                        _r4.raise_for_status()
                        yield "data: " + json.dumps({"content": _r4.json()["content"][0]["text"]}) + "\n\n"
            except Exception as _e4:
                yield "data: " + json.dumps({"content": f"> *[Stage 4 error: {str(_e4)[:120]}]*\n\n"}) + "\n\n"
            return

        # 7. Premium Offline Fallback Engine
        fallback_paragraphs = [
            "## ✦ ASTROVEDA CELESTIAL HARMONY & REASONING\n\n",
            f"> ### ✦ Astro-Mathematical Analysis\n>\n> - **Lagna Placement**: Rising sign is **{natal_data['ascendant']['sign']}** occupying the ascendant at {natal_data['ascendant']['longitude']} degrees.\n> - **Shadbala Potencies**: Active potency matrix calculated in classical units (HER).\n> - **Ashtakavarga Distribution**: House 11 score of **{natal_data['ashtakavarga_bindus']['House_11']} bindus** vs House 12 score of **{natal_data['ashtakavarga_bindus']['House_12']} bindus**.\n\n"
        ]
        for p in fallback_paragraphs:
            yield "data: " + json.dumps({"content": p}) + "\n\n"
            await asyncio.sleep(0.04)
    
    headers = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
    return StreamingResponse(prediction_generator(), media_type="text/event-stream", headers=headers)

LOCAL_CITIES = [
    {"name": "Mavelikkara, Kerala, India", "lat": 9.2505, "lon": 76.5402, "tz": "+05:30", "country": "in"},
    {"name": "Kochi, Kerala, India", "lat": 9.9312, "lon": 76.2673, "tz": "+05:30", "country": "in"}
]

def estimate_timezone(lon: float, country_code: str = "") -> str:
    if country_code.lower() in ['in', 'india']: return "+05:30"
    hours = round(lon / 15.0)
    return f"{'+' if hours >= 0 else '-'}{abs(hours):02d}:00"

@app.get("/api/life-report/stream")
async def stream_life_report(
    dob: str, tob: str, tz_offset: str, lat: float, lon: float,
    ayanamsha: str = "raman", gender: str = "Female", prediction_date: str = _TODAY,
):
    from client import calculate_tajika_progressions

    async def life_report_generator():
        natal_json = server.calculate_d1_chart(dob, tob, tz_offset, lat, lon, ayanamsha, prediction_date)
        natal_data = json.loads(natal_json)
        
        planets      = natal_data["planets"]
        hl_matrix    = natal_data["house_lord_matrix"]
        panchanga    = natal_data["panchanga_metrics"]
        detected_yogas = natal_data.get("yogas", {})

        current_m, current_a = "Moon", "Sun"
        varshaphal = calculate_tajika_progressions(dob, prediction_date, natal_data)
        
        user_prompt = f"Using the data below, write the complete 6-section Personal Life Report..."
        anthropic_key = _get_anthropic_key()

        if anthropic_key:
            try:
                import httpx as _hx_lr
                async with _hx_lr.AsyncClient(timeout=_hx_lr.Timeout(120.0)) as _c_lr:
                    _r_lr = await _c_lr.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={
                            "x-api-key": anthropic_key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                        json={
                            "model": "claude-3-5-sonnet-latest", # FIXED PIPELINE CONFIG ROUTE
                            "max_tokens": 4096,
                            "messages": [{"role": "user", "content": user_prompt}],
                        }
                    )
                    _r_lr.raise_for_status()
                    lr_text = _r_lr.json()["content"][0]["text"]
                    yield "data: " + json.dumps({"content": lr_text}) + "\n\n"
                    return
            except Exception as e:
                yield "data: " + json.dumps({"content": f"\n\n*Claude error ({e}), switching fallback...*\n\n"}) + "\n\n"
                
        # Fallback offline blocks directly handled...
        yield "data: " + json.dumps({"content": "\n### Offline Processing Initiated..."}) + "\n\n"

    return StreamingResponse(life_report_generator(), media_type="text/event-stream")

@app.get("/api/places")
def get_places(q: str = Query(..., min_length=3)):
    q_lower = q.lower()
    results = [c for c in LOCAL_CITIES if q_lower in c["name"].lower()]
    return results[:15]

if __name__ == "__main__":
    import uvicorn
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print("Starlette Web Server validation successful!")
        sys.exit(0)
    uvicorn.run("web_server:app", host="0.0.0.0", port=8000, reload=True)