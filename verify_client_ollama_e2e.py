import asyncio
import json
import sys
from client import call_mcp_server, search_local_index, generate_reading_with_ollama

async def diagnostic_run():
    print("=== ASTROVEDA DIAGNOSTIC RUN ===")
    dob = "1966-08-29"
    tob = "03:15"
    tz_offset = "+05:30"
    lat = 9.267
    lon = 76.55
    
    # Step 1: Call local MCP Server
    try:
        print("\n[1/3] Querying local D1 Chart calculations from FastMCP using PUSHYA Ayanamsha and prediction_date 2026-05-25...")
        chart_data = await call_mcp_server(dob, tob, tz_offset, lat, lon, ayanamsha="pushya", prediction_date="2026-05-25")
        print("Success! Calculated Chart:")
        print(json.dumps(chart_data, indent=2))
    except Exception as e:
        print(f"Failed to query MCP server: {e}")
        sys.exit(1)
        
    # Step 2: Search local knowledge (Hardcoded diagnostic rule)
    print("\n[2/3] Getting RAG matching rules (Hardcoded diagnostic)...")
    book_rules = search_local_index(chart_data)
    print(f"Rules: '{book_rules}'")
    
    # Step 3: Query local Ollama instance (Streaming)
    print("\n[3/3] Sending to local Ollama and streaming response (testing Female Horoscopy + Pushya + Gochara pivot):")
    generate_reading_with_ollama(json.dumps(chart_data), book_rules, gender="Female", ayanamsha="Pushya", prediction_date="2026-05-25", dob=dob)
    print("\n=== DIAGNOSTIC RUN COMPLETED ===")

if __name__ == "__main__":
    asyncio.run(diagnostic_run())
