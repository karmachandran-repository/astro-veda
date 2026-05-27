import json
import sys
from server import calculate_d1_chart

dob = "1966-08-29"
tob = "03:15"
tz_offset = "+05:30"
lat = 9.267
lon = 76.55

print(f"Calculating chart for {dob} {tob} {tz_offset} ({lat}, {lon})...")
res_str = calculate_d1_chart(dob, tob, tz_offset, lat, lon)
print("Result JSON:")
print(res_str)
