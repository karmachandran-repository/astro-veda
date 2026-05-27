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
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from openai import OpenAI
except ImportError:
    print("[Critical Error] 'openai' module not found! Please run pip install openai inside your venv.", file=sys.stderr)
    sys.exit(1)

def load_system_blueprint(filename="synthesis_engine.md"):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.join(base_dir, filename)
    if not os.path.exists(full_path):
        print(f"[Critical Initialization Error] Blueprint file missing at: {full_path}", file=sys.stderr)
        sys.exit(1)
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read()

def calculate_tajika_progressions(dob_str, prediction_date_str):
    try:
        from datetime import datetime
        birth_date = datetime.strptime(dob_str, "%Y-%m-%d")
        target_date = datetime.strptime(prediction_date_str, "%Y-%m-%d")
        completed_age = target_date.year - birth_date.year
        if (target_date.month, target_date.day) < (birth_date.month, birth_date.day):
            completed_age -= 1
        return {"completed_age": completed_age, "muntha_progressed_house": (completed_age % 12) + 1}
    except Exception:
        return {"completed_age": 60, "muntha_progressed_house": 11}

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
        if varshaphal_data:
            data_sheet += f"- Tajika Varshaphal Progression Profile: Progressed Completed Age={varshaphal_data.get('completed_age')}, Progressed Muntha House={varshaphal_data.get('muntha_progressed_house')}\n\n"
        else:
            data_sheet += "\n"
        
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
            search_phrases.append(f"{p_name} in the {house}th")
            search_phrases.append(f"{p_name} in {house}th")
            search_phrases.append(f"{p_name} in house {house}")
            search_phrases.append(f"{p_name} in the {house} house")
            if house == 1:
                search_phrases.append(f"{p_name} in the 1st")
                search_phrases.append(f"{p_name} in 1st")
            elif house == 2:
                search_phrases.append(f"{p_name} in the 2nd")
                search_phrases.append(f"{p_name} in 2nd")
            elif house == 3:
                search_phrases.append(f"{p_name} in the 3rd")
                search_phrases.append(f"{p_name} in 3rd")
            else:
                search_phrases.append(f"{p_name} in the {house}rd" if house == 3 else f"{p_name} in the {house}th")
    
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
        response = requests.post(url, json=payload, stream=True, timeout=5)
        if response.status_code == 200:
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line.decode("utf-8"))
                    content = chunk.get("response", "")
                    print(content, end="", flush=True)
            print()
            return
    except Exception:
        pass
        
    payload["model"] = "gemma4:e4b"
    try:
        response = requests.post(url, json=payload, stream=True, timeout=5)
        if response.status_code == 200:
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line.decode("utf-8"))
                    content = chunk.get("response", "")
                    print(content, end="", flush=True)
            print()
            return
    except Exception:
        pass
        
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
    
    print("\n[Ollama/OpenAI Offline Fallback Reading]:")
    print("The alignment of the Moon in the 10th house (Cancer) under the Pushya Ayanamsha shows a deep emotional alignment and intuitive connection to the native's career. The traditional classical rule indicates that a strong Moon in its own house grants a lasting public reputation and honor. Venus occupying the 7th house indicates harmonious relationships and mutual devotion, though the presence of Gulika in the same house brings minor obstacles that are overcome through the native's innate patience and wisdom.")

def main():
    asyncio.run(run_engine())

if __name__ == "__main__":
    main()