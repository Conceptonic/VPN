#!/usr/bin/env python3

import sys
import requests
import time

from dotenv import load_dotenv
load_dotenv("/opt/vpn_bot/.env")

sys.path.insert(0, "/opt/vpn_bot")
import database as db
import xui_api as xui
import config

BOT_TOKEN = config.BOT_TOKEN
ADMIN_ID  = config.ADMIN_ID

TEST_MODE  = True   # ← True = только тебе, False = всем
TEST_TG_ID = ADMIN_ID


def send_message(tg_id: int, text: str) -> bool:
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": tg_id, "text": text, "parse_mode": "HTML"},
            timeout=10
        )
        return resp.json().get("ok", False)
    except Exception as e:
        print(f"  Ошибка отправки tg_id={tg_id}: {e}")
        return False


def update_config_in_db(sub_id: int, new_link: str) -> None:
    with db._conn() as conn:
        db._execute(conn,
            "UPDATE subscriptions SET config_link = %s WHERE id = %s",
            (new_link, sub_id)
        )


def main():
    print("=== Рассылка обновлённых конфигов ===\n")

    db.init_db()

    if not xui.login():
        print("ОШИБКА: не удалось войти в 3x-ui")
        sys.exit(1)
    print("✅ Вошли в 3x-ui\n")

    subs = db.get_all_subscriptions(limit=100, offset=0)
    if not subs:
        print("Активных подписок не найдено.")
        return

    if TEST_MODE:
        subs = [s for s in subs if s["tg_id"] == TEST_TG_ID]
        if not subs:
            print(f"🧪 ТЕСТ: подписка для tg_id={TEST_TG_ID} не найдена")
            return
        print(f"🧪 ТЕСТ — обрабатываю только себя (tg_id={TEST_TG_ID})\n")
    else:
        print(f"Найдено активных подписок: {len(subs)}\n")

    ok_count = 0
    fail_count = 0

    for sub in subs:
        tg_id     = sub["tg_id"]
        client_id = sub["xui_client_id"]
        email     = sub["xui_email"]
        sub_id    = sub["id"]
        sub_link  = sub.get("sub_link", "")
        name      = sub.get("full_name") or f"tg_id={tg_id}"

        print(f"Обрабатываю: {name} (tg_id={tg_id})")

        try:
            # Обновляем config_link в БД (с правильным flow)
            new_link = xui.get_client_link(client_id, email)
            if "Ошибка" not in new_link:
                update_config_in_db(sub_id, new_link)

            # Определяем что слать — sub_link или прямой конфиг
            link_to_send = sub_link if sub_link else new_link

            if sub_link:
                # Шлём sub_link — клиент получит кнопку автообновления
                msg1 = (
                    f"🔄 <b>Сервер обновлён!</b>\n\n"
                    f"Нажми кнопку обновления в приложении (🔄) — "
                    f"конфиг подтянется автоматически.\n\n"
                    f"Если не обновилось — добавь подписку заново:\n"
                    f"<code>{sub_link}</code>"
                )
                send_message(tg_id, msg1)
            else:
                # Нет sub_link — шлём прямой конфиг
                msg1 = (
                    f"🔄 <b>Твой конфиг обновлён!</b>\n\n"
                    f"Замени старое подключение на новое:\n\n"
                    f"📱 Удали старое → нажми <b>+</b> → "
                    f"<b>Import from clipboard</b> → вставь ссылку ниже"
                )
                send_message(tg_id, msg1)
                time.sleep(0.3)
                send_message(tg_id, f"<code>{new_link}</code>")

            print(f"  ✅ Уведомление отправлено ({'sub_link' if sub_link else 'config_link'})")
            ok_count += 1

        except Exception as e:
            print(f"  ❌ Ошибка: {e}")
            fail_count += 1

        time.sleep(0.5)

    print(f"\n=== Готово ===")
    print(f"✅ Обновлено: {ok_count}")
    print(f"❌ Ошибок: {fail_count}")

    if not TEST_MODE:
        send_message(
            ADMIN_ID,
            f"🔄 <b>Рассылка завершена</b>\n\n"
            f"✅ Обновлено: {ok_count}\n"
            f"❌ Ошибок: {fail_count}"
        )


if __name__ == "__main__":
    main()
