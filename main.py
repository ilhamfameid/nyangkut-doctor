# Nyangkut Doctor - Sectors Hackathon 2026
# Telegram bot: analisis kesehatan fundamental saham IDX
# Versi: 2.3 - Public Ready: Non-blocking Airtable, User Tracking,
#              Calculated Floating P/L & Multi-column Logging

import os
import time
from dotenv import load_dotenv
from typing import Optional

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(_PROJECT_DIR, ".env"))

import re, json, asyncio, urllib.parse
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from zoneinfo import ZoneInfo
from datetime import datetime, time as dt_time

from supabase_helper import (
    get_or_create_user,
    save_analysis,
    get_user_analyses,
    count_user_watchlist,
    get_user_watchlist,
    add_watchlist_entry,
    remove_watchlist_entry,
    get_all_watchlist_entries,
    update_watchlist_snapshot,
    get_telegram_id_by_user_id,
)

SECTORS_API_KEY    = os.getenv("SECTORS_API_KEY").strip() if os.getenv("SECTORS_API_KEY") else None
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LLM_BASE_URL       = os.getenv("LLM_BASE_URL", "http://localhost:20128/v1")
LLM_API_KEY        = os.getenv("HERMES_CUSTOM_LOCALHOST_20128_API_KEY") or os.getenv("LLM_API_KEY")
LLM_MODEL          = os.getenv("LLM_MODEL", "NyangkutDoctorBot")

SECTORS_API_BASE = "https://api.sectors.app/v2"
TICKER_RE = re.compile(r"^([A-Z]{4})(?:\.JK)?\s*(\d+(?:\.\d+)?)?$", re.IGNORECASE)

# -- Airtable logging config (sudah tidak dipakai — hanya Supabase yang aktif)
AIRTABLE_API_KEY    = os.getenv("AIRTABLE_API_KEY") or os.getenv("AIRTABLE_PAT")
AIRTABLE_BASE_ID    = os.getenv("AIRTABLE_BASE_ID", "appwvMn6T211Ch7dh")
AIRTABLE_TABLE_NAME = os.getenv("AIRTABLE_TABLE_NAME", "Table 1")
AIRTABLE_URL        = os.getenv("AIRTABLE_URL", "https://airtable.com/appwvMn6T211Ch7dh/shrRUfKjrblwcFgm0")

def norm_ticker(t: Optional[str]) -> str:
    """Samain format ticker: buang suffix .JK, uppercase."""
    if not t:
        return ""
    return t.strip().upper().split(".")[0]

def format_rupiah(val):
    if val is None or val == "":
        return "N/A"
    if isinstance(val, (int, float)):
        abs_val = abs(val)
        if abs_val >= 1e12:
            return f"Rp {val / 1e12:.2f} Triliun"
        elif abs_val >= 1e9:
            return f"Rp {val / 1e9:.2f} Miliar"
        elif abs_val >= 1e6:
            return f"Rp {val / 1e6:.2f} Juta"
        return f"Rp {val:,.0f}"
    return str(val)

def sectors_get(path: str, params: Optional[dict] = None, max_retries: int = 3) -> dict:
    url = f"{SECTORS_API_BASE}{path}"
    headers = {"Authorization": SECTORS_API_KEY}
    
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            
            if resp.status_code == 429:
                # Cek dulu: apakah ini karena kredit habis atau rate limit biasa?
                try:
                    error_body = resp.json()
                    error_type = error_body.get("error", "") or error_body.get("detail", "")
                except Exception:
                    error_type = ""
                
                if error_type == "INSUFFICIENT_CREDITS":
                    # Kredit habis — jangan retry, langsung raise
                    raise Exception("Kredit API Sectors habis. Silakan isi ulang.")
                
                # Bukan soal kredit — lanjut retry dengan exponential backoff
                wait_time = 2 ** attempt  # 2s, 4s, 8s
                print(f"[RateLimit] 429 pada {path} — tunggu {wait_time}s (percobaan {attempt}/{max_retries})")
                time.sleep(wait_time)
                continue
            
            resp.raise_for_status()
            return resp.json()
            
        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt < max_retries:
                wait_time = 2 ** attempt
                print(f"[Warning] Error pada {path} — tunggu {wait_time}s (percobaan {attempt}/{max_retries})")
                time.sleep(wait_time)
            continue
    
    # Kalau semua percobaan gagal
    raise last_error or Exception(f"Gagal setelah {max_retries} percobaan: {path}")

def fetch_company(ticker: str) -> dict:
    return sectors_get(f"/company/report/{ticker}/", {"sections": "overview,valuation,financials"})

def _run_screener(where_clause: str, limit: int) -> list:
    try:
        data = sectors_get("/companies/", {
            "where": where_clause,
            "order_by": "-market_cap",
            "limit": limit,
        })
    except Exception as e:
        print(f"[Warning] Screener gagal ({where_clause}): {e}")
        return []
    if isinstance(data, dict):
        rows = data.get("results", [])
    elif isinstance(data, list):
        rows = data
    else:
        rows = []
    return rows if isinstance(rows, list) else []

def fetch_peers(sub_sector: Optional[str], sector: Optional[str], current_ticker: str, limit: int = 4) -> list:
    cur = norm_ticker(current_ticker)
    fetch_limit = limit * 2

    def collect(where_clause):
        rows = _run_screener(where_clause, fetch_limit + 1)
        out = []
        for r in rows:
            sym = norm_ticker(r.get("symbol") or r.get("ticker"))
            if sym and sym != cur:
                out.append({"ticker": sym, "company_name": r.get("company_name") or sym})
        return out[:fetch_limit]

    candidates = []
    if sub_sector:
        candidates.append(collect(f"sub_sector = '{sub_sector.replace(chr(39), chr(39)*2)}'"))
    if sector:
        candidates.append(collect(f"sector = '{sector.replace(chr(39), chr(39)*2)}'"))

    rows = next((c for c in candidates if c), [])
    if not rows:
        return []

    peers = []
    for r in rows:
        try:
            url = f"{SECTORS_API_BASE}/company/report/{r['ticker']}/"
            headers = {"Authorization": SECTORS_API_KEY}
            resp = requests.get(url, headers=headers, params={"sections": "valuation,overview"}, timeout=30)
            if resp.status_code == 200:
                rep = resp.json()
                peers.append({
                    "ticker": r["ticker"],
                    "company_name": r["company_name"],
                    "pb": get_field(rep, "pb_mrq", "pb", "pbv", "price_to_book", "pbvRatio", "pb_ratio"),
                    "sector": get_field(rep, "sector", "sub_sector"),
                })
        except Exception as e:
            print(f"[Warning] Skip peer {r['ticker']} karena timeout/error: {e}")
            continue

    return peers

_DATE_KEYS = ("date", "trading_date", "day", "timestamp")

def _get_date_key(item: dict):
    for k in _DATE_KEYS:
        if k in item and item[k]:
            return item[k]
    return None

def fetch_daily(ticker: str) -> list:
    data = sectors_get(f"/daily/{ticker.lower()}/")
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = None
        for key in ("data", "results"):
            val = data.get(key)
            if isinstance(val, list):
                rows = val
                break
        rows = rows or []
    else:
        rows = []

    if rows and isinstance(rows[0], dict) and _get_date_key(rows[0]) is not None:
        rows = sorted(rows, key=lambda x: _get_date_key(x))
    elif rows:
        print(f"[Warning] Data daily {ticker} tidak punya field tanggal dikenal "
              f"({_DATE_KEYS}) - urutan diasumsikan sudah kronologis dari API.")
    return rows

NESTED_CONTAINERS = ("overview", "valuation", "financials", "peers_comparison", "historical_valuation", "quarterly", "annual")

def get_field(obj, *candidates):
    if isinstance(obj, dict):
        for key in candidates:
            if key in obj and obj[key] not in (None, ""):
                return obj[key]
        for container in NESTED_CONTAINERS:
            if container in obj:
                res = get_field(obj[container], *candidates)
                if res not in (None, ""):
                    return res
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and k not in NESTED_CONTAINERS:
                res = get_field(v, *candidates)
                if res not in (None, ""):
                    return res
    elif isinstance(obj, list) and len(obj) > 0:
        if all(isinstance(item, dict) for item in obj) and any("year" in item for item in obj):
            items_sorted = sorted(obj, key=lambda x: x.get("year", 0), reverse=True)
        else:
            items_sorted = obj
        for item in items_sorted:
            res = get_field(item, *candidates)
            if res not in (None, ""):
                return res
    return None

def safe_num(val):
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None

def get_eps_growth(company):
    hist_eps = company.get("financials", {}).get("historical_eps", {})
    if not hist_eps:
        return None
    years = sorted(hist_eps.keys(), reverse=True)
    if len(years) >= 2:
        latest = safe_num(hist_eps[years[0]].get("eps"))
        prev = safe_num(hist_eps[years[1]].get("eps"))
        if latest is not None and prev is not None and prev != 0:
            return ((latest - prev) / abs(prev)) * 100
    return None

def get_der(company):
    hist = company.get("financials", {}).get("historical_financials", [])
    if not hist:
        return None
    latest = sorted(hist, key=lambda x: x.get("year", 0), reverse=True)[0]
    debt = safe_num(latest.get("total_debt"))
    equity = safe_num(latest.get("total_equity"))
    if debt is not None and equity is not None and equity != 0:
        return debt / equity
    netdebt = safe_num(latest.get("net_debt"))
    if netdebt is not None and equity is not None and equity != 0:
        return netdebt / equity
    return None

def get_fcf(company):
    hist = company.get("financials", {}).get("historical_financials", [])
    if not hist:
        return None
    latest = sorted(hist, key=lambda x: x.get("year", 0), reverse=True)[0]
    return latest.get("free_cash_flow")

async def call_llm(prompt: str, system: str = "") -> str:
    if not LLM_API_KEY:
        return "[LLM dimatikan - isi HERMES_CUSTOM_LOCALHOST_20128_API_KEY di .env dulu]"

    payload = {
        "model": LLM_MODEL,
        "messages": ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ],
        "stream": False,
        "max_tokens": 600,
        "temperature": 0.3,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}",
        "User-Agent": "Mozilla/5.0"
    }

    url = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"

    def _do_post():
        resp = requests.post(url, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        return resp.json()

    body = await asyncio.to_thread(_do_post)
    msg = body["choices"][0]["message"]
    return msg.get("content", "") or msg.get("text", "")

def build_prompt(ticker: str, buy_price: float, company: dict, peers: list, daily: list, user_name: str) -> tuple:
    pv     = get_field(company, "pb_mrq", "pb", "pbv", "price_to_book", "pbvRatio", "pb_ratio")
    if pv is None:
        hist_val = company.get("valuation", {}).get("historical_valuation", [])
        if hist_val:
            pv = hist_val[-1].get("pb")

    pe     = get_field(company, "pe_ttm", "pe", "price_to_earnings", "peRatio", "pe_ratio")
    if pe is None:
        pe = company.get("valuation", {}).get("forward_pe")
    sector = get_field(company, "sector", "industry")

    rev_raw = get_field(company, "total_revenue_mrq", "revenue", "total_revenue", "revenue_ttm", "latest_revenue", "sales")
    ni_raw  = get_field(company, "earnings_mrq", "net_income", "netProfit", "netIncome", "net_profit", "net_income_ttm")

    hist_fin = company.get("financials", {}).get("historical_financials", [])
    if isinstance(hist_fin, list) and len(hist_fin) > 0:
        latest_fin = sorted(hist_fin, key=lambda x: x.get("year", 0), reverse=True)[0]
        if ni_raw is None:
            ni_raw = latest_fin.get("net_income") or latest_fin.get("net_profit") or latest_fin.get("earnings")
        if rev_raw is None:
            rev_raw = latest_fin.get("total_revenue") or latest_fin.get("revenue")

    rev = format_rupiah(rev_raw)
    ni  = format_rupiah(ni_raw)

    valuation_data = company.get("valuation", {})
    hist_val = valuation_data.get("historical_valuation", [])
    avg_pbv_hist = None
    avg_pbv_hist_str = "N/A"

    if isinstance(hist_val, list) and len(hist_val) > 0:
        pbv_list = [safe_num(item.get("pb")) for item in hist_val if safe_num(item.get("pb")) is not None]
        if pbv_list:
            avg_pbv_hist = sum(pbv_list) / len(pbv_list)
            avg_pbv_hist_str = f"{avg_pbv_hist:.2f}x"

    eps_disp = "N/A"
    eps_raw = get_field(company, "eps", "eps_ttm", "earnings_per_share")
    if safe_num(eps_raw) is not None:
        eps_disp = f"{safe_num(eps_raw):.2f}"

    eps_growth = get_eps_growth(company)
    eps_growth_str = f"{eps_growth:.2f}%" if eps_growth is not None else "N/A"
    der_raw = get_der(company)
    der_str = f"{der_raw:.2f}x" if der_raw is not None else "N/A"
    fcf_raw = get_fcf(company)
    fcf_str = format_rupiah(fcf_raw)

    name   = get_field(company, "name", "long_name", "company_name") or ticker
    current_price = get_field(company, "current_price", "last_close_price", "close", "last_price")

    now_price = daily[-1].get("close") if daily and isinstance(daily[-1], dict) else (current_price if current_price is not None else "N/A")
    if isinstance(now_price, (int, float)) and buy_price > 0:
        loss_pct = (now_price - buy_price) / buy_price * 100
        loss_str = f"{loss_pct:.2f}%"
    else:
        loss_pct = "N/A"
        loss_str = "N/A"

    pv_f = float(pv) if isinstance(pv, (int, float)) else None
    pe_f = float(pe) if isinstance(pe, (int, float)) else None

    pv_disp   = f"{pv_f:.2f}x" if pv_f is not None else str(pv if pv is not None else "N/A")
    pe_disp   = f"{pe_f:.1f}x" if pe_f is not None else str(pe if pe is not None else "N/A")
    loss_disp = loss_str

    peer_block = ""
    avg_pbv = None
    cheapest_peers_block = ""
    if peers:
        pbv_vals = []
        for p in peers:
            tp = p.get("ticker", "?")
            pp = p.get("pb")
            ps = p.get("sector") or "?"
            if isinstance(pp, (int, float)):
                pbv_vals.append((tp, pp, ps))
        if pbv_vals:
            avg_pbv = sum(v for _, v, _ in pbv_vals) / len(pbv_vals)
            peer_block = "Emiten sejenis (sama sektor):\n"
            for tp, pp, ps in pbv_vals:
                peer_block += f"  - {tp}: PBV {pp:.2f}x - {ps}\n"
            peer_block += f"  -> Rerata PBV sektor: {avg_pbv:.2f}x\n"

            cheapest = sorted(pbv_vals, key=lambda x: x[1])[:3]
            cheapest_peers_block = "Kandidat substitusi termurah (PBV ascending):\n"
            for tp, pp, ps in cheapest:
                cheapest_peers_block += f"  - {tp}: PBV {pp:.2f}x - {ps}\n"

    buy_price_str = "tidak diketahui" if buy_price <= 0 else f"{buy_price:,.0f}"
    avg_pbv_str = f"{avg_pbv:.2f}x" if avg_pbv is not None else "N/A"
    avg_pbv_note = f"{avg_pbv_str} (dari tabel)" if peer_block else "belum tersedia"

    pbv_status = "murah" if (pv_f is not None and avg_pbv_hist is not None and pv_f < avg_pbv_hist) else ("mahal" if (pv_f is not None and avg_pbv_hist is not None) else "-")
    price_status = "loss" if (isinstance(loss_pct, (int, float)) and loss_pct < 0) else ("profit" if isinstance(loss_pct, (int, float)) else "-")
    der_status = "wajar bank" if (sector and sector.lower() == "financials") else "-"
    eps_growth_status = "rendah" if (eps_growth is not None and eps_growth < 5) else "-"

    flag_lines = []
    if ni_raw is None:
        flag_lines.append("LABA BERSIH TIDAK ADA DI DATA.")
    if pv_f is not None and avg_pbv_hist is not None and pv_f > avg_pbv_hist * 1.5:
        flag_lines.append(f"PBV PREMIUM vs HISTORIS: {pv_f:.2f}x vs rerata historis {avg_pbv_hist:.2f}x.")
    if pv_f is not None and avg_pbv is not None and pv_f > avg_pbv * 1.5:
        ratio = pv_f / avg_pbv
        flag_lines.append(f"PBV PREMIUM SECTOR: {pv_f:.2f}x vs rerata sektor {avg_pbv:.2f}x ({ratio:.1f}x lebih mahal dari rerata).")
    if eps_growth is not None and eps_growth < 5:
        flag_lines.append(f"EPS GROWTH RENDAH: {eps_growth:.2f}%.")

    flag_block = ""
    if flag_lines:
        flag_block = "[FLAGGED ISSUES]:\n" + "\n".join(f"  - {f}" for f in flag_lines) + "\n"

    der_note = ""
    if sector and sector.lower() == "financials":
        der_note = (
            "\n[CATATAN PERBANKAN] DER di atas dihitung dari utang berbunga terhadap "
            "ekuitas, bukan total liabilitas. Untuk bank angka ini wajar terlihat kecil "
            "karena simpanan nasabah (dana pihak ketiga) tidak masuk hitungan sebagai utang."
        )

    prompt = f"""Analisakan kesehatan fundamental emiten {name} ({ticker}) untuk investor ritel di harga {buy_price_str}.

Data:
[HARGA] Beli       : {buy_price_str} | Terkini: {now_price} | Floating P/L: {loss_disp}
[VALUASI] PBV      : {pv_disp} | PE: {pe_disp} | Sektor: {sector or "N/A"} | Rerata PBV Historis: {avg_pbv_hist_str}
[FAKTA] Revenue    : {rev} | Laba: {ni} | EPS: {eps_disp} | EPS Growth: {eps_growth_str}
[FINANSIAL] DER (utang berbunga/ekuitas): {der_str} | FCF: {fcf_str}
{peer_block}
{cheapest_peers_block}
{flag_block}Format jawaban:
[DIAGNOSA]         : [Sehat / Waspada / Kritis / Data terbatas]
[ALASAN SINGKAT]   : [1-2 kalimat]
[KONSTRUKSI METRIK]:
PBV: {pv_disp} (Sektor: {avg_pbv_note} | Hist: {avg_pbv_hist_str}) — {pbv_status}
PE: {pe_disp} — -
Harga vs Beli: {loss_disp} — {price_status}
DER: {der_str} — {der_status}
EPS Growth YoY: {eps_growth_str} — {eps_growth_status}

[RESEP DOKTER]    : [Kesimpulan hold/cut loss + saran substitusi jika mahal, pakai daftar "Kandidat substitusi termurah" jika ada]
[CATATAN]         : 1 kalimat batasan data{der_note}
"""

    # airtable_data = {
    #     "user_name": user_name,
    #     "ticker": ticker,
    #     "buy_price_num": buy_price if buy_price else 0,
    #     "now_price": now_price if isinstance(now_price, (int, float)) else str(now_price),
    #     "pv": pv_disp,
    #     "pe": pe_disp,
    #     "sector": sector or "N/A",
    # }

    return prompt #airtable_data


def calculate_radar_scores(company: dict, diagnosis: str) -> dict:
    val = company.get("valuation", {})
    financials = company.get("financials", {})
    overview = company.get("overview", {})

    hist_val = val.get("historical_valuation", [])
    current_pbv = hist_val[-1].get("pb") if hist_val else None
    peer_pbv_avg = hist_val[-1].get("pb_peer_avg") if hist_val else None
    forward_pe = val.get("forward_pe")
    market_cap_rank = overview.get("market_cap_rank")
    sector_tags = overview.get("tags", [])

    eps_hist = financials.get("historical_eps", {})
    eps_years = sorted(eps_hist.keys(), reverse=True)
    if len(eps_years) >= 2:
        latest_eps = eps_hist[eps_years[0]].get("eps")
        prev_eps = eps_hist[eps_years[1]].get("eps")
        if latest_eps and prev_eps and prev_eps != 0:
            eps_growth = ((latest_eps - prev_eps) / abs(prev_eps)) * 100
            future_score = max(20, min(95, 50 + eps_growth * 2))
        else:
            future_score = 50
    else:
        future_score = 50

    if current_pbv and peer_pbv_avg and peer_pbv_avg > 0:
        ratio = current_pbv / peer_pbv_avg
        value_score = max(10, min(95, 100 - (ratio - 1) * 12))
    else:
        value_score = 50

    if market_cap_rank:
        competitive_score = max(10, min(100, 50 + (5 - market_cap_rank) * 10))
    else:
        competitive_score = 50

    if forward_pe:
        financials_score = max(20, min(95, 100 - forward_pe * 3))
    else:
        financials_score = 50

    has_dividend = "dividend-yield-ttm-above-5-percent" in sector_tags
    dividend_score = 65 if has_dividend else 30

    return {
        "value": round(value_score, 1),
        "competitive": round(competitive_score, 1),
        "financials": round(financials_score, 1),
        "future": round(future_score, 1),
        "dividend": round(dividend_score, 1),
    }


def generate_radar_chart_url(ticker: str, metrics: dict) -> str:
    labels = ["Value", "Competitive", "Financials", "Future", "Dividend"]
    data = [
        metrics.get("value", 50),
        metrics.get("competitive", 50),
        metrics.get("financials", 50),
        metrics.get("future", 50),
        metrics.get("dividend", 50),
    ]

    chart_config = {
        "type": "radar",
        "data": {
            "labels": labels,
            "datasets": [{
                "label": ticker,
                "data": data,
                "backgroundColor": "rgba(54, 162, 235, 0.2)",
                "borderColor": "rgb(54, 162, 235)",
                "pointBackgroundColor": "rgb(54, 162, 235)",
                "pointBorderColor": "#fff",
                "pointRadius": 5,
                "fill": True,
            }]
        },
        "options": {
            "responsive": True,
            "scales": {
                "r": {
                    "min": 0,
                    "max": 100,
                    "ticks": {"stepSize": 20, "color": "#666", "font": {"size": 11}},
                    "pointLabels": {"font": {"size": 13, "weight": "bold"}, "color": "#333"},
                    "grid": {"color": "rgba(0,0,0,0.08)"},
                    "angleLines": {"color": "rgba(0,0,0,0.15)"}
                }
            },
            "plugins": {
                "title": {"display": True, "text": f"Analisis Fundamental {ticker}", "font": {"size": 16, "weight": "bold"}, "color": "#333"},
                "legend": {"display": False},
            }
        }
    }

    url = "https://quickchart.io/chart?v=4&c=" + urllib.parse.quote(json.dumps(chart_config))
    return url


async def send_radar_chart(update: Update, ticker: str, radar_scores: dict, diagnosis: str = "") -> None:
    try:
        chart_url = generate_radar_chart_url(ticker, radar_scores)
        short_diag = diagnosis.split(chr(10))[0] if diagnosis else "Analisis Dokter"
        caption = f"📊 Radar Chart {ticker}\n{short_diag}"
        await update.message.reply_photo(photo=chart_url, caption=caption, parse_mode=None)
    except Exception as e:
        print(f"[Warning] Gagal kirim chart {ticker}: {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    m = TICKER_RE.match(text)
    if not m:
        await update.message.reply_text(
            "Format salah. Contoh:\n  `BBRI 5200` atau `BBCA`",
            parse_mode="Markdown",
        )
        return

    ticker = m.group(1).upper()
    buy_price = float(m.group(2)) if m.group(2) else None

    user = update.effective_user
    user_name = f"@{user.username}" if user.username else (user.first_name or "Anonymous")

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    t0 = time.time()

    try:
        company = await asyncio.to_thread(fetch_company, ticker)
    except Exception as e:
        await update.message.reply_text(f"Error fetch data {ticker}: {e}")
        return

    t1 = time.time()
    print(f"[TIMING] fetch_company: {t1 - t0:.2f}s")

    name = get_field(company, "name", "long_name", "company_name") or ticker
    sub_sector = get_field(company, "sub_sector")
    sector = get_field(company, "sector", "industry")

    status_msg = await update.message.reply_text(f"Sedang cek rekam medis **{name} ({ticker})**...", parse_mode="Markdown")

    async def _get_peers():
        tp0 = time.time()
        if sub_sector or sector:
            result = await asyncio.to_thread(fetch_peers, sub_sector, sector, ticker, 4)
        else:
            result = []
        print(f"[TIMING] fetch_peers: {time.time() - tp0:.2f}s (dapat {len(result)} peer)")
        return result

    async def _get_daily():
        td0 = time.time()
        result = await asyncio.to_thread(fetch_daily, ticker)
        print(f"[TIMING] fetch_daily: {time.time() - td0:.2f}s")
        return result

    peers, daily = await asyncio.gather(_get_peers(), _get_daily())

    t2 = time.time()
    print(f"[TIMING] peers+daily (paralel): {t2 - t1:.2f}s")

    prompt = build_prompt(ticker, buy_price if buy_price else 0, company, peers, daily, user_name)

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        tl0 = time.time()
        diagnosis = await call_llm(prompt, SYSTEM_PROMPT)
        print(f"[TIMING] call_llm: {time.time() - tl0:.2f}s")
    except Exception as e:
        diagnosis = f"Gagal menganalisis saham {ticker}: {e}"

    t3 = time.time()
    print(f"[TIMING] TOTAL: {t3 - t0:.2f}s")

    # Potong kalau terlalu panjang untuk Telegram (batas 4096 karakter)
    if len(diagnosis) > 4000:
        diagnosis = diagnosis[:4000] + "\n\n⚠️ (Pesan terlalu panjang, dipotong. Ketik /history untuk versi lengkap.)"

    try:
        await status_msg.delete()
    except:
        pass

    # Kirim foto chart
    radar_scores = calculate_radar_scores(company, diagnosis)
    await send_radar_chart(update, ticker, radar_scores, diagnosis)

    # Balas hasil ke Telegram secara langsung
    diagnosis += "\n\nDisclaimer: bukan rekomendasi investasi."
    await update.message.reply_text(diagnosis, parse_mode=None)

    # Simpan ke Supabase
    try:
        user_id = get_or_create_user(user.id, user.username or "", user.first_name or "")
        save_analysis(user_id, ticker, buy_price or 0, diagnosis)
        await update.message.reply_text("📊 Analisis tersimpan. Ketik `/history` untuk lihat riwayat.")
    except Exception as e:
        print(f"[Warning] Gagal simpan ke Supabase: {e}")

    # Airtable logging di-nonaktifkan — data masuk ke Supabase saja.
    # (Baris di bawah ini di-comment — tidak dieksekusi.)


async def watch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tambah ticker ke watchlist. Format: /watch TICKER [HARGA]"""
    telegram_id = update.effective_user.id
    user = update.effective_user
    # Convert telegram_id → user_id internal dulu
    user_id = get_or_create_user(telegram_id, user.username or "", user.first_name or "")

    args = context.args

    if not args:
        await update.message.reply_text(
            "Format: `/watch TICKER [HARGA]`\n"
            "Contoh: `/watch BBRI 5200` atau `/watch BBCA`",
            parse_mode="Markdown",
        )
        return

    ticker = args[0].upper()

    # Parse buy_price jika ada
    buy_price = None
    if len(args) > 1:
        try:
            buy_price = float(args[1])
        except ValueError:
            pass  # Diabaikan, ticker tetap ditambahkan

    # Cek kapasitas maksimal 5
    count = count_user_watchlist(user_id)
    if count >= 5:
        await update.message.reply_text(
            f"Watchlist kamu penuh ({count}/5 ticker).\n"
            "Hapus salah satu pakai `/unwatch TICKER` dulu."
        )
        return

    # Cek duplikat (manual, sebelum insert)
    watchlist = get_user_watchlist(user_id)
    for entry in watchlist:
        if entry["ticker"] == ticker:
            price_info = f" (beli: {entry['buy_price']:,.0f})" if entry.get("buy_price") else ""
            await update.message.reply_text(
                f"`{ticker}` sudah ada di watchlist kamu.{price_info}",
                parse_mode="Markdown",
            )
            return

    # Insert
    try:
        add_watchlist_entry(user_id, ticker, buy_price)
        price_str = f" di harga {buy_price:,.0f}" if buy_price else ""
        await update.message.reply_text(
            f"`{ticker}` berhasil ditambahkan ke watchlist{price_str}.",
            parse_mode="Markdown",
        )
    except Exception as e:
        print(f"[Warning] Gagal watch {ticker}: {e}")
        await update.message.reply_text("Terjadi kesalahan, coba lagi nanti.")


async def unwatch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hapus ticker dari watchlist. Format: /unwatch TICKER"""
    telegram_id = update.effective_user.id
    user = update.effective_user
    # Convert telegram_id → user_id internal dulu
    user_id = get_or_create_user(telegram_id, user.username or "", user.first_name or "")

    args = context.args

    if not args:
        await update.message.reply_text(
            "Format: `/unwatch TICKER`\n"
            "Contoh: `/unwatch BBRI`",
            parse_mode="Markdown",
        )
        return

    ticker = args[0].upper()

    try:
        removed = remove_watchlist_entry(user_id, ticker)
        if removed:
            await update.message.reply_text(
                f"`{ticker}` dihapus dari watchlist.",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                f"`{ticker}` tidak ditemukan di watchlist kamu.",
                parse_mode="Markdown",
            )
    except Exception as e:
        print(f"[Warning] Gagal unwatch {ticker}: {e}")
        await update.message.reply_text("Terjadi kesalahan, coba lagi nanti.")


async def mywatchlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tampilkan watchlist user. Format: /mywatchlist"""
    telegram_id = update.effective_user.id
    user = update.effective_user
    # Convert telegram_id → user_id internal dulu
    user_id = get_or_create_user(telegram_id, user.username or "", user.first_name or "")

    watchlist = get_user_watchlist(user_id)

    if not watchlist:
        await update.message.reply_text(
            "Watchlist kamu kosong.\n"
            "Tambah ticker pakai `/watch TICKER [HARGA]`.",
        )
        return

    lines = ["*Watchlist kamu:*", ""]
    for entry in watchlist:
        ticker = entry["ticker"]
        buy_price = entry.get("buy_price")
        price_str = f" (beli: {buy_price:,.0f})" if buy_price else ""
        lines.append(f"• `{ticker}`{price_str}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


def check_watchlist_changes(last_snapshot: dict, current_price, pbv, pl_pct) -> tuple:
    """
    Bandingkan data baru vs snapshot lama, tentuin apa perlu notifikasi.
    Return: (should_notify: bool, reason: str)
    Fungsi murni — gak nyentuh API/DB/Telegram sama sekali, gampang ditest.
    """
    if not last_snapshot:
        return False, ""  # pertama kali cek, belum ada pembanding

    old_pbv = last_snapshot.get("pbv")
    old_pl = last_snapshot.get("pl_pct")

    # Cek PBV berubah > 20%
    if old_pbv is not None and pbv is not None and old_pbv != 0:
        pbv_change_pct = abs(pbv - old_pbv) / abs(old_pbv) * 100
        if pbv_change_pct > 20:
            direction = "naik" if pbv > old_pbv else "turun"
            return True, f"PBV {direction} {pbv_change_pct:.1f}% (dari {old_pbv:.2f}x ke {pbv:.2f}x)"

    # Cek P/L positif↔️negatif
    if old_pl is not None and pl_pct is not None:
        old_sign = 1 if old_pl >= 0 else -1
        new_sign = 1 if pl_pct >= 0 else -1
        if old_sign != new_sign:
            return True, f"Status P/L berubah: dari {old_pl:+.2f}% ke {pl_pct:+.2f}%"

    return False, ""


async def run_daily_watchlist_check(context: ContextTypes.DEFAULT_TYPE):
    """Scheduled job: cek semua entri watchlist 1x sehari."""
    print("[Scheduler] Memulai pengecekan watchlist harian...")
    try:
        entries = get_all_watchlist_entries()
        print(f"[Scheduler] Ditemukan {len(entries)} entri watchlist")
        for entry in entries:
            try:
                user_id = entry["user_id"]
                ticker = entry["ticker"]
                buy_price = entry.get("buy_price")
                last_snapshot = entry.get("last_snapshot")
                entry_id = entry["id"]
                company = await asyncio.to_thread(fetch_company, ticker)
                daily = await asyncio.to_thread(fetch_daily, ticker)
                current_price = None
                if daily and isinstance(daily, list) and len(daily) > 0:
                    last_daily = daily[-1]
                    if isinstance(last_daily, dict):
                        current_price = last_daily.get("close")
                pbv = get_field(company, "pb_mrq", "pb", "pbv", "price_to_book", "pbvRatio", "pb_ratio")
                if pbv is None:
                    hist_val = company.get("valuation", {}).get("historical_valuation", [])
                    if hist_val:
                        pbv = hist_val[-1].get("pb")
                pl_pct = None
                if current_price is not None and buy_price and buy_price > 0:
                    pl_pct = (current_price - buy_price) / buy_price * 100
                should_notify = False
                notification_reason = ""
                notification_message = ""
                if last_snapshot:
                    old_pbv = last_snapshot.get("pbv")
                    old_pl = last_snapshot.get("pl_pct")
                    if old_pbv is not None and pbv is not None and old_pbv != 0:
                        pbv_change_pct = abs(pbv - old_pbv) / abs(old_pbv) * 100
                        if pbv_change_pct > 20:
                            should_notify = True
                            direction = "naik" if pbv > old_pbv else "turun"
                            notification_reason = f"PBV {direction} {pbv_change_pct:.1f}% (dari {old_pbv:.2f}x ke {pbv:.2f}x)"
                    if not should_notify and old_pl is not None and pl_pct is not None:
                        old_sign = 1 if old_pl >= 0 else -1
                        new_sign = 1 if pl_pct >= 0 else -1
                        if old_sign != new_sign:
                            should_notify = True
                            notification_reason = f"Status P/L berubah: dari {old_pl:+.2f}% ke {pl_pct:+.2f}%"
                    if should_notify:
                        name = get_field(company, "name", "long_name", "company_name") or ticker
                        price_str = f"Rp {current_price:,.0f}" if current_price else "N/A"
                        pl_str = f"{pl_pct:+.2f}%" if pl_pct is not None else "N/A"
                        pbv_str = f"{pbv:.2f}x" if pbv else "N/A"
                        notification_message = f"📊 *Update Watchlist: {ticker}*\n\nNama: {name}\nHarga terkini: {price_str}\nP/L: {pl_str}\nPBV: {pbv_str}\n\n⚠️ {notification_reason}"
                if should_notify:
                    telegram_id = get_telegram_id_by_user_id(user_id)
                    if telegram_id:
                        await context.bot.send_message(chat_id=telegram_id, text=notification_message, parse_mode="Markdown")
                        print(f"[Scheduler] Notifikasi dikirim ke user {telegram_id} untuk {ticker}")
                new_snapshot = {"current_price": current_price, "pbv": pbv, "pl_pct": pl_pct, "updated_at": datetime.now(ZoneInfo("Asia/Jakarta")).isoformat()}
                update_watchlist_snapshot(entry_id, new_snapshot)
                print(f"[Scheduler] {ticker}: snapshot updated (PBV={pbv}, P/L={pl_pct})")
            except Exception as e:
                print(f"[Scheduler] Error processing {entry.get('ticker', '?')}: {e}")
                continue
        print("[Scheduler] Pengecekan watchlist selesai")
    except Exception as e:
        print(f"[Scheduler] Error fatal: {e}")


async def test_scheduler_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command testing manual — panggil scheduler langsung tanpa nunggu jadwal."""
    ADMIN_TELEGRAM_ID = 5032965843
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        await update.message.reply_text("Command ini gak tersedia.")
        return
    await update.message.reply_text("Menjalankan pengecekan watchlist manual...")
    await run_daily_watchlist_check(context)
    await update.message.reply_text("Selesai. Cek log terminal untuk detail.")


async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    records = get_user_analyses(telegram_id)

    if not records:
        await update.message.reply_text("📭 Belum ada analisis. Kirim ticker dulu!")
        return

    text = "📋 Riwayat analisis:\n\n"
    for r in records[:10]:
        date = r["created_at"][:10]
        diag = r["diagnosis"]
        # Ambil cuma sampai sebelum [KONSTRUKSI METRIK] biar gak kepotong di tengah kalimat
        cutoff_marker = "[KONSTRUKSI METRIK]"
        if cutoff_marker in diag:
            diag = diag.split(cutoff_marker)[0].strip() + "\n_(selengkapnya: kirim ulang ticker ini)_"
        elif len(diag) > 300:
            diag = diag[:300].rsplit(" ", 1)[0] + "..."
        text += f"  {date} | {r['ticker']} | {diag}\n\n"

    if len(text) > 4000:
        text = text[:4000] + "\n\n⚠️ (Lebih banyak tersedia di /history selanjutnya)"

    await update.message.reply_text(text, parse_mode=None)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "**Nyangkut Doctor** - klinik saham fundamental.\n\n"
        "Kirim format: `KODE_SAHAM(TICKER) HARGA_BELI`\n"
        "Contoh: `BBRI 5200` atau `BBCA`\n\n"
        "⚠️ Bot ini alat bantu analisis & edukasi, bukan nasihat/rekomendasi investasi. "
        "Keputusan investasi sepenuhnya tanggung jawab pengguna.",
        parse_mode="Markdown",
    )

SYSTEM_PROMPT = """Kamu adalah dokter keuangan saham Indonesia.
Bahasa: santai tapi akurat, pakai bahasa Indonesia sehari-hari.
Framing: investor ritel yang beli di harga X sekarang floating loss/profit Y%.

LABEL:
- Sehat         : Fundamental kuat (EPS tumbuh/positif, arus kas baik, harga profit), tak ada sinyal bahaya.
- Sehat (catatan) : Sehat, tapi ada catatan penting (misal valuasi mahal vs sektor, atau ada data yang hilang). Kasih tau apa catatannya.
- Waspada       : Ada tanda-tanda risiko tapi belum kritis; valuasi mulai mahal, EPS growth melambat, revenue madep.
- Kritis        : Fundamental rusak: laba minus, arus kas merah, DER ekstrem, big loss.
- Data terbatas: Ada celah data besar (laba bersih null dan EPS null, atau rerata sektor nggak bisa dihitung) sehingga tak bisa confident.

RULES:
1. Data yang tersedia hanya yang dikirim di prompt. Jangan minta data yang tidak ada.
2. Baca blok [FLAGGED ISSUES] dengan seksama — itu adalah hal yang WAJIB disorot di Alasan Singkat dan Resep Dokter.
3. Jika ada FLAGGED ISSUES, diagnosa BOLEH pakai label "Sehat (catatan)" — bukan harus turun ke Waspada/Kritis secara otomatis, tapi harus sebutkan catatannya. JANGAN pakai label "Sehat" polos kalau ada FLAGGED ISSUES.
4. [VALUASI HISTORIS]: Bandingkan PBV saat ini dengan "Rerata PBV Historis (Sendiri)".
5. [FITUR SUBSTITUSI]: Jika valuasi saham MAHAL, WAJIB sarankan substitusi ke emiten rival yang PBV-nya lebih murah (lihat daftar "Kandidat substitusi termurah" jika ada).
6. Format jawaban HARUS konsisten sesuai template (Diagnosa, Alasan, Konstruksi/Tabel, Resep Dokter, Catatan).
7. JANGAN tambahkan catatan, pernyataan, atau klaim yang tidak didukung oleh data yang diberikan. Catatan hanya boleh berasal dari flag yang ada atau penjelasan DER khusus bank.
8. DER yang diberikan di data adalah rasio utang berbunga terhadap ekuitas, BUKAN total liabilitas. Untuk bank, DER ini akan selalu terlihat kecil karena simpanan nasabah tidak dihitung sebagai utang di sini — jangan menyebut DER bank "tinggi" berdasar angka ini.
"""

def main():
    if not TELEGRAM_BOT_TOKEN or not SECTORS_API_KEY:
        print("Error: TELEGRAM_BOT_TOKEN atau SECTORS_API_KEY belum diset di .env")
        return

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .get_updates_read_timeout(30)
        .build()
    )
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("watch", watch_cmd))
    app.add_handler(CommandHandler("unwatch", unwatch_cmd))
    app.add_handler(CommandHandler("mywatchlist", mywatchlist_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CommandHandler("history", history_cmd))
    app.add_handler(CommandHandler("testscheduler", test_scheduler_cmd))

    # Setup scheduler harian via JobQueue — jam 09:00 WIB setiap hari
    app.job_queue.run_daily(
        run_daily_watchlist_check,
        time=dt_time(hour=9, minute=0, tzinfo=ZoneInfo("Asia/Jakarta"))
    )
    print("[Scheduler] Watchlist scheduler aktif (jalan 1x/hari jam 09:00 WIB)")

    print("Nyangkut Doctor bot siap. Tekan Ctrl-C untuk menghentikan.")
    app.run_polling()

if __name__ == "__main__":
    main()
