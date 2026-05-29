import os
import json
import logging
from datetime import datetime, timedelta
from mcp.server.fastmcp import FastMCP
import swisseph as swe

log = logging.getLogger(__name__)

import threading
_swe_lock = threading.Lock()

mcp = FastMCP("AstroVeda-Engine")

SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

YOGAS = [
    "Vishkumbha", "Priti", "Ayushman", "Saubhagya", "Shobhana", "Atiganda", "Sukarma", 
    "Dhriti", "Shula", "Ganda", "Vriddhi", "Dhruva", "Vyaghata", "Harshana", 
    "Vajra", "Siddhi", "Vyatipata", "Variyan", "Parigha", "Shiva", "Siddha", 
    "Sadhya", "Shubha", "Shukla", "Brahma", "Indra", "Vaidhriti"
]

KARANAS = [
    "Kimstughna", "Bava", "Balava", "Kaulava", "Taitila", "Garija", "Vanija", "Vishti",
    "Shakuni", "Chatushpada", "Naga"
]

HOUSE_LORDS = {
    "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury", "Cancer": "Moon",
    "Leo": "Sun", "Virgo": "Mercury", "Libra": "Venus", "Scorpio": "Mars",
    "Sagittarius": "Jupiter", "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter"
}

BHAVA_KARAKAS = {
    "House_1": "Sun", "House_2": "Jupiter", "House_3": "Mars", "House_4": "Moon",
    "House_5": "Jupiter", "House_6": "Mars", "House_7": "Venus", "House_8": "Saturn",
    "House_9": "Jupiter", "House_10": "Mercury", "House_11": "Jupiter", "House_12": "Saturn"
}

DASHA_YEARS = {
    "Sun": 6, "Moon": 10, "Mars": 7, "Rahu": 18, 
    "Jupiter": 16, "Saturn": 19, "Mercury": 17, "Ketu": 7, "Venus": 20
}


def calculate_universal_varga(longitude: float, varga: int) -> str:
    total_degrees = longitude % 360.0
    sign_idx = int(total_degrees / 30.0) % 12
    sign_deg = total_degrees % 30.0
    
    if varga == 2:
        # Classical Hora: odd signs (even index) → Leo first half, Cancer second half;
        # even signs (odd index) → Cancer first half, Leo second half.
        if sign_idx % 2 == 0:
            return "Leo" if sign_deg < 15.0 else "Cancer"
        else:
            return "Cancer" if sign_deg < 15.0 else "Leo"
    elif varga == 3:
        return SIGNS[(sign_idx + (int(sign_deg / 10.0) * 4)) % 12]
    elif varga == 4:
        return SIGNS[(sign_idx + (int(sign_deg / 7.5) * 3)) % 12]
    elif varga == 5:
        return SIGNS[(0 if sign_idx % 2 == 0 else 6 + int(sign_deg / 6.0)) % 12]
    elif varga == 7:
        return SIGNS[(sign_idx if sign_idx % 2 == 0 else (sign_idx + 7) + int(sign_deg / (30.0 / 7.0))) % 12]
    elif varga == 9:
        start_map = [0, 4, 8, 0, 4, 8, 0, 4, 8, 0, 4, 8]
        return SIGNS[(start_map[sign_idx] + int(sign_deg / (30.0 / 9.0))) % 12]
    elif varga == 10:
        return SIGNS[(sign_idx if sign_idx % 2 == 0 else (sign_idx + 9) + int(sign_deg / 3.0)) % 12]
    elif varga == 12:
        return SIGNS[(sign_idx + int(sign_deg / 2.5)) % 12]
    elif varga == 16:
        start_sign = 0 if sign_idx % 3 == 0 else (4 if sign_idx % 3 == 1 else 8)
        return SIGNS[(start_sign + int(sign_deg / 1.875)) % 12]
    elif varga == 20:
        start_sign = 0 if sign_idx % 3 == 0 else (4 if sign_idx % 3 == 1 else 8)
        return SIGNS[(start_sign + int(sign_deg / 1.5)) % 12]
    elif varga == 24:
        return SIGNS[(4 if sign_idx % 2 == 0 else 10 + int(sign_deg / 1.25)) % 12]
    elif varga == 27:
        start_sign = 0 if sign_idx % 3 == 0 else (4 if sign_idx % 3 == 1 else 8)
        return SIGNS[(start_sign + int(sign_deg / (30.0 / 27.0))) % 12]
    elif varga == 30:
        if sign_idx % 2 == 0:
            if sign_deg < 5.0: return "Aries"
            elif sign_deg < 10.0: return "Aquarius"
            elif sign_deg < 18.0: return "Sagittarius"
            elif sign_deg < 25.0: return "Gemini"
            else: return "Libra"
        else:
            if sign_deg < 5.0: return "Taurus"
            elif sign_deg < 12.0: return "Virgo"
            elif sign_deg < 20.0: return "Pisces"
            elif sign_deg < 25.0: return "Capricorn"
            else: return "Scorpio"
    elif varga == 40:
        return SIGNS[(0 if sign_idx % 2 == 0 else 6 + int(sign_deg / 0.75)) % 12]
    elif varga == 45:
        start_sign = sign_idx if sign_idx % 3 == 0 else ((sign_idx + 4) % 12 if sign_idx % 3 == 1 else (sign_idx + 8) % 12)
        return SIGNS[(start_sign + int(sign_deg / (30.0 / 45.0))) % 12]
    elif varga == 60:
        return SIGNS[(sign_idx + int(sign_deg / 0.5)) % 12]
    return SIGNS[sign_idx]

def determine_aspects(planets_data: dict, lagna_house: int) -> dict:
    house_aspects = {f"House_{i}": [] for i in range(1, 13)}
    for p_name, p_val in planets_data.items():
        p_house = p_val["house"]
        asp_7 = (p_house + 6) if (p_house + 6) <= 12 else (p_house + 6 - 12)
        house_aspects[f"House_{asp_7}"].append(f"{p_name}_(7th_Drishti)")
        
        if p_name == "Saturn":
            asp_3 = (p_house + 2) if (p_house + 2) <= 12 else (p_house + 2 - 12)
            asp_10 = (p_house + 9) if (p_house + 9) <= 12 else (p_house + 9 - 12)
            house_aspects[f"House_{asp_3}"].append("Saturn_(3rd_Drishti)")
            house_aspects[f"House_{asp_10}"].append("Saturn_(10th_Drishti)")
        elif p_name == "Mars":
            asp_4 = (p_house + 3) if (p_house + 3) <= 12 else (p_house + 3 - 12)
            asp_8 = (p_house + 7) if (p_house + 7) <= 12 else (p_house + 7 - 12)
            house_aspects[f"House_{asp_4}"].append("Mars_(4th_Drishti)")
            house_aspects[f"House_{asp_8}"].append("Mars_(8th_Drishti)")
        elif p_name == "Jupiter":
            asp_5 = (p_house + 4) if (p_house + 4) <= 12 else (p_house + 4 - 12)
            asp_9 = (p_house + 8) if (p_house + 8) <= 12 else (p_house + 8 - 12)
            house_aspects[f"House_{asp_5}"].append("Jupiter_(5th_Drishti)")
            house_aspects[f"House_{asp_9}"].append("Jupiter_(9th_Drishti)")
    return house_aspects

def calculate_two_tier_dashas(birth_dt: datetime, moon_lon: float) -> list:
    nak_len = 360.0 / 27.0
    nak_lord, balance_decimal = _get_dasha_balance(moon_lon)

    elapsed_days = int((DASHA_YEARS[nak_lord] - balance_decimal) * 365.25)
    theoretical_start = birth_dt - timedelta(days=elapsed_days)
    
    mahadasha_list = []
    curr_start = theoretical_start
    idx = NAKSHATRA_LORDS.index(nak_lord)
    birth_plus_120 = birth_dt + timedelta(days=120 * 365.25)
    
    while curr_start < birth_plus_120:
        m_lord = NAKSHATRA_LORDS[idx]
        m_dur = DASHA_YEARS[m_lord]
        m_end = curr_start + timedelta(days=m_dur * 365.25)

        antardashas = []
        sub_start = curr_start
        sub_idx = NAKSHATRA_LORDS.index(m_lord)

        for _ in range(9):
            a_lord = NAKSHATRA_LORDS[sub_idx]
            a_dur = (m_dur * DASHA_YEARS[a_lord]) / 120.0
            a_end = sub_start + timedelta(days=int(a_dur * 365.25))
            antardashas.append({
                "antardasha": a_lord,
                "start_date": sub_start.strftime("%Y-%m-%d"),
                "end_date": a_end.strftime("%Y-%m-%d")
            })
            sub_start = a_end
            sub_idx = (sub_idx + 1) % 9
            
        if antardashas:
            antardashas[-1]["end_date"] = m_end.strftime("%Y-%m-%d")
            
        mahadasha_list.append({
            "mahadasha": m_lord,
            "start_date": curr_start.strftime("%Y-%m-%d"),
            "end_date": m_end.strftime("%Y-%m-%d"),
            "antardashas": antardashas
        })
        curr_start = m_end
        idx = (idx + 1) % 9
        
    timeline = [m for m in mahadasha_list if m["end_date"] > birth_dt.strftime("%Y-%m-%d")]
    if timeline:
        birth_str = birth_dt.strftime("%Y-%m-%d")
        timeline[0]["start_date"] = birth_str
        filtered_antars = []
        for a in timeline[0]["antardashas"]:
            if a["end_date"] > birth_str:
                filtered_antars.append(a)
        if filtered_antars:
            filtered_antars[0]["start_date"] = birth_str
            timeline[0]["antardashas"] = filtered_antars
    return timeline

NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra", 
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva_Phalguni", "Uttara_Phalguni", 
    "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha", 
    "Mula", "Purva_Ashadha", "Uttara_Ashadha", "Shravana", "Dhanishta", "Shatabhisha", 
    "Purva_Bhadrapada", "Uttara_Bhadrapada", "Revati"
]
NAKSHATRA_LORDS = ["Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury"]

# Weekday-to-slot mapping for Gulika (Mandi) calculation.
# The daytime (approx. 06:00–18:00 local) is split into 8 equal 90-minute slots.
# Gulika occupies the slot determined by the weekday of birth.
# Slot numbers (1-indexed from sunrise): Mon=6, Tue=5, Wed=4, Thu=3, Fri=2, Sat=1, Sun=7
_GULIKA_SLOTS = [6, 5, 4, 3, 2, 1, 7]  # indexed by datetime.weekday() (Mon=0 … Sun=6)


def _get_dasha_balance(moon_lon: float) -> tuple:
    """Return (ruling_planet, balance_in_years) for the nakshatra containing moon_lon.

    Centralises the Vimshottari nakshatra-lord lookup so the identical six-line
    block does not have to be duplicated in calculate_two_tier_dashas() and
    calculate_d1_chart().
    """
    nak_len = 360.0 / 27.0
    nak_idx = int(moon_lon / nak_len) % 27
    nak_lord = NAKSHATRA_LORDS[nak_idx % 9]
    traversed = moon_lon - (nak_idx * nak_len)
    pct_remaining = (nak_len - traversed) / nak_len
    balance = pct_remaining * DASHA_YEARS[nak_lord]
    return nak_lord, balance


def _calculate_gulika_longitude(
    jd_ut: float, lat: float, lon: float, local_dt: datetime, offset_hours: float
) -> float:
    """Compute Gulika (Mandi) sidereal longitude using the classical weekday-slot formula.

    The daytime is approximated as 06:00–18:00 local time (12 hours), divided into
    8 equal slots of 90 minutes each. Gulika occupies the slot determined by the
    weekday of birth. Its longitude is the sidereal Ascendant at the start of that slot.
    """
    slot = _GULIKA_SLOTS[local_dt.weekday()]
    gulika_local_hour = 6.0 + (slot - 1) * 1.5  # hours since midnight, local

    # Build a UTC Julian Day for the Gulika moment on the birth date
    local_midnight = local_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    utc_midnight = local_midnight - timedelta(hours=offset_hours)
    gulika_jd = (
        swe.julday(
            utc_midnight.year, utc_midnight.month, utc_midnight.day,
            utc_midnight.hour + utc_midnight.minute / 60.0,
        )
        + gulika_local_hour / 24.0
    )

    cusps, ascmc = swe.houses(gulika_jd, lat, lon, b"P")
    gulika_lon = (ascmc[0] - swe.get_ayanamsa(gulika_jd)) % 360
    return round(gulika_lon, 4)

ASHTAKAVARGA_RULES = {
    "Sun": {
        "Sun": [1, 2, 4, 7, 8, 9, 10, 11],
        "Moon": [3, 6, 10, 11],
        "Mars": [1, 2, 4, 7, 8, 9, 10, 11],
        "Mercury": [3, 5, 6, 9, 10, 11, 12],
        "Jupiter": [5, 6, 9, 11],
        "Venus": [6, 7, 12],
        "Saturn": [1, 2, 4, 7, 8, 9, 10, 11],
        "Lagna": [3, 4, 6, 10, 11, 12]
    },
    "Moon": {
        "Sun": [3, 6, 7, 8, 10, 11],
        "Moon": [1, 3, 6, 7, 10, 11],
        "Mars": [2, 3, 5, 6, 9, 10, 11],
        "Mercury": [1, 3, 4, 5, 7, 8, 10, 11],
        "Jupiter": [1, 4, 7, 8, 10, 11, 12],
        "Venus": [3, 4, 5, 7, 9, 10, 11],
        "Saturn": [3, 5, 6, 11],
        "Lagna": [3, 6, 10, 11]
    },
    "Mars": {
        "Sun": [3, 5, 6, 10, 11, 12],
        "Moon": [3, 6, 11],
        "Mars": [1, 2, 4, 7, 8, 9, 10, 11],
        "Mercury": [3, 5, 6, 11],
        "Jupiter": [6, 10, 11, 12],
        "Venus": [6, 8, 11, 12],
        "Saturn": [1, 4, 7, 8, 9, 10, 11],
        "Lagna": [1, 3, 6, 10, 11]
    },
    "Mercury": {
        "Sun": [5, 6, 9, 11, 12],
        "Moon": [2, 4, 6, 8, 10, 11],
        "Mars": [1, 2, 4, 7, 8, 9, 10, 11],
        "Mercury": [1, 3, 5, 6, 9, 10, 11, 12],
        "Jupiter": [6, 8, 11, 12],
        "Venus": [1, 2, 3, 4, 5, 8, 9, 11],
        "Saturn": [1, 2, 4, 7, 8, 9, 10, 11],
        "Lagna": [1, 2, 4, 6, 8, 10, 11]
    },
    "Jupiter": {
        "Sun": [1, 2, 3, 4, 7, 8, 9, 10, 11],
        "Moon": [2, 5, 7, 9, 11],
        "Mars": [1, 2, 4, 7, 8, 10, 11],
        "Mercury": [1, 2, 4, 5, 6, 9, 10, 11],
        "Jupiter": [1, 2, 3, 4, 7, 8, 10, 11],
        "Venus": [2, 5, 6, 9, 10, 11],
        "Saturn": [3, 5, 6, 12],
        "Lagna": [1, 2, 4, 5, 6, 7, 9, 10, 11]
    },
    "Venus": {
        "Sun": [8, 11, 12],
        "Moon": [1, 2, 3, 4, 5, 8, 9, 11, 12],
        "Mars": [3, 4, 6, 9, 11, 12],
        "Mercury": [3, 4, 5, 6, 9, 11],
        "Jupiter": [5, 8, 9, 10, 11],
        "Venus": [1, 2, 3, 4, 5, 8, 9, 10, 11],
        "Saturn": [3, 4, 5, 8, 9, 10, 11],
        "Lagna": [1, 2, 3, 4, 5, 8, 9, 11]
    },
    "Saturn": {
        "Sun": [1, 2, 4, 7, 8, 10, 11],
        "Moon": [3, 6, 11],
        "Mars": [3, 5, 6, 10, 11, 12],
        "Mercury": [6, 8, 9, 10, 11, 12],
        "Jupiter": [5, 6, 11, 12],
        "Venus": [6, 11, 12],
        "Saturn": [3, 5, 6, 11],
        "Lagna": [1, 3, 4, 6, 10, 11]
    }
}

def calculate_samudaya_ashtakavarga(planets_data, lagna_sign_idx):
    samudaya = [0] * 12
    for p_target in ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]:
        rules = ASHTAKAVARGA_RULES[p_target]
        for source_name, relative_houses in rules.items():
            if source_name == "Lagna":
                source_sign = lagna_sign_idx
            else:
                source_sign = SIGNS.index(planets_data[source_name]["sign"])
            
            for h in relative_houses:
                target_sign = (source_sign + h - 1) % 12
                samudaya[target_sign] += 1
                
    ashtakavarga_bindus = {}
    for h_idx in range(12):
        house_sign = (lagna_sign_idx + h_idx) % 12
        ashtakavarga_bindus[f"House_{h_idx + 1}"] = samudaya[house_sign]
        
    return ashtakavarga_bindus

EXALTATION_DEGREES = {
    "Sun": 10, "Moon": 33, "Mars": 298, "Mercury": 165, "Jupiter": 95, "Venus": 357, "Saturn": 200
}

def detect_all_yogas(planets_data, lagna_sign_idx):
    yogas = {}
    
    # 1. Gajakesari Yoga: Jupiter in 1, 4, 7, 10 from Moon
    # Classical validity requires Moon NOT in a dusthana (6,8,12)
    # If Moon is in dusthana, yoga forms but phala is attenuated.
    moon_house = planets_data["Moon"]["house"]
    jup_house = planets_data["Jupiter"]["house"]
    relative_moon_jup = (jup_house - moon_house) % 12
    gajakesari_geometry = relative_moon_jup in [0, 3, 6, 9]
    moon_in_dusthana = moon_house in [6, 8, 12]
    yogas["Gajakesari"] = gajakesari_geometry
    yogas["Gajakesari_Full_Strength"] = gajakesari_geometry and not moon_in_dusthana
    yogas["Gajakesari_Attenuated"] = gajakesari_geometry and moon_in_dusthana
    
    # 2. Pancha Mahapurusha Yogas
    mahapurusha_rules = {
        "Ruchaka": ("Mars", ["Aries", "Scorpio"], "Capricorn"),
        "Bhadra": ("Mercury", ["Gemini", "Virgo"], "Virgo"),
        "Hamsa": ("Jupiter", ["Sagittarius", "Pisces"], "Cancer"),
        "Malavya": ("Venus", ["Taurus", "Libra"], "Pisces"),
        "Sasa": ("Saturn", ["Capricorn", "Aquarius"], "Libra")
    }
    
    for yoga_name, (p_name, own, exalted) in mahapurusha_rules.items():
        p_data = planets_data[p_name]
        is_in_kendra = p_data["house"] in [1, 4, 7, 10]
        is_dignified = p_data["sign"] in own or p_data["sign"] == exalted
        yogas[yoga_name] = is_in_kendra and is_dignified
        
    # 3. Budhaditya Yoga: Sun & Mercury in the same house
    yogas["Budhaditya"] = planets_data["Sun"]["house"] == planets_data["Mercury"]["house"]
    
    # 4. Neechabhanga Raja Yoga: cancellation of debilitation
    neechabhanga = False
    for p_name, ex_deg in EXALTATION_DEGREES.items():
        p_data = planets_data[p_name]
        DEBILITATION_SIGNS = {
            "Sun": "Libra", "Moon": "Scorpio", "Mars": "Cancer", 
            "Mercury": "Pisces", "Jupiter": "Capricorn", "Venus": "Virgo", "Saturn": "Aries"
        }
        if p_data["sign"] == DEBILITATION_SIGNS[p_name]:
            dispositor = HOUSE_LORDS[p_data["sign"]]
            disp_house = planets_data[dispositor]["house"]
            disp_from_moon = (disp_house - moon_house) % 12 + 1
            if disp_house in [1, 4, 7, 10] or disp_from_moon in [1, 4, 7, 10]:
                neechabhanga = True
                break
    yogas["Neechabhanga_Raja"] = neechabhanga

    # Rahu/Ketu dispositor strength assessment
    rahu_sign = planets_data["Rahu"]["sign"]
    ketu_sign = planets_data["Ketu"]["sign"]
    rahu_dispositor = HOUSE_LORDS[rahu_sign]
    ketu_dispositor = HOUSE_LORDS[ketu_sign]

    DEBILITATION_SIGNS_ALL = {
        "Sun": "Libra", "Moon": "Scorpio", "Mars": "Cancer",
        "Mercury": "Pisces", "Jupiter": "Capricorn",
        "Venus": "Virgo", "Saturn": "Aries"
    }

    rahu_disp_debilitated = (
        rahu_dispositor in DEBILITATION_SIGNS_ALL and
        planets_data.get(rahu_dispositor, {}).get("sign") ==
        DEBILITATION_SIGNS_ALL[rahu_dispositor]
    )
    ketu_disp_debilitated = (
        ketu_dispositor in DEBILITATION_SIGNS_ALL and
        planets_data.get(ketu_dispositor, {}).get("sign") ==
        DEBILITATION_SIGNS_ALL[ketu_dispositor]
    )

    yogas["Rahu_Dispositor_Weak"] = rahu_disp_debilitated
    yogas["Ketu_Dispositor_Weak"] = ketu_disp_debilitated
    yogas["Rahu_Dispositor"] = rahu_dispositor
    yogas["Rahu_Dispositor_Sign"] = planets_data.get(
        rahu_dispositor, {}
    ).get("sign", "Unknown")

    # Guru-Chandala Yoga check in D9 (Navamsha)
    jup_d9 = planets_data["Jupiter"]["vargas"].get("D9", "")
    rahu_d9 = planets_data["Rahu"]["vargas"].get("D9", "")
    yogas["Guru_Chandala_D9"] = (
        bool(jup_d9) and bool(rahu_d9) and jup_d9 == rahu_d9
    )
    if yogas["Guru_Chandala_D9"]:
        yogas["Guru_Chandala_D9_Sign"] = jup_d9
        yogas["Guru_Chandala_D9_Note"] = (
            f"Jupiter and Rahu conjunct in {jup_d9} Navamsha — "
            "Guru-Chandala pattern in D9 chart. Spouse's dharmic "
            "alignment may be unconventional; wisdom may be tainted "
            "by materialistic or deceptive influences. Verify "
            "dispositor strength for full assessment."
        )

    # Gajakesari phala classification for report use
    if yogas.get("Gajakesari"):
        moon_h = planets_data["Moon"]["house"]
        jup_sign = planets_data["Jupiter"]["sign"]
        moon_sign = planets_data["Moon"]["sign"]
        # Moon is debilitated in Scorpio (Parashari standard)
        # AND in Capricorn per some classical texts (neecha bhanga
        # context). We check both to be safe.
        DEBILITATION_SIGNS_GK = {
            "Sun": "Libra", "Moon": "Scorpio", "Mars": "Cancer",
            "Mercury": "Pisces", "Jupiter": "Capricorn",
            "Venus": "Virgo", "Saturn": "Aries"
        }
        # Capricorn is Moon's deep debilitation point (3° Capricorn)
        # per classical Parashari — include both
        moon_debilitated = moon_sign in ["Scorpio", "Capricorn"]
        yogas["Gajakesari_Notes"] = {
            "geometry": "conjunction" if relative_moon_jup == 0 else "kendra_aspect",
            "moon_dusthana": moon_in_dusthana,
            "moon_debilitated": moon_debilitated,
            "phala": "attenuated" if (moon_in_dusthana or moon_debilitated) else "full",
            "caveat": (
                "Moon in dusthana and debilitated sign significantly weakens "
                "Gajakesari phala per Phaladeepika. Fame and prosperity are "
                "conditional, not assured."
            ) if (moon_in_dusthana or moon_debilitated) else "Full phala active."
        }

    return yogas

def calculate_dynamic_shadbala(planets_data):
    potencies = {}
    for name in ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]:
        p_data = planets_data[name]
        lon = p_data["longitude"]
        house = p_data["house"]
        
        ex_deg = EXALTATION_DEGREES[name]
        deb_deg = (ex_deg + 180) % 360
        dist = abs(lon - deb_deg)
        if dist > 180: dist = 360 - dist
        exaltation_points = (dist / 180.0) * 60.0
        
        dig_bala = 0
        if name in ["Sun", "Mars"]:
            h_dist = abs(house - 10)
            if h_dist > 6: h_dist = 12 - h_dist
            dig_bala = (1.0 - h_dist / 6.0) * 60.0
        elif name in ["Jupiter", "Mercury"]:
            h_dist = abs(house - 1)
            if h_dist > 6: h_dist = 12 - h_dist
            dig_bala = (1.0 - h_dist / 6.0) * 60.0
        elif name in ["Moon", "Venus"]:
            h_dist = abs(house - 4)
            if h_dist > 6: h_dist = 12 - h_dist
            dig_bala = (1.0 - h_dist / 6.0) * 60.0
        elif name in ["Saturn"]:
            h_dist = abs(house - 7)
            if h_dist > 6: h_dist = 12 - h_dist
            dig_bala = (1.0 - h_dist / 6.0) * 60.0
            
        cheshta_bala = 30.0
        if p_data.get("is_retrograde") == "Yes":
            cheshta_bala = 60.0
        elif p_data.get("is_combust") == "Yes":
            cheshta_bala = 10.0
            
        total_bala = exaltation_points + dig_bala + cheshta_bala
        shadbala_score = int(300 + total_bala * 2.2)
        
        if shadbala_score > 480:
            classification = "Very_High"
        elif shadbala_score > 410:
            classification = "Strong"
        elif shadbala_score > 350:
            classification = "Balanced"
        elif shadbala_score > 310:
            classification = "Auspicious"
        else:
            classification = "Modified"
            
        potencies[name] = f"{classification}_({shadbala_score}_HER)"
        
    return potencies

def calculate_transits_for_date(date_str, lagna_sign_idx):
    try:
        py, pm, pd = [int(x) for x in date_str.split("-")]
        p_jd = swe.julday(py, pm, pd, 12.0)
        planet_map = {"Sun": swe.SUN, "Moon": swe.MOON, "Mars": swe.MARS, "Mercury": swe.MERCURY, "Jupiter": swe.JUPITER, "Venus": swe.VENUS, "Saturn": swe.SATURN, "Rahu": swe.MEAN_NODE}
        transit_planets = {}
        for name, pid in planet_map.items():
            res = swe.calc_ut(p_jd, pid, swe.FLG_SIDEREAL)
            lon_val = res[0][0] % 360
            s_idx = int(lon_val / 30)
            transit_planets[name] = {
                "sign": SIGNS[s_idx],
                "longitude": round(lon_val, 4),
                "house": (s_idx - lagna_sign_idx) % 12 + 1
            }
        return transit_planets
    except Exception:
        return {}


def get_nakshatra_info(longitude: float):
    deg = longitude % 360.0
    nak_len = 360.0 / 27.0
    nak_idx = int(deg / nak_len) % 27
    nak_name = NAKSHATRAS[nak_idx]
    lord_name = NAKSHATRA_LORDS[nak_idx % 9]
    return nak_name, lord_name

_TODAY = datetime.today().strftime("%Y-%m-%d")


def find_solar_return_generic(
    birth_sun_lon: float,
    dob_utc: datetime,
    completed_age: int
) -> float:
    approx_year = dob_utc.year + completed_age
    jd_start = swe.julday(approx_year, dob_utc.month, dob_utc.day, 12.0)
    low = jd_start - 2.0
    high = jd_start + 2.0
    for _ in range(35):
        mid = (low + high) / 2.0
        res = swe.calc_ut(mid, swe.SUN, swe.FLG_SIDEREAL)
        sun_lon = res[0][0] % 360.0
        diff = (sun_lon - birth_sun_lon + 180.0) % 360.0 - 180.0
        if diff < 0:
            low = mid
        else:
            high = mid
    jd_ret = (low + high) / 2.0
    res_check = swe.calc_ut(jd_ret, swe.SUN, swe.FLG_SIDEREAL)
    final_lon = res_check[0][0] % 360.0
    error_deg = abs((final_lon - birth_sun_lon + 180.0) % 360.0 - 180.0)
    if error_deg > 0.5:
        log.warning(
            "Solar return search imprecise: birth_sun=%.4f, found=%.4f, error=%.4f°",
            birth_sun_lon, final_lon, error_deg
        )
        return jd_start
    return jd_ret


def compute_varshaphal(
    birth_sun_lon: float,
    dob_utc: datetime,
    birth_lagna_sign_idx: int,
    lat: float,
    lon: float,
    prediction_date: str,
    ayanamsha: str
) -> dict:
    try:
        pred_dt = datetime.strptime(prediction_date, "%Y-%m-%d")
        completed_age = pred_dt.year - dob_utc.year
        if (pred_dt.month, pred_dt.day) < (dob_utc.month, dob_utc.day):
            completed_age -= 1
        jd_ret = find_solar_return_generic(birth_sun_lon, dob_utc, completed_age)
        ret_utc = datetime(2000, 1, 1, 12, 0) + timedelta(days=(jd_ret - 2451545.0))
        solar_return_date = ret_utc.strftime("%Y-%m-%d")
        solar_return_time = ret_utc.strftime("%H:%M:%S")
        cusps, ascmc = swe.houses(jd_ret, lat, lon, b"P")
        varsha_lagna_lon = (ascmc[0] - swe.get_ayanamsa(jd_ret)) % 360.0
        varsha_lagna_sign_idx = int(varsha_lagna_lon / 30.0)
        varsha_lagna_nak, varsha_lagna_nak_lord = get_nakshatra_info(varsha_lagna_lon)
        muntha_sign_idx = (birth_lagna_sign_idx + completed_age) % 12
        muntha_house = (muntha_sign_idx - varsha_lagna_sign_idx) % 12 + 1
        planet_map = {
            "Sun": swe.SUN, "Moon": swe.MOON, "Mars": swe.MARS,
            "Mercury": swe.MERCURY, "Jupiter": swe.JUPITER,
            "Venus": swe.VENUS, "Saturn": swe.SATURN,
            "Rahu": swe.MEAN_NODE
        }
        varsha_planets = {}
        for p_name, pid in planet_map.items():
            res = swe.calc_ut(jd_ret, pid, swe.FLG_SIDEREAL)
            p_lon = res[0][0] % 360.0
            p_sign_idx = int(p_lon / 30.0)
            varsha_planets[p_name] = {
                "sign": SIGNS[p_sign_idx],
                "longitude": round(p_lon, 4),
                "house": (p_sign_idx - varsha_lagna_sign_idx) % 12 + 1
            }
        ketu_lon = (varsha_planets["Rahu"]["longitude"] + 180.0) % 360.0
        ketu_sign_idx = int(ketu_lon / 30.0)
        varsha_planets["Ketu"] = {
            "sign": SIGNS[ketu_sign_idx],
            "longitude": round(ketu_lon, 4),
            "house": (ketu_sign_idx - varsha_lagna_sign_idx) % 12 + 1
        }

        # Detect Sun-Ketu close conjunction in Varsha chart
        varsha_sun_lon = varsha_planets["Sun"]["longitude"]
        varsha_ketu_lon = varsha_planets["Ketu"]["longitude"]
        sun_ketu_diff = abs(
            (varsha_sun_lon - varsha_ketu_lon + 180) % 360 - 180
        )
        varsha_sun_ketu_conjunction = (
            varsha_planets["Sun"]["house"] ==
            varsha_planets["Ketu"]["house"] and
            sun_ketu_diff <= 13.0
        )

        # Detect Varsha Saturn 7th drishti on Varsha Lagna
        varsha_saturn_house = varsha_planets["Saturn"]["house"]
        saturn_7th_target = (varsha_saturn_house + 6 - 1) % 12 + 1
        varsha_saturn_aspects_lagna = (saturn_7th_target == 1)

        # Also check Saturn 3rd and 10th special drishti on Lagna
        saturn_3rd_target = (varsha_saturn_house + 2 - 1) % 12 + 1
        saturn_10th_target = (varsha_saturn_house + 9 - 1) % 12 + 1
        varsha_saturn_special_on_lagna = (
            saturn_3rd_target == 1 or saturn_10th_target == 1
        )

        return {
            "completed_age": completed_age,
            "solar_return_jd": round(jd_ret, 4),
            "solar_return_date": solar_return_date,
            "solar_return_time_utc": solar_return_time,
            "varsha_lagna": {
                "sign": SIGNS[varsha_lagna_sign_idx],
                "sign_index": varsha_lagna_sign_idx,
                "longitude": round(varsha_lagna_lon, 4),
                "nakshatra": varsha_lagna_nak,
                "nakshatra_lord": varsha_lagna_nak_lord
            },
            "muntha": {
                "sign": SIGNS[muntha_sign_idx],
                "sign_index": muntha_sign_idx,
                "house": muntha_house
            },
            "varsha_planets": varsha_planets,
            "varsha_alerts": {
                "sun_ketu_conjunction": varsha_sun_ketu_conjunction,
                "sun_ketu_orb_degrees": round(sun_ketu_diff, 2),
                "sun_ketu_house": varsha_planets["Sun"]["house"] if varsha_sun_ketu_conjunction else None,
                "sun_ketu_note": (
                    "Sun-Ketu conjunction within 13° in Varsha H"
                    + str(varsha_planets["Sun"]["house"])
                    + " creates eclipse-like suppression of identity "
                    "and vitality. Health vigilance advised."
                ) if varsha_sun_ketu_conjunction else None,
                "saturn_aspects_varsha_lagna": varsha_saturn_aspects_lagna,
                "saturn_special_drishti_on_lagna": varsha_saturn_special_on_lagna,
                "saturn_lagna_note": (
                    "Varsha Saturn in H" + str(varsha_saturn_house) +
                    " casts drishti on Varsha Lagna — health and "
                    "vitality require active monitoring this solar year. "
                    "Career themes are secondary to physical constitution."
                ) if (varsha_saturn_aspects_lagna or varsha_saturn_special_on_lagna) else None
            }
        }
    except Exception as e:
        log.error("compute_varshaphal failed: %s", e, exc_info=True)
        return {
            "error": str(e),
            "completed_age": 0,
            "muntha": {"sign": "Aries", "sign_index": 0, "house": 1},
            "varsha_planets": {}
        }


@mcp.tool()
def calculate_d1_chart(dob: str, tob: str, tz_offset: str, lat: float, lon: float, ayanamsha: str = "raman", prediction_date: str = _TODAY) -> str:
    with _swe_lock:
     try:
        y, m, d = [int(x) for x in dob.split("-")]
        h, mn = [int(x) for x in tob.split(":")]
        
        sign = -1.0 if "-" in tz_offset else 1.0
        tz_clean = tz_offset.replace("+", "").replace("-", "")
        th, tm = [float(x) for x in tz_clean.split(":")] if ":" in tz_clean else (float(tz_clean), 0.0)
        offset_hours = sign * (th + tm / 60.0)
        
        local_dt = datetime(y, m, d, h, mn)
        utc_dt = local_dt - timedelta(hours=offset_hours)
        jd_ut = swe.julday(utc_dt.year, utc_dt.month, utc_dt.day, utc_dt.hour + utc_dt.minute/60.0)

        if ayanamsha.strip().lower() == 'lahiri':
            swe.set_sid_mode(swe.SIDM_LAHIRI)
        elif ayanamsha.strip().lower() == 'pushya':
            swe.set_sid_mode(swe.SIDM_TRUE_PUSHYA)
        else:
            swe.set_sid_mode(swe.SIDM_RAMAN)

        cusps, ascmc = swe.houses(jd_ut, lat, lon, b'P')
        lagna_long = (ascmc[0] - swe.get_ayanamsa(jd_ut)) % 360
        lagna_sign_idx = int(lagna_long / 30)

        lagna_nak, lagna_lord = get_nakshatra_info(lagna_long)
        ascendant_data = {
            "sign": SIGNS[lagna_sign_idx],
            "longitude": round(lagna_long, 4),
            "house": 1,
            "nakshatra": lagna_nak,
            "nakshatra_lord": lagna_lord
        }

        planet_map = {"Sun": swe.SUN, "Moon": swe.MOON, "Mars": swe.MARS, "Mercury": swe.MERCURY, "Jupiter": swe.JUPITER, "Venus": swe.VENUS, "Saturn": swe.SATURN, "Rahu": swe.MEAN_NODE}
        planets_data = {}
        varga_list = [1, 2, 3, 4, 5, 7, 9, 10, 12, 16, 20, 24, 27, 30, 40, 45, 60]
        
        for name, pid in planet_map.items():
            res = swe.calc_ut(jd_ut, pid, swe.FLG_SIDEREAL)
            lon_val = res[0][0] % 360
            s_idx = int(lon_val / 30)
            
            is_retrograde = "Yes" if res[0][3] < 0 else "No"
            is_combust = "Yes" if name != "Sun" and abs(lon_val - (swe.calc_ut(jd_ut, swe.SUN, swe.FLG_SIDEREAL)[0][0] % 360)) < 8.5 else "No"
            varga_map = {f"D{v}": calculate_universal_varga(lon_val, v) for v in varga_list}
            
            p_nak, p_lord = get_nakshatra_info(lon_val)
                
            planets_data[name] = {
                "sign": SIGNS[s_idx],
                "longitude": round(lon_val, 4),
                "house": (s_idx - lagna_sign_idx) % 12 + 1,
                "is_retrograde": is_retrograde,
                "is_combust": is_combust,
                "vargas": varga_map,
                "nakshatra": p_nak,
                "nakshatra_lord": p_lord
            }

        k_lon = (planets_data["Rahu"]["longitude"] + 180.0) % 360
        k_varga_map = {f"D{v}": calculate_universal_varga(k_lon, v) for v in varga_list}
        k_nak, k_lord = get_nakshatra_info(k_lon)
        planets_data["Ketu"] = {
            "sign": SIGNS[int(k_lon / 30)], 
            "longitude": round(k_lon, 4), 
            "house": (int(k_lon / 30) - lagna_sign_idx) % 12 + 1, 
            "is_retrograde": "No", 
            "is_combust": "No", 
            "vargas": k_varga_map,
            "nakshatra": k_nak,
            "nakshatra_lord": k_lord
        }

        # Compute Gulika (Mandi) using the classical weekday-slot formula.
        # _calculate_gulika_longitude returns the sidereal Ascendant at Gulika's hora.
        g_lon = _calculate_gulika_longitude(jd_ut, lat, lon, local_dt, offset_hours)

        g_varga_map = {f"D{v}": calculate_universal_varga(g_lon, v) for v in varga_list}
        g_nak, g_lord = get_nakshatra_info(g_lon)
        gulika_data = {
            "sign": SIGNS[int(g_lon / 30)], 
            "longitude": round(g_lon, 4), 
            "house": (int(g_lon / 30) - lagna_sign_idx) % 12 + 1, 
            "is_retrograde": "No", 
            "is_combust": "No", 
            "vargas": g_varga_map,
            "nakshatra": g_nak,
            "nakshatra_lord": g_lord
        }
        planets_data["Gulika"] = gulika_data

        global_aspect_map = determine_aspects(planets_data, lagna_sign_idx)

        house_lord_mapping = {}
        for h_idx in range(12):
            h_num_str = f"House_{h_idx + 1}"
            h_sign_idx = (lagna_sign_idx + h_idx) % 12
            h_sign_name = SIGNS[h_sign_idx]
            lord_name = HOUSE_LORDS[h_sign_name]
            karaka_name = BHAVA_KARAKAS[h_num_str]
            occupants = [p for p, v in planets_data.items() if v["house"] == (h_idx + 1)]
            
            house_lord_mapping[h_num_str] = {
                "ZodiacSign": h_sign_name,
                "HouseLord": lord_name,
                "LordPlacementHouse": planets_data[lord_name]["house"],
                "NaturalSignificator": karaka_name,
                "SignificatorPlacementHouse": planets_data[karaka_name]["house"],
                "Occupants": occupants,
                "ReceivingAspects": global_aspect_map[h_num_str]
            }

        s_lon = planets_data["Sun"]["longitude"]
        m_lon = planets_data["Moon"]["longitude"]
        tithi_diff = (m_lon - s_lon) % 360
        tithi_idx = int(tithi_diff / 12) + 1
        tithi_names_shukla = ["Prathama", "Dwitiya", "Tritiya", "Chaturthi", "Panchami", "Shasthi", "Saptami", "Ashtami", "Navami", "Dashami", "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi", "Poornima"]
        tithi_names_krishna = ["Prathama", "Dwitiya", "Tritiya", "Chaturthi", "Panchami", "Shasthi", "Saptami", "Ashtami", "Navami", "Dashami", "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi", "Amavasya"]
        tithi_name = f"Shukla_Paksha_{tithi_names_shukla[tithi_idx - 1]}" if tithi_idx <= 15 else f"Krishna_Paksha_{tithi_names_krishna[tithi_idx - 16]}"
        
        # Calculate transit positions for prediction date
        py, pm, pd = [int(x) for x in prediction_date.split("-")]
        p_jd = swe.julday(py, pm, pd, 12.0)
        transit_planets = {}
        for name, pid in planet_map.items():
            res = swe.calc_ut(p_jd, pid, swe.FLG_SIDEREAL)
            lon_val = res[0][0] % 360
            s_idx = int(lon_val / 30)
            transit_planets[name] = {
                "sign": SIGNS[s_idx],
                "longitude": round(lon_val, 4),
                "house": (s_idx - lagna_sign_idx) % 12 + 1
            }

        raw_timeline = calculate_two_tier_dashas(local_dt, planets_data["Moon"]["longitude"])
        for m in raw_timeline:
            m["transit_positions"] = calculate_transits_for_date(m["start_date"], lagna_sign_idx)
            for a in m.get("antardashas", []):
                a["transit_positions"] = calculate_transits_for_date(a["start_date"], lagna_sign_idx)

        nak_len = 360.0 / 27.0
        nak_idx = int(planets_data["Moon"]["longitude"] / nak_len) % 27
        nak_lord, balance_decimal = _get_dasha_balance(planets_data["Moon"]["longitude"])

        dasha_timeline_dict = {
            "dasha_balance": {
                "dasha": nak_lord,
                "years": round(balance_decimal, 4)
            },
            "timeline": [
                {
                    "dasha": m["mahadasha"],
                    "mahadasha": m["mahadasha"],
                    "start_date": m["start_date"],
                    "end_date": m["end_date"],
                    "transit_positions": m["transit_positions"],
                    "antardashas": [
                        {
                            "antardasha": a["antardasha"],
                            "start_date": a["start_date"],
                            "end_date": a["end_date"],
                            "transit_positions": a.get("transit_positions", {})
                        } for a in m.get("antardashas", [])
                    ]
                } for m in raw_timeline
            ]
        }

        planets_data_nine = {k: v for k, v in planets_data.items() if k != "Gulika"}

        natal_positions = {
            "planets": planets_data_nine,
            "special_points": {
                "Lagna": ascendant_data,
                "Gulika": gulika_data
            }
        }
            
        dynamic_bindus = calculate_samudaya_ashtakavarga(
            planets_data, lagna_sign_idx
        )

        # Ashtakavarga H12 expenditure type analysis
        h12_bindus = dynamic_bindus.get("House_12", 0)
        h12_sign_idx = (lagna_sign_idx + 11) % 12
        h12_lord = HOUSE_LORDS[SIGNS[h12_sign_idx]]
        h12_lord_house = planets_data.get(h12_lord, {}).get("house", 0)

        EXPENDITURE_PROFILES = {
            "Venus": "luxury, medical/hospitalization, foreign comforts, romantic pursuits",
            "Mercury": "communication, travel, education, trading losses",
            "Moon": "emotional spending, family, liquids, travel",
            "Sun": "authority/government related, health, status expenditure",
            "Mars": "legal disputes, surgery, accidents, property",
            "Jupiter": "religious/charitable giving, education, pilgrimages",
            "Saturn": "chronic illness, labor, property maintenance, isolation"
        }

        ashtakavarga_h12_analysis = {
            "h12_bindus": h12_bindus,
            "h12_lord": h12_lord,
            "h12_lord_house": h12_lord_house,
            "expenditure_profile": EXPENDITURE_PROFILES.get(
                h12_lord, "general expenditure"
            ),
            "severity": (
                "high" if h12_bindus >= 35 else
                "moderate" if h12_bindus >= 28 else
                "low"
            ),
            "note": (
                f"H12 has {h12_bindus} bindus with {h12_lord} as lord "
                f"({EXPENDITURE_PROFILES.get(h12_lord, 'general expenditure')}). "
                + (
                    "High bindu count amplifies this expenditure channel "
                    "significantly — not merely spiritual liberation."
                    if h12_bindus >= 35 else ""
                )
            )
        }

        dynamic_shadbala = calculate_dynamic_shadbala(planets_data)
        detected_yogas = detect_all_yogas(planets_data, lagna_sign_idx)

        varshaphal_data = compute_varshaphal(
            birth_sun_lon=planets_data["Sun"]["longitude"],
            dob_utc=utc_dt,
            birth_lagna_sign_idx=lagna_sign_idx,
            lat=lat,
            lon=lon,
            prediction_date=prediction_date,
            ayanamsha=ayanamsha
        )

        result = {
            "ascendant": ascendant_data,
            "lagna_sign": ascendant_data["sign"],
            "planets": planets_data_nine,
            "upagrahas": {"Gulika": gulika_data},
            "special_points": {"Lagna": ascendant_data, "Gulika": gulika_data},
            "house_lord_matrix": house_lord_mapping,
            "panchanga_metrics": {"Tithi": tithi_name, "Vara": WEEKDAYS[local_dt.weekday()], "Yoga": YOGAS[int(((s_lon + m_lon) % 360) / (360.0 / 27.0)) % 27], "Karana": KARANAS[int(tithi_diff / 6) % 11]},
            "ashtakavarga_bindus": dynamic_bindus,
            "ashtakavarga_h12_analysis": ashtakavarga_h12_analysis,
            "shadbala_potency": dynamic_shadbala,
            "dasha_timeline": dasha_timeline_dict,
            "dasha_and_antardasha_timeline": raw_timeline,
            "natal_positions": natal_positions,
            "transit_positions": transit_planets,
            "yogas": detected_yogas,
            "varshaphal": varshaphal_data,
            "metadata": {"ayanamsha": ayanamsha}
        }
        return json.dumps(result, separators=(',', ':'))
     except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

if __name__ == "__main__":
    mcp.run()