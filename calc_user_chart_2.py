import json
from server import calculate_d1_chart

dob = "1995-07-20"
tob = "13:51"
tz_offset = "+05:30"
lat = 8.95893
lon = 76.67649

print(f"Calculating chart for {dob} {tob} {tz_offset} ({lat}, {lon})...")
res_str = calculate_d1_chart(dob, tob, tz_offset, lat, lon)
print("Result JSON:")
print(res_str)
