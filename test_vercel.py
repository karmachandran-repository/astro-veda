import time
import urllib.request

url = "https://astro-veda-f99a.vercel.app/api/prediction/stream"
print(f"Streaming from Vercel: {url} ...")
start_time = time.time()
try:
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=60) as response:
        print(f"Status: {response.status}")
        while True:
            line = response.readline().decode('utf-8')
            if not line:
                break
            print(line.strip())
    print(f"\nStream completed successfully in {time.time() - start_time:.2f} seconds.")
except Exception as e:
    print(f"\nError after {time.time() - start_time:.2f} seconds: {e}")

