# Context: Nyangkut Doctor

> Baca ini tiap sesi baru biar nggak salah asumsi soal progress.

## Status: "SELESAI 100%" — fokus sekarang: VIDEO + SUBMISSION (bukan kode baru)

### Sudah selesai & teruji ✅
- Bot dasar: analisis fundamental per ticker (fetch_company, fetch_peers, fetch_daily) via Sectors API
- Radar chart via QuickChart (competitive_score: pakai max(10, ...))
- History via Supabase (tabel: users, analyses)
- Retry logic sectors_get() — INSUFFICIENT_CREDITS langsung fail, selainnya retry 3x exponential backoff (2s/4s/8s). Lolos unit test mock.
- Disclaimer di start_cmd dan handle_message (compliance hackathon)
- Tabel watchlist Supabase (kolom: id, user_id, ticker, buy_price, last_snapshot, created_at) — UNIQUE(user_id, ticker) aktif
- Command /watch, /unwatch, /mywatchlist — ada di main.py, diregistrasi, di-test manual (duplikat, limit 5, not found) — SEMUA LOLOS
- Scheduler run_daily_watchlist_check pakai JobQueue bawaan python-telegram-bot (BUKAN APScheduler manual)
- test_scheduler_cmd (/testscheduler) — dibatasi ADMIN_TELEGRAM_ID, ada di main.py

### Sudah selesai & teruji ✅
- Notifikasi watchlist end-to-end — logic try/except per-ticker sudah robust, tapi belum full-test karena kredit Sectors API belum tersambung (sudah lapor Slack #support, nunggu balasan)

### Catatan arsitektur (JANGAN diubah tanpa alasan kuat) ⚠️
- user_id di watchlist/analyses: SELALU pakai users.id internal, BUKAN telegram_id langsung. Handler HARUS panggil get_or_create_user() dulu sebelum insert.
- Semua akses supabase.table(...) HARUS lewat fungsi di supabase_helper.py, TIDAK BOLEH langsung di main.py
- Python yang dipakai: Python global 3.12 (C:\Users\Ilhamf\AppData\Local\Programs\Python\Python312\python.exe) — job_queue sudah aktif, TIDAK PERLU install apa pun
- fetch_company/fetch_daily itu fungsi blocking (requests), harus dipanggil lewat asyncio.to_thread() kalau dipakai di fungsi async
- Scheduler jalan 1x sehari jam 09:00 WIB (desain sengaja, bukan keterbatasan — data fundamental tidak berubah secepat itu, dan ini hemat kredit API)

### Cara kerja yang WAJIB diikuti
- SEBELUM bilang "sudah selesai/sudah ditulis", WAJIB verifikasi dengan search langsung di file (misal cari nama fungsi persis) — jangan cuma berdasarkan ingatan/asumsi dari respons sebelumnya.
- Kalau ada keraguan soal status project, cek isi file dulu, JANGAN menebak atau menawarkan alternatif arsitektur yang sudah pernah diputuskan (contoh: pernah ada saran mundur ke in-memory storage padahal sudah pakai Supabase — JANGAN ulangi ini).
- Kalau baru saja menulis kode ke file, verifikasi ulang dengan search sebelum melapor "sudah masuk" — jangan asumsikan patch berhasil hanya karena instruksinya sudah diberikan.

### Folder & file penting
- main.py — entry point bot
- supabase_helper.py — semua akses DB harus lewat sini
- .env — konfigurasi (token, API key, Supabase URL/key, LLM URL)

### Yang TIDAK perlu dikerjakan lagi untuk submission ini
- Fitur baru apa pun di luar yang sudah ada. Fokus: video + submission.
