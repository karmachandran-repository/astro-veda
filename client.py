#!/usr/bin/env python3
"""
AstroVeda Engine Orchestrator Client (OpenAI Decoupled Core Edition)
Handles structural data processing, eliminates prompt fatigue, 
and streams an un-abbreviated, personalized 6-part Jyotish analysis.
"""

import os
import sys
import json
import asyncio
import logging
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

log = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # OpenAI is an optional fallback; Claude is primary

def load_system_blueprint(filename="synthesis_engine.md"):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.join(base_dir, filename)
    if not os.path.exists(full_path):
        print(f"[Critical Initialization Error] Blueprint file missing at: {full_path}", file=sys.stderr)
        sys.exit(1)
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read()

def calculate_tajika_progressions(
    dob_str: str,
    prediction_date_str: str,
    natal_data: dict = None
) -> dict:
    if natal_data and "varshaphal" in natal_data:
        vp = natal_data["varshaphal"]
        if "error" not in vp:
            return vp
    try:
        from datetime import datetime
        birth_date = datetime.strptime(dob_str, "%Y-%m-%d")
        target_date = datetime.strptime(prediction_date_str, "%Y-%m-%d")
        completed_age = target_date.year - birth_date.year
        if (target_date.month, target_date.day) < (
            birth_date.month, birth_date.day
        ):
            completed_age -= 1
        muntha_house = (completed_age % 12) + 1
        return {"completed_age": completed_age, "muntha_progressed_house": muntha_house}
    except Exception:
        return {"completed_age": 0, "muntha_progressed_house": 1}

def invoke_claude_engine(natal_data, varshaphal_data, system_blueprint, birth_metadata):
    """Run the full 10-part synthesis via Claude (Anthropic). Primary inference engine."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or api_key == "YOUR_CLAUDE_API_KEY_HERE":
        print("\n[Configuration Error] ANTHROPIC_API_KEY not set. Falling back to OpenAI.")
        invoke_openai_cloud_engine(natal_data, varshaphal_data, system_blueprint, birth_metadata)
        return

    try:
        from anthropic import Anthropic
    except ImportError:
        print("[Error] 'anthropic' package not installed. Run: pip install anthropic", file=sys.stderr)
        return

    try:
        from client import calculate_tajika_progressions, search_local_index
        planets = natal_data["planets"]
        panchanga = natal_data["panchanga_metrics"]
        hl_matrix = natal_data["house_lord_matrix"]

        data_sheet = "AUTHENTIC CELESTIAL ALIGNMENT COORDINATES FOR SYNTHESIS:\n"
        data_sheet += f"- Native Gender Profile: {birth_metadata['gender']}\n"
        data_sheet += f"- Chosen Ayanamsha: {birth_metadata['selected_ayanamsha'].upper()}\n"
        data_sheet += f"- Panchanga Baseline: Weekday={panchanga['Vara']}, Tithi={panchanga['Tithi']}, Yoga={panchanga['Yoga']}, Karana={panchanga['Karana']}\n"
        vp = natal_data.get("varshaphal", varshaphal_data or {})
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
                f"HouseLord={h_data['HouseLord']} in House {h_data['LordPlacementHouse']} | "
                f"NaturalKaraka={h_data['NaturalSignificator']} in House {h_data['SignificatorPlacementHouse']} | "
                f"Aspects={h_data['ReceivingAspects']}\n"
            )

        data_sheet += "\nSHODASAVARGA SIGN HARMONICS:\n"
        varga_list = [1, 2, 3, 4, 5, 7, 9, 10, 12, 16, 20, 24, 27, 30, 40, 45, 60]
        for p_name, p_val in planets.items():
            v_str = ", ".join([f"D{v}={p_val['vargas'][f'D{v}']}" for v in varga_list])
            data_sheet += f"- {p_name}: House={p_val['house']}, Retro={p_val['is_retrograde']}, Combust={p_val['is_combust']} | {v_str}\n"

        data_sheet += f"\nASHTAKAVARGA: {json.dumps(natal_data['ashtakavarga_bindus'])}\n"
        data_sheet += f"SHADBALA: {json.dumps(natal_data['shadbala_potency'])}\n"
        dasha_list = natal_data['dasha_timeline']['timeline'] if isinstance(natal_data['dasha_timeline'], dict) else natal_data['dasha_timeline']
        data_sheet += f"\nVIMSHOTTARI TIMELINE: {json.dumps(dasha_list[:5])}\n"
        data_sheet += f"\nCLASSICAL RULES:\n{search_local_index(natal_data)}\n"
    except Exception as e:
        data_sheet = f"Error assembling data sheet: {e}"

    print("\n" + "="*70)
    print("      ASTROVEDA CLAUDE SYNTHESIS — FULL 10-PART JYOTISH REPORT")
    print("="*70 + "\n")

    from datetime import datetime as _dt
    today_str = _dt.today().strftime("%B %d, %Y")
    live_blueprint = system_blueprint.replace("{CURRENT_DATE}", today_str)

    try:
        client = Anthropic(api_key=api_key)
        with client.messages.stream(
            model="claude-opus-4-6",
            max_tokens=16000,
            system=live_blueprint,
            messages=[{"role": "user", "content": (
                "Execute full synthesis immediately using this raw data payload. "
                "Do not output instructions or definition summaries:\n\n" + data_sheet
            )}],
        ) as stream:
            for text_chunk in stream.text_stream:
                print(text_chunk, end="", flush=True)
        return
    except Exception as e:
        print(f"\n[Claude Inference Failure]: {e}")

def invoke_openai_cloud_engine(natal_data, varshaphal_data, system_blueprint, birth_metadata):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("\n[Configuration Error] Environment variable OPENAI_API_KEY not found!")
        return

    try:
        planets = natal_data["planets"]
        panchanga = natal_data["panchanga_metrics"]
        hl_matrix = natal_data["house_lord_matrix"]
        
        # Flatten the data out cleanly to prevent prompt structural clashing
        data_sheet = "AUTHENTIC CELESTIAL ALIGNMENT COORDINATES FOR SYNTHESIS:\n"
        data_sheet += f"- Native Gender Profile: {birth_metadata['gender']}\n"
        data_sheet += f"- Chosen Ayanamsha: {birth_metadata['selected_ayanamsha'].upper()}\n"
        data_sheet += f"- Panchanga Baseline: Weekday={panchanga['Vara']}, Tithi={panchanga['Tithi']}, Yoga={panchanga['Yoga']}, Karana={panchanga['Karana']}\n"
        vp = natal_data.get("varshaphal", varshaphal_data or {})
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
        vp_alerts = natal_data.get("varshaphal", {})
        alerts = vp_alerts.get("varsha_alerts", {})
        if alerts:
            data_sheet += "\nVARSHA CHART ALERTS:\n"
            if alerts.get("sun_ketu_note"):
                data_sheet += f"- {alerts['sun_ketu_note']}\n"
            if alerts.get("saturn_lagna_note"):
                data_sheet += f"- {alerts['saturn_lagna_note']}\n"
        h12_analysis = natal_data.get("ashtakavarga_h12_analysis", {})
        if h12_analysis:
            data_sheet += (
                f"\nH12 EXPENDITURE PROFILE:\n"
                f"- {h12_analysis.get('note', '')}\n"
            )

        dasha_list = natal_data['dasha_timeline']['timeline'] if isinstance(natal_data['dasha_timeline'], dict) else natal_data['dasha_timeline']
        data_sheet += f"\nVIMSHOTTARI TIMELINE INTERSECTIONS ARRAY: {json.dumps(dasha_list[:5])}\n"
        
        # Dynamically retrieve and append classical rules from classical knowledge base
        book_rules = search_local_index(natal_data)
        data_sheet += f"\nRETRIEVED CLASSICAL RULES FROM CELESTIAL KNOWLEDGE BASE:\n{book_rules}\n"
        
    except Exception as e:
        data_sheet = f"Error processing flattened layout strings: {e}"

    print("\n" + "="*70)
    print("      ASTROVEDA COMPLETE SHODASAVARGA MODEL GENERATION STREAM")
    print("="*70 + "\n")
    
    try:
        client = OpenAI()
        stream = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_blueprint},
                {"role": "user", "content": f"Execute full synthesis immediately using this raw data payload text. Do not output instructions or definition summaries under any circumstances:\n\n{data_sheet}"}
            ],
            temperature=0.1,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                print(chunk.choices[0].delta.content, end="", flush=True)
    except Exception as e:
        print(f"\n[Cloud Inference Failure]: {e}")

async def run_engine():
    master_engine_blueprint = load_system_blueprint("synthesis_engine.md")
    raw_dob = input("Enter Birth Date (YYYY-MM-DD) [1966-05-25]: ").strip() or "1966-05-25"
    tob = input("Enter Birth Time (HH:MM) [16:58]: ").strip() or "16:58"
    tz = input("Enter Timezone Offset [+05:30]: ").strip() or "+05:30"
    lat = float(input("Enter Latitude [8.9602]: ").strip() or "8.9602")
    lon = float(input("Enter Longitude [76.6788]: ").strip() or "76.6788")
    gender_choice = input("Select Gender (1=Female, 2=Male) [1]: ").strip() or "1"
    gender = "Male" if gender_choice == "2" else "Female"
    aya_choice = input("Select Ayanamsha (1=Lahiri, 2=Raman, 3=Pushya) [1]: ").strip() or "1"
    if aya_choice == "1":
        selected_ayanamsha = "lahiri"
    elif aya_choice == "2":
        selected_ayanamsha = "raman"
    elif aya_choice == "3":
        selected_ayanamsha = "pushya"
    else:
        selected_ayanamsha = "lahiri"
    pred_date = input("Enter Target Date [2030-12-31]: ").strip() or "2030-12-31"

    birth_metadata = {"birth_date": raw_dob, "birth_time": tob, "timezone_offset": tz, "latitude": lat, "longitude": lon, "gender": gender, "selected_ayanamsha": selected_ayanamsha, "target_prediction_date": pred_date}
    varshaphal_progression = calculate_tajika_progressions(raw_dob, pred_date)

    server_script = os.path.join(os.path.dirname(__file__), "server.py")
    server_parameters = StdioServerParameters(command=sys.executable, args=[server_script], env=os.environ.copy())
    
    try:
        async with stdio_client(server_parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                calculation_result = await session.call_tool("calculate_d1_chart", arguments={"dob": raw_dob, "tob": tob, "tz_offset": tz, "lat": lat, "lon": lon, "ayanamsha": selected_ayanamsha, "prediction_date": pred_date})
                natal_dataset = json.loads(calculation_result.content[0].text)
                # Prefer Claude; fall back to OpenAI if key not present
                anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
                if anthropic_key and anthropic_key != "YOUR_CLAUDE_API_KEY_HERE":
                    invoke_claude_engine(natal_dataset, varshaphal_progression, master_engine_blueprint, birth_metadata)
                else:
                    invoke_openai_cloud_engine(natal_dataset, varshaphal_progression, master_engine_blueprint, birth_metadata)
    except Exception as e:
        print(f"\n[System Failure]: {e}")

async def call_mcp_server(dob, tob, tz_offset, lat, lon, ayanamsha="raman", prediction_date="2026-05-26"):
    server_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")
    server_parameters = StdioServerParameters(command=sys.executable, args=[server_script], env=os.environ.copy())
    async with stdio_client(server_parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            calculation_result = await session.call_tool(
                "calculate_d1_chart", 
                arguments={
                    "dob": dob, 
                    "tob": tob, 
                    "tz_offset": tz_offset, 
                    "lat": lat, 
                    "lon": lon, 
                    "ayanamsha": ayanamsha, 
                    "prediction_date": prediction_date
                }
            )
            return json.loads(calculation_result.content[0].text)

def search_local_index(chart_data):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    index_path = os.path.join(base_dir, "indexed_knowledge.json")
    if not os.path.exists(index_path):
        return "No index file found."
    
    with open(index_path, "r", encoding="utf-8") as f:
        indexed_books = json.load(f)
    
    search_phrases = []
    
    # 1. Ascendant
    asc = chart_data.get("ascendant", {})
    if asc:
        sign = asc.get("sign")
        if sign:
            search_phrases.append(f"{sign} Lagna")
            search_phrases.append(f"Lagna in {sign}")
            search_phrases.append(f"Ascendant in {sign}")
    
    def add_planet_phrases(p_name, p_data):
        sign = p_data.get("sign")
        house = p_data.get("house")
        if sign:
            search_phrases.append(f"{p_name} in {sign}")
            search_phrases.append(f"{p_name} occupying {sign}")
        if house:
            def _ordinal(n):
                if 11 <= (n % 100) <= 13:
                    return f"{n}th"
                return f"{n}{['th','st','nd','rd'][min(n % 10, 3)]}"
            ord_str = _ordinal(house)
            search_phrases.append(f"{p_name} in the {ord_str}")
            search_phrases.append(f"{p_name} in {ord_str}")
            search_phrases.append(f"{p_name} in house {house}")
            search_phrases.append(f"{p_name} in the {house} house")
    
    # 2. Planets
    planets = chart_data.get("planets", {})
    for p_name, p_data in planets.items():
        add_planet_phrases(p_name, p_data)
        
    # 3. Upagrahas
    upagrahas = chart_data.get("upagrahas", {})
    for u_name, u_data in upagrahas.items():
        add_planet_phrases(u_name, u_data)
        
    # 4. Special Points
    special_points = chart_data.get("special_points", {})
    for sp_name, sp_data in special_points.items():
        if isinstance(sp_data, dict):
            add_planet_phrases(sp_name, sp_data)
    
    # 5. Yogas
    yogas = chart_data.get("yogas", {})
    for yoga_name, active in yogas.items():
        if active:
            yoga_clean = yoga_name.replace("_", " ")
            search_phrases.append(f"{yoga_clean} Yoga")
            search_phrases.append(yoga_clean)
            
    matches_general = []
    matches_narsimeha = []
    
    for book_entry in indexed_books:
        book_name = book_entry.get("book", "")
        is_narsimeha = book_name.lower() in ["narsimeha", "narsimeha2"]
        
        for page in book_entry.get("pages", []):
            text = page.get("text", "")
            page_num = page.get("page_number", 0)
            
            score = 0
            text_lower = text.lower()
            for phrase in search_phrases:
                if phrase.lower() in text_lower:
                    score += 1
            
            if score > 0:
                match_item = {
                    "book": book_name,
                    "page": page_num,
                    "text": text,
                    "score": score
                }
                if is_narsimeha:
                    matches_narsimeha.append(match_item)
                else:
                    matches_general.append(match_item)
    
    matches_general.sort(key=lambda x: x["score"], reverse=True)
    matches_narsimeha.sort(key=lambda x: x["score"], reverse=True)
    
    # Prioritize narsimeha/narsimeha2 matches alongside other classical literature, maintaining total of 2 matches
    top_matches = []
    if matches_narsimeha:
        top_matches.append(matches_narsimeha[0])
        if matches_general:
            top_matches.append(matches_general[0])
        elif len(matches_narsimeha) > 1:
            top_matches.append(matches_narsimeha[1])
    else:
        top_matches = matches_general[:2]
    
    formatted_results = ""
    for i, match in enumerate(top_matches, 1):
        formatted_results += f"--- Match {i} | Book: {match['book']} | Page: {match['page']} ---\n{match['text']}\n\n"
    
    if not formatted_results:
        if indexed_books and indexed_books[0]["pages"]:
            p1 = indexed_books[0]["pages"][0]
            p2 = indexed_books[0]["pages"][1] if len(indexed_books[0]["pages"]) > 1 else p1
            formatted_results += f"--- Match 1 | Book: {indexed_books[0]['book']} | Page: {p1['page_number']} ---\n{p1['text']}\n\n"
            formatted_results += f"--- Match 2 | Book: {indexed_books[0]['book']} | Page: {p2['page_number']} ---\n{p2['text']}\n\n"
        else:
            formatted_results = "No matches found."
            
    return formatted_results

def generate_reading_with_ollama(chart_json, book_rules, gender="Female", ayanamsha="Pushya", prediction_date="2026-05-25", dob=""):
    import requests
    url = "http://localhost:11434/api/generate"
    prompt = (
        f"Generate a beautiful, personalized Jyotish reading for a {gender} native born on {dob}.\n"
        f"Ayanamsha system: {ayanamsha}. Prediction anchor date: {prediction_date}.\n\n"
        f"Astrological Chart Data:\n{chart_json}\n\n"
        f"Classical rules retrieved from traditional books for matching planetary configurations:\n{book_rules}\n\n"
        f"Provide a short, rich 1-paragraph Vedic reading prioritizing these classical rules."
    )
    payload = {
        "model": "gemma",
        "prompt": prompt,
        "stream": True,
        "options": {
            "num_ctx": 8192
        }
    }
    print("Initiating Ollama generation stream...")
    try:
        response = requests.post(url, json=payload, stream=True, timeout=120)
        if response.status_code == 200:
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line.decode("utf-8"))
                    content = chunk.get("response", "")
                    print(content, end="", flush=True)
            print()
            return
    except Exception as e:
        log.warning("Ollama (gemma) unavailable, falling back: %s", e)
        
    payload["model"] = "gemma4:e4b"
    try:
        response = requests.post(url, json=payload, stream=True, timeout=120)
        if response.status_code == 200:
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line.decode("utf-8"))
                    content = chunk.get("response", "")
                    print(content, end="", flush=True)
            print()
            return
    except Exception as e:
        log.warning("Ollama (gemma4:e4b) unavailable, falling back to OpenAI: %s", e)
        
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        try:
            from openai import OpenAI
            client = OpenAI()
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a professional Jyotish astrologer."},
                    {"role": "user", "content": prompt}
                ]
            )
            print(completion.choices[0].message.content)
            return
        except Exception as e:
            print(f"\n[Fallback Error]: {e}")
    
    print("\n[All inference engines unavailable. Please verify Ollama is running or set a valid API key in your environment variables.]")

def main():
    asyncio.run(run_engine())

if __name__ == "__main__":
    main()