"""
Debug script - cek struktur mentah respons Sectors API
Jalankan: python debug_sectors.py BBCA
"""
import json
import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

SECTORS_API_KEY = os.getenv("SECTORS_API_KEY")
SECTORS_API_BASE = "https://api.sectors.app/v2"

ticker = sys.argv[1].upper() if len(sys.argv) > 1 else "BBCA"

url = f"{SECTORS_API_BASE}/company/report/{ticker}/"
headers = {"Authorization": SECTORS_API_KEY}
params = {"sections": "overview,valuation,financials,peers"}

resp = requests.get(url, headers=headers, params=params, timeout=15)
print(f"Status: {resp.status_code}")
print(f"URL: {resp.url}")
print("-" * 60)

try:
    data = resp.json()
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print("-" * 60)
    print("Top-level keys:", list(data.keys()) if isinstance(data, dict) else type(data))
    if isinstance(data, dict):
        if "valuation" in data:
            print("valuation keys:", list((data["valuation"] or {}).keys()))
        if "financials" in data:
            print("financials keys:", list((data["financials"] or {}).keys()))
except Exception as e:
    print(f"Bukan JSON valid: {e}")
    print(resp.text[:2000])