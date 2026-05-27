import requests
import json

api_key = "FreeAPIUser"
# Let's check what the server parsed for the user's specific birth time URL
url = "https://api.vedastro.org/api/Calculate/PlanetNirayanaLongitude/PlanetName/Sun/Time/13:51/20/07/1995/+05:30/Location/8.95893,76.67649/76.67649/8.95893/Ayanamsa/Raman"

print(f"Testing URL: {url}")
try:
    headers = {"x-api-key": api_key}
    res = requests.get(url, headers=headers, timeout=30)
    print(f"Status Code: {res.status_code}")
    data = res.json()
    params = data.get("Input", {}).get("Parameters", [])
    for p in params:
        if p.get("Name") == "time":
            print("Parsed Time structure:")
            print(json.dumps(p.get("Value"), indent=2))
except Exception as e:
    print(f"Failed: {e}")
