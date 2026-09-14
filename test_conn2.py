import asyncio, time
from dotenv import load_dotenv
import os, httpx

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def main():
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"https://api.telegram.org/bot{TOKEN}/getMe")
            print("OK", r.status_code, r.text[:200], time.time() - t0)
    except Exception as e:
        print("GAGAL:", type(e).__name__, e, time.time() - t0)

asyncio.run(main())