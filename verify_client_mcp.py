import asyncio
import sys
from client import call_mcp_server

async def test():
    print("--- Running client-to-server end-to-end verification ---")
    dob = "2010-12-31"
    tob = "23:40"
    tz_offset = "+08:00"
    lat = 35.65
    lon = 139.83
    
    try:
        chart_data = await call_mcp_server(dob, tob, tz_offset, lat, lon)
        print("Successfully queried MCP server from client!")
        print(chart_data)
        
        # Verify the key fields are populated correctly
        assert chart_data["ascendant"]["sign"] == "Virgo"
        assert chart_data["upagrahas"]["Gulika"]["sign"] == "Capricorn"
        assert len(chart_data["planets"]) == 9
        print("\nSUCCESS: End-to-end MCP client-to-server verification passed perfectly!")
    except Exception as e:
        print(f"\nFAILED end-to-end verification: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(test())
