# tes_nyangkut.py - mock test tanpa Sectors API key

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import asyncio


class MockSectors:
    _data = {
        "BBRI": {
            "name": "Bank Rakyat Indonesia",
            "ticker": "BBRI",
            "sector": "Financials",
            "sub_sector": "Banks",
            "pbv": 2.1,
            "pe": 12.4,
            "revenue": "Rp 42 triliun (2025)",
            "net_income": "Rp 18,7 triliun (2025)",
            "current_price": 4750,
        },
        "BBCA": {
            "name": "Bank Central Asia",
            "ticker": "BBCA",
            "sector": "Financials",
            "sub_sector": "Banks",
            "pbv": 3.8,
            "pe": 18.2,
            "revenue": "Rp 35 triliun (2025)",
            "net_income": "Rp 21,3 triliun (2025)",
            "current_price": 9800,
        },
        "BMRI": {
            "name": "Bank Mandiri",
            "ticker": "BMRI",
            "sector": "Financials",
            "sub_sector": "Banks",
            "pbv": 1.9,
            "pe": 11.1,
            "revenue": "Rp 38 triliun (2025)",
            "net_income": "Rp 15,2 triliun (2025)",
            "current_price": 4200,
        },
    }
    _daily = {
        "BBRI": [{"close": 4800}, {"close": 4780}, {"close": 4750}],
        "BBCA": [{"close": 9900}, {"close": 9850}, {"close": 9800}],
        "BMRI": [{"close": 4250}, {"close": 4230}, {"close": 4200}],
    }

    @staticmethod
    def company_report(ticker):
        return MockSectors._data.get(ticker.upper(), {})

    @staticmethod
    def peers(ticker, limit=4):
        sec = MockSectors._data.get(ticker.upper(), {}).get("sector", "")
        if not sec:
            return []
        result = []
        for k, v in MockSectors._data.items():
            if v.get("sector") == sec and k != ticker.upper():
                result.append(v.copy())
                if len(result) >= limit:
                    break
        return result

    @staticmethod
    def daily(ticker):
        return MockSectors._daily.get(ticker.lower(), [])


# Override fungsi di main.py sebelum import handler
import main as m
m.fetch_company = MockSectors.company_report
m.fetch_peers   = lambda t, limit=4: MockSectors.peers(t, limit)
m.fetch_daily   = MockSectors.daily

# Mock LLM: balikin teks statis per ticker biar test output akhir
m.LLM_API_KEY = None
_MOCK_RESPONSES = {
    "BBRI": ("[DIAGNOSA]         : Sehat\n"
             "[ALASAN SINGKAT]   : Laba masih tumbuh, PBV 2.10x di bawah rerata sektor 2.40x.\n"
             "[KONTRUKSI]:\n"
             "| Item           | Nilai Anda | Rerata Sektor      | Status     |\n"
             "|----------------|------------|--------------------|------------|\n"
             "| PBV            | 2.10x      | 2.40x (dari tabel di atas) | murah      |\n"
             "| PE             | 12.4x      | -                  | -          |\n"
             "| Harga vs Beli  | -8.65%     | -                  | loss       |\n"
             "[CATATAN]         : Data laba hanya 1 periode, belum bisa melihat tren"),
    "BBCA": ("[DIAGNOSA]         : Waspada\n"
             "[ALASAN SINGKAT]   : PBV 3.80x jauh di atas rerata sektor 2.40x, valuasi expensive.\n"
             "[KONTRUKSI]:\n"
             "| Item           | Nilai Anda | Rerata Sektor      | Status     |\n"
             "|----------------|------------|--------------------|------------|\n"
             "| PBV            | 3.80x      | 2.40x (dari tabel di atas) | mahal      |\n"
             "| PE             | 18.2x      | -                  | -          |\n"
             "| Harga vs Beli  | -1.02%     | -                  | loss       |\n"
             "[CATATAN]         : Data laba hanya 1 periode, belum bisa melihat tren"),
    "BMRI": ("[DIAGNOSA]         : Sehat\n"
             "[ALASAN SINGKAT]   : PBV 1.90x paling murah sektor, laba stabil.\n"
             "[KONTRUKSI]:\n"
             "| Item           | Nilai Anda | Rerata Sektor      | Status     |\n"
             "|----------------|------------|--------------------|------------|\n"
             "| PBV            | 1.90x      | 2.40x (dari tabel di atas) | murah      |\n"
             "| PE             | 11.1x      | -                  | -          |\n"
             "| Harga vs Beli  | -6.67%     | -                  | loss       |\n"
             "[CATATAN]         : Data laba hanya 1 periode, belum bisa melihat tren"),
}


async def mock_llm(prompt, system=""):
    # Deteksi ticker dari prompt
    for ticker in _MOCK_RESPONSES:
        if f"({ticker})" in prompt.upper():
            return _MOCK_RESPONSES[ticker]
    return _MOCK_RESPONSES["BBRI"]


m.call_llm = mock_llm


async def test_ticker(ticker, buy_price=None):
    print(f"\n=== TEST: {ticker} @ {buy_price} ===")
    sys.stdout.flush()

    class MockMsg:
        text = f"{ticker} {buy_price}" if buy_price else ticker
        async def reply_text(self, txt, **kw):
            print(f"  >> BOT: {txt}")

    class MockUpdate:
        message = MockMsg()

    await m.handle_message(MockUpdate(), None)


if __name__ == "__main__":
    asyncio.run(test_ticker("BBRI", 5200))
    asyncio.run(test_ticker("BBCA"))
    asyncio.run(test_ticker("BMRI", 4500))
