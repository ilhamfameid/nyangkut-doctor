import os
from supabase import create_client

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY"),
)


def get_or_create_user(telegram_id: int, username: str, full_name: str):
    """Cari user berdasarkan telegram_id. Kalau belum ada, buat baru."""
    response = supabase.table("users") \
        .select("id") \
        .eq("telegram_id", telegram_id) \
        .execute()

    if response.data:
        return response.data[0]["id"]

    response = supabase.table("users").insert({
        "telegram_id": telegram_id,
        "username": username,
        "full_name": full_name,
    }).execute()

    return response.data[0]["id"]


def save_analysis(user_id: int, ticker: str, buy_price: float, diagnosis: str):
    """Simpan hasil analisis ke tabel analyses."""
    diag_label = "N/A"
    resep_label = "N/A"
    for line in diagnosis.split("\n"):
        line = line.strip()
        if line.startswith("[DIAGNOSA]") or line.startswith("[DIAGNOSA]:"):
            diag_label = line.split(":", 1)[-1].strip()
        elif line.startswith("[RESEP DOKTER]") or line.startswith("[RESEP DOKTER]:"):
            resep_label = line.split(":", 1)[-1].strip()

    supabase.table("analyses").insert({
        "user_id": user_id,
        "ticker": ticker,
        "buy_price": buy_price,
        "diagnosis": diagnosis,
        "resep_dokter": resep_label,
    }).execute()


def get_user_analyses(telegram_id: int):
    """Ambil riwayat analisis user berdasarkan telegram_id."""
    user = supabase.table("users") \
        .select("id") \
        .eq("telegram_id", telegram_id) \
        .execute()

    if not user.data:
        return []

    user_id = user.data[0]["id"]

    response = supabase.table("analyses") \
        .select("*") \
        .eq("user_id", user_id) \
        .execute()

    # Sort manual di Python karena library Supabase Py tidak support order() yang konsisten
    result = response.data
    result.sort(key=lambda r: r["created_at"], reverse=True)
    return result[:20]


def count_user_watchlist(user_id: int) -> int:
    """Hitung jumlah entri watchlist untuk user tertentu (pakai user_id internal)."""
    result = supabase.table("watchlist") \
        .select("id") \
        .eq("user_id", user_id) \
        .execute()
    return len(result.data) if result.data else 0


def get_user_watchlist(user_id: int) -> list:
    """Dapatkan semua entri watchlist user, terurut dari yang paling baru."""
    result = supabase.table("watchlist") \
        .select("*") \
        .eq("user_id", user_id) \
        .execute()
    data = result.data if result.data else []
    # Sort manual karena library Supabase Py tidak support order() yang konsisten
    data.sort(key=lambda r: r["created_at"], reverse=True)
    return data


def add_watchlist_entry(user_id: int, ticker: str, buy_price: float = None) -> dict:
    """
    Tambah entri watchlist.
    Return dict entri yang berhasil ditambahkan.
    Raise exception dengan pesan ramah jika gagal (misal duplikat, koneksi error).
    """
    data = {
        "user_id": user_id,
        "ticker": ticker.upper(),
        "buy_price": buy_price,
    }
    try:
        result = supabase.table("watchlist") \
            .insert(data) \
            .execute()
        if not result.data:
            raise Exception("Gagal menambah entri watchlist (tidak ada response).")
        return result.data[0]
    except Exception as e:
        # Tangkep error duplikat (unique constraint) — cek kode error Postgres 23505
        err_str = str(e).lower()
        if "23505" in err_str or "duplicate" in err_str or "unique" in err_str:
            raise Exception(f"`{ticker}` sudah ada di watchlist.")
        # Error lain: wrap dengan pesan generik biar nggak bocor detail DB ke user
        raise Exception(f"Gagal menambah watchlist: {e}")


def remove_watchlist_entry(user_id: int, ticker: str) -> bool:
    """
    Hapus entri watchlist berdasarkan user_id dan ticker.
    Return True jika ada baris yang terhapus, False jika tidak ditemukan.
    """
    try:
        result = supabase.table("watchlist") \
            .delete() \
            .eq("user_id", user_id) \
            .eq("ticker", ticker.upper()) \
            .execute()
        # Kalau ada data yang kehapus, result.data akan berisi array (mungkin kosong kalau nggak ada yang cocok)
        return bool(result.data and len(result.data) > 0)
    except Exception as e:
        # Log internal untuk debugging, return False biar command handler kasih pesan ramah
        print(f"[Warning] Gagal hapus watchlist {ticker}: {e}")
        return False


def get_all_watchlist_entries() -> list:
    """Dapatkan semua entri watchlist dari semua user."""
    result = supabase.table("watchlist").select("*").execute()
    return result.data if result.data else []


def update_watchlist_snapshot(entry_id: int, snapshot: dict):
    """Update kolom last_snapshot untuk entri watchlist tertentu."""
    supabase.table("watchlist").update({"last_snapshot": snapshot}).eq("id", entry_id).execute()


def get_telegram_id_by_user_id(user_id: int):
    """Dapatkan telegram_id berdasarkan user_id internal."""
    result = supabase.table("users").select("telegram_id").eq("id", user_id).execute()
    return result.data[0]["telegram_id"] if result.data else None
