#!/usr/bin/env python3
"""Синхронизирует sub_link в БД с реальными subId из 3x-ui."""

import sys
import os
import json

sys.path.insert(0, '/opt/vpn_bot')
os.chdir('/opt/vpn_bot')

from dotenv import load_dotenv
load_dotenv('/opt/vpn_bot/.env')

import database as db
import xui_api as xui
from config import XUI_HOST, XUI_PORT, XUI_BASE_PATH, XUI_INBOUND_ID

db.init_db()

if not xui.login():
    print("ОШИБКА: не удалось войти в 3x-ui")
    sys.exit(1)

print("Вошли в 3x-ui")

# Получаем клиентов из 3x-ui
resp = xui.session.get(
    f"{XUI_HOST}:{XUI_PORT}{XUI_BASE_PATH}/panel/api/inbounds/get/{XUI_INBOUND_ID}"
)
data = resp.json()
if not data.get('success'):
    print(f"ОШИБКА: {data}")
    sys.exit(1)

clients = json.loads(data['obj']['settings'])['clients']
sub_map = {c['email']: c.get('subId', '') for c in clients}
print(f"Клиентов в 3x-ui: {len(clients)}")
for email, sub_id in sub_map.items():
    print(f"  {email}: {sub_id or '(нет subId)'}")

# Обновляем sub_link в БД
with db._conn() as conn:
    subs = db._fetchall(conn, "SELECT id, xui_email, sub_link FROM subscriptions WHERE status = 'active'")
    print(f"\nАктивных подписок в БД: {len(subs)}")
    updated = 0
    for s in subs:
        email = s['xui_email']
        real_sub_id = sub_map.get(email, '')
        if real_sub_id:
            new_link = f"https://m8vpn.ru/sub/{real_sub_id}"
            if s['sub_link'] != new_link:
                db._execute(conn, "UPDATE subscriptions SET sub_link = %s WHERE id = %s",
                            (new_link, s['id']))
                print(f"  ✅ {email}: {s['sub_link']} → {new_link}")
                updated += 1
            else:
                print(f"  ✓  {email}: уже актуально")
        else:
            print(f"  ⚠️  {email}: subId не найден в 3x-ui")

print(f"\nОбновлено: {updated}")
