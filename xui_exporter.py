"""
Prometheus-экспортер для 3x-ui.
Экспортирует: онлайн-клиентов, трафик по каждому клиенту, статус inbound.
"""

import time
import json
import logging
import os
import requests
import urllib3
from dotenv import load_dotenv
from prometheus_client import (
    start_http_server,
    Gauge,
    Counter,
    Info,
    REGISTRY,
    PROCESS_COLLECTOR,
    PLATFORM_COLLECTOR,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Конфиг из .env ─────────────────────────────────────────────
XUI_HOST       = os.getenv("XUI_HOST", "")
XUI_PORT       = os.getenv("XUI_PORT", "443")
XUI_BASE_PATH  = os.getenv("XUI_BASE_PATH", "")
XUI_LOGIN      = os.getenv("XUI_LOGIN", "")
XUI_PASSWORD   = os.getenv("XUI_PASSWORD", "")
XUI_INBOUND_ID = int(os.getenv("XUI_INBOUND_ID", "1"))

EXPORTER_PORT     = int(os.getenv("EXPORTER_PORT", "9550"))
SCRAPE_INTERVAL   = int(os.getenv("SCRAPE_INTERVAL", "30"))  # секунд

BASE_URL = f"{XUI_HOST}:{XUI_PORT}{XUI_BASE_PATH}"

# ── Prometheus метрики ──────────────────────────────────────────

# Убираем стандартные метрики процесса (лишний шум)
REGISTRY.unregister(PROCESS_COLLECTOR)
REGISTRY.unregister(PLATFORM_COLLECTOR)

# Общие метрики inbound
xui_online_clients = Gauge(
    "xui_online_clients",
    "Количество активных VPN подключений прямо сейчас",
    ["inbound_id"],
)
xui_total_clients = Gauge(
    "xui_total_clients",
    "Всего клиентов в inbound (включая неактивных)",
    ["inbound_id"],
)
xui_inbound_up_bytes = Gauge(
    "xui_inbound_up_bytes_total",
    "Исходящий трафик inbound (байт)",
    ["inbound_id"],
)
xui_inbound_down_bytes = Gauge(
    "xui_inbound_down_bytes_total",
    "Входящий трафик inbound (байт)",
    ["inbound_id"],
)
xui_inbound_enabled = Gauge(
    "xui_inbound_enabled",
    "Статус inbound (1 = включён, 0 = выключен)",
    ["inbound_id"],
)

# Метрики по каждому клиенту
xui_client_up_bytes = Gauge(
    "xui_client_up_bytes_total",
    "Исходящий трафик клиента (байт)",
    ["email", "inbound_id"],
)
xui_client_down_bytes = Gauge(
    "xui_client_down_bytes_total",
    "Входящий трафик клиента (байт)",
    ["email", "inbound_id"],
)
xui_client_enabled = Gauge(
    "xui_client_enabled",
    "Включён ли клиент (1/0)",
    ["email", "inbound_id"],
)
xui_client_online = Gauge(
    "xui_client_online",
    "Онлайн ли клиент прямо сейчас (1/0)",
    ["email", "inbound_id"],
)
xui_client_expiry = Gauge(
    "xui_client_expiry_timestamp",
    "Unix timestamp истечения подписки клиента (0 = бессрочно)",
    ["email", "inbound_id"],
)

xui_scrape_success = Gauge(
    "xui_scrape_success",
    "Успешность последнего сбора метрик (1 = ОК, 0 = ошибка)",
)
xui_scrape_duration = Gauge(
    "xui_scrape_duration_seconds",
    "Время сбора метрик (секунд)",
)


# ── 3x-ui клиент ───────────────────────────────────────────────

session = requests.Session()
session.verify = False


def login() -> bool:
    try:
        resp = session.post(f"{BASE_URL}/login", data={
            "username": XUI_LOGIN,
            "password": XUI_PASSWORD,
        }, timeout=10)
        return resp.json().get("success", False)
    except Exception as e:
        logger.error(f"Ошибка логина в 3x-ui: {e}")
        return False


def get_online_emails() -> set[str]:
    """
    Возвращает set email'ов клиентов онлайн прямо сейчас.
    Некоторые версии 3x-ui возвращают пустое тело на /onlines —
    в этом случае возвращаем None чтобы использовать lastOnline fallback.
    """
    try:
        resp = session.post(f"{BASE_URL}/panel/api/inbounds/onlines", timeout=10)
        if not resp.text.strip():
            # Пустое тело — endpoint не поддерживается в этой версии 3x-ui
            return None
        data = resp.json()
        if data.get("success"):
            return set(data.get("obj", []) or [])
    except Exception as e:
        logger.warning(f"Не удалось получить список онлайн клиентов: {e}")
    return None


ONLINE_THRESHOLD_MS = 5 * 60 * 1000  # считаем онлайн если lastOnline < 5 минут назад


def is_online_by_last_seen(last_online_ms: int) -> bool:
    """Fallback: считаем клиента онлайн если он был активен < 5 мин назад."""
    if not last_online_ms or last_online_ms == 0:
        return False
    import time
    now_ms = int(time.time() * 1000)
    return (now_ms - last_online_ms) < ONLINE_THRESHOLD_MS


def get_inbounds() -> list:
    try:
        resp = session.get(f"{BASE_URL}/panel/api/inbounds/list", timeout=10)
        data = resp.json()
        if data.get("success"):
            return data.get("obj", [])
    except Exception as e:
        logger.error(f"Ошибка получения inbounds: {e}")
    return []


# ── Сбор метрик ────────────────────────────────────────────────

def collect_metrics() -> None:
    start = time.time()
    try:
        if not login():
            logger.error("Не удалось авторизоваться в 3x-ui")
            xui_scrape_success.set(0)
            return

        online_emails = get_online_emails()
        use_last_online_fallback = online_emails is None
        if use_last_online_fallback:
            logger.info("Используем lastOnline fallback (endpoint /onlines не поддерживается)")
            online_emails = set()

        inbounds = get_inbounds()

        for inbound in inbounds:
            iid = str(inbound["id"])

            # Метрики самого inbound
            xui_inbound_enabled.labels(inbound_id=iid).set(1 if inbound.get("enable") else 0)
            xui_inbound_up_bytes.labels(inbound_id=iid).set(inbound.get("up", 0))
            xui_inbound_down_bytes.labels(inbound_id=iid).set(inbound.get("down", 0))

            # Клиенты
            settings = json.loads(inbound.get("settings", "{}"))
            clients = settings.get("clients", [])
            xui_total_clients.labels(inbound_id=iid).set(len(clients))

            # clientStats — трафик и lastOnline по каждому клиенту
            client_stats = {
                s["email"]: s
                for s in (inbound.get("clientStats") or [])
            }

            online_count = 0
            for client in clients:
                email = client.get("email", "unknown")
                stats = client_stats.get(email, {})

                if use_last_online_fallback:
                    # Используем lastOnline из clientStats
                    is_online = is_online_by_last_seen(stats.get("lastOnline", 0))
                else:
                    is_online = email in online_emails

                if is_online:
                    online_count += 1

                xui_client_enabled.labels(email=email, inbound_id=iid).set(
                    1 if client.get("enable", True) else 0
                )
                xui_client_online.labels(email=email, inbound_id=iid).set(
                    1 if is_online else 0
                )
                expiry = client.get("expiryTime", 0)
                xui_client_expiry.labels(email=email, inbound_id=iid).set(
                    expiry // 1000 if expiry else 0  # ms → unix seconds
                )
                xui_client_up_bytes.labels(email=email, inbound_id=iid).set(
                    stats.get("up", 0)
                )
                xui_client_down_bytes.labels(email=email, inbound_id=iid).set(
                    stats.get("down", 0)
                )

            xui_online_clients.labels(inbound_id=iid).set(online_count)

        xui_scrape_success.set(1)
        logger.info(f"Метрики собраны. Онлайн: {online_count} клиентов.")

    except Exception as e:
        logger.error(f"Ошибка сбора метрик: {e}")
        xui_scrape_success.set(0)
    finally:
        xui_scrape_duration.set(time.time() - start)


# ── Main ───────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info(f"Запуск экспортера на порту {EXPORTER_PORT}...")
    start_http_server(EXPORTER_PORT)
    logger.info(f"Экспортер запущен: http://localhost:{EXPORTER_PORT}/metrics")

    while True:
        collect_metrics()
        time.sleep(SCRAPE_INTERVAL)