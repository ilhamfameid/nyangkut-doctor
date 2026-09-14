import requests, json, time, sys, os

with open('.env') as f:
    for line in f:
        if line.startswith('TELEGRAM_BOT_TOKEN='):
            token = line.strip().split('=', 1)[1]
            break

base = f'https://api.telegram.org/bot{token}'
print('Token:', token[:10] + '...')

# 1) Ambil chat_id kita (dari update terakhir)
r = requests.post(base + '/getUpdates', json={}).json()
if not r.get('result'):
    print('ERROR: Tidak ada update. Bot harusnya pernah dikirim pesan sebelumnya.')
    sys.exit(1)
our_id = r['result'][-1]['message']['from']['id']
print('Chat ID kita:', our_id)

# 2) Kirim tes ke bot
test_msg = 'BBRI 5200'
r = requests.post(base + '/sendMessage', json={
    'chat_id': our_id,
    'text': test_msg,
    'parse_mode': 'Markdown',
}).json()

if not r.get('ok'):
    print('ERROR kirim:', r.get('error_code'), r.get('description'))
    sys.exit(1)
msg_id = r['result']['message_id']
print('Pesan dikirim, message_id:', msg_id)

# 3) Tunggu balasan bot (polling manual)
print('Menunggu balasan bot (max 30 detik)...')
time.sleep(2)

for i in range(15):
    time.sleep(2)
    r = requests.post(base + '/getUpdates', json={
        'offset': -1,  # ambil semua
        'timeout': 1,
    }).json()
    updates = r.get('result', [])
    for u in updates:
        if u.get('message', {}).get('chat', {}).get('id') == our_id:
            from_bot = u['message'].get('from', {}).get('is_bot', False)
            if from_bot:
                txt = u['message'].get('text', '')
                print('Balasan bot:', txt[:200] if txt else '(tanpa teks)')
                sys.exit(0)
    print(f'  [{i+1}/15] belum ada balasan...')

print('ERROR: Tidak ada balasan dari bot dalam 30 detik')
