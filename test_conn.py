import httpx, time
t0 = time.time()
try:
    r = httpx.get("https://api.telegram.org", timeout=10)
    print("OK", r.status_code, time.time() - t0)
except Exception as e:
    print("GAGAL:", type(e).__name__, e, time.time() - t0)