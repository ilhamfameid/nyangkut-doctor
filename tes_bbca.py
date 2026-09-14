import requests, json, os
from dotenv import load_dotenv

load_dotenv()
key = os.getenv("SECTORS_API_KEY")

r = requests.get('https://api.sectors.app/v2/company/report/BBCA/?sections=overview,valuation,financials',
                 headers={'Authorization': key}, timeout=15)
d = r.json()

def find_by_prefix(obj, prefix, path=''):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.startswith(prefix):
                print(f'{path}.{k} = {v}')
            find_by_prefix(v, prefix, f'{path}.{k}')
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            find_by_prefix(v, prefix, f'{path}[{i}]')

print('=== Cari pb ===')
find_by_prefix(d, 'pb')
print()
print('=== Cari pe ===')
find_by_prefix(d, 'pe')
