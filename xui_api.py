import requests
import uuid
import json
import time
import config
from config import XUI_HOST, XUI_PORT, XUI_LOGIN, XUI_PASSWORD, XUI_INBOUND_ID, XUI_BASE_PATH
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = f"{XUI_HOST}:{XUI_PORT}{XUI_BASE_PATH}"
session = requests.Session()
session.verify = False
session.headers.update({"Host": "..."})

_session_valid = False  # флаг что сессия авторизована


def login() -> bool:
    global _session_valid
    resp = session.post(f"{BASE_URL}/login", data={
        "username": XUI_LOGIN,
        "password": XUI_PASSWORD,
    })
    ok = resp.json().get("success", False)
    _session_valid = ok
    return ok


def _ensure_logged_in() -> bool:
    """Использует кешированную сессию; логинится только если сессия протухла."""
    global _session_valid
    if _session_valid:
        return True
    return login()


def _api_get(path: str) -> dict:
    """GET с автоматическим re-login при 401/неуспехе."""
    global _session_valid
    resp = session.get(f"{BASE_URL}{path}")
    data = resp.json()
    if not data.get("success") and resp.status_code in (401, 403):
        _session_valid = False
        if login():
            resp = session.get(f"{BASE_URL}{path}")
            data = resp.json()
    return data


def _api_post(path: str, **kwargs) -> dict:
    """POST с автоматическим re-login при 401/неуспехе."""
    global _session_valid
    resp = session.post(f"{BASE_URL}{path}", **kwargs)
    data = resp.json()
    if not data.get("success") and resp.status_code in (401, 403):
        _session_valid = False
        if login():
            resp = session.post(f"{BASE_URL}{path}", **kwargs)
            data = resp.json()
    return data


def get_sub_link(sub_id: str) -> str:
    """Возвращает ссылку подписки для Happ.
    Порт и путь настраиваются в .env через XUI_SUB_PORT и XUI_SUB_PATH.
    Путь должен совпадать с настройкой в 3x-ui → Настройки → Подписка.
    """
    import os
    host     = os.getenv("XUI_DOMAIN") or XUI_HOST.replace("http://", "").replace("https://", "")
    sub_port = int(os.getenv("XUI_SUB_PORT", "2096"))
    sub_path = os.getenv("XUI_SUB_PATH", "/sub/")
    return f"https://{host}{sub_path}{sub_id}"


def add_client(name: str, days: int, traffic_gb: int = 0) -> dict:
    """
    Создаёт клиента в 3x-ui.
    Возвращает {"client_id": ..., "email": ..., "link": ..., "sub_link": ..., "sub_id": ...}
    """
    if not _ensure_logged_in():
        raise Exception("Не удалось войти в 3x-ui")

    client_id = str(uuid.uuid4())
    email = f"{name.lower().replace(' ', '_')}_{client_id[:6]}"
    traffic_bytes = traffic_gb * 1024 ** 3 if traffic_gb > 0 else 0
    expire_timestamp = int((time.time() + days * 86400) * 1000)

    sub_id = uuid.uuid4().hex[:16]

    client = {
        "id": client_id,
        "alterId": 0,
        "email": email,
        "limitIp": config.XUI_LIMIT_IP,
        "totalGB": traffic_bytes,
        "expiryTime": expire_timestamp,
        "enable": True,
        "tgId": "",
        "subId": sub_id,
        "flow": "xtls-rprx-vision",
    }

    data = _api_post("/panel/api/inbounds/addClient", json={
        "id": XUI_INBOUND_ID,
        "settings": json.dumps({"clients": [client]}),
    })

    if not data.get("success"):
        raise Exception(f"Ошибка создания клиента: {data.get('msg')}")

    link     = get_client_link(client_id, email)
    sub_link = get_sub_link(sub_id)
    return {"client_id": client_id, "email": email, "link": link, "sub_link": sub_link, "sub_id": sub_id}


def update_client_expiry(client_id: str, new_expire_ms: int) -> bool:
    """
    Обновляет дату истечения существующего клиента.
    new_expire_ms — unix timestamp в миллисекундах.
    """
    if not _ensure_logged_in():
        return False

    data = _api_get(f"/panel/api/inbounds/get/{XUI_INBOUND_ID}")
    if not data.get("success"):
        return False

    clients = json.loads(data["obj"].get("settings", "{}")).get("clients", [])
    client = next((c for c in clients if c["id"] == client_id), None)
    if not client:
        return False

    client["expiryTime"] = new_expire_ms

    result = _api_post(
        f"/panel/api/inbounds/updateClient/{client_id}",
        json={
            "id": XUI_INBOUND_ID,
            "settings": json.dumps({"clients": [client]}),
        }
    )
    return result.get("success", False)


def get_client_link(client_id: str, email: str) -> str:
    """Получает конфиг-ссылку для клиента из inbound"""
    data = _api_get(f"/panel/api/inbounds/get/{XUI_INBOUND_ID}")

    if not data.get("success"):
        return "Ошибка получения конфига"

    inbound = data["obj"]
    import os
    host = os.getenv("XUI_DOMAIN") or XUI_HOST.replace("http://", "").replace("https://", "")

    stream = json.loads(inbound.get("streamSettings", "{}"))
    reality = stream.get("realitySettings", {})
    public_key = reality.get("settings", {}).get("publicKey", "")
    server_name = reality.get("serverNames", ["google.com"])[0]
    short_id = reality.get("shortIds", [""])[0]
    fingerprint = reality.get("settings", {}).get("fingerprint", "chrome")

    port = inbound.get("port", 443)

    link = (
        f"vless://{client_id}@{host}:{port}"
        f"?type=tcp&security=reality"
        f"&pbk={public_key}"
        f"&fp={fingerprint}"
        f"&sni={server_name}"
        f"&sid={short_id}"
        f"&spx=%2F"
        f"#{email}"
    )
    return link


def delete_client(email: str) -> bool:
    """Удаляет клиента из inbound"""
    if not _ensure_logged_in():
        return False
    data = _api_post(
        f"/panel/api/inbounds/{XUI_INBOUND_ID}/delClient/{email}"
    )
    return data.get("success", False)