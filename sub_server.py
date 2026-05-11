"""
Сервер страниц подписки.
"""

import os
import sys
from datetime import datetime
from aiohttp import web
from dotenv import load_dotenv

load_dotenv("/opt/vpn_bot/.env")
sys.path.insert(0, "/opt/vpn_bot")

import database as db

PORT = int(os.getenv("SUB_PAGE_PORT", "8085"))

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>M8 VPN — Подписка</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=Inter:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0a0a0f;
    --surface: #12121a;
    --surface2: #1a1a26;
    --border: rgba(255,255,255,0.07);
    --accent: #6c63ff;
    --accent2: #ff6584;
    --green: #22d3a0;
    --text: #e8e8f0;
    --muted: #6b6b80;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Inter', sans-serif;
    min-height: 100vh;
    overflow-x: hidden;
  }

  /* Background */
  body::before {
    content: '';
    position: fixed;
    inset: 0;
    background:
      radial-gradient(ellipse 80% 50% at 20% -10%, rgba(108,99,255,0.15) 0%, transparent 60%),
      radial-gradient(ellipse 60% 40% at 80% 110%, rgba(34,211,160,0.1) 0%, transparent 60%);
    pointer-events: none;
    z-index: 0;
  }

  .container {
    max-width: 520px;
    margin: 0 auto;
    padding: 32px 20px 60px;
    position: relative;
    z-index: 1;
  }

  /* Header */
  .header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 40px;
    animation: fadeDown 0.6s ease both;
  }
  .logo {
    width: 40px;
    height: 40px;
    background: linear-gradient(135deg, var(--accent), var(--green));
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 20px;
  }
  .brand {
    font-family: 'Syne', sans-serif;
    font-size: 22px;
    font-weight: 800;
    letter-spacing: -0.5px;
  }
  .brand span { color: var(--accent); }

  /* Status card */
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 24px;
    margin-bottom: 16px;
    animation: fadeUp 0.6s ease both;
  }
  .card:nth-child(2) { animation-delay: 0.1s; }
  .card:nth-child(3) { animation-delay: 0.2s; }
  .card:nth-child(4) { animation-delay: 0.3s; }

  .card-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 20px;
  }
  .status-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--green);
    box-shadow: 0 0 12px var(--green);
    animation: pulse 2s ease infinite;
  }
  .card-title {
    font-family: 'Syne', sans-serif;
    font-size: 18px;
    font-weight: 700;
  }
  .card-subtitle {
    font-size: 13px;
    color: var(--muted);
    margin-left: auto;
  }

  .grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }
  .grid-item {
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px 16px;
  }
  .grid-label {
    font-size: 11px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 6px;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .grid-value {
    font-size: 15px;
    font-weight: 500;
    color: var(--text);
  }
  .grid-value.green { color: var(--green); }
  .grid-value.accent { color: var(--accent); }

  /* Steps */
  .step {
    display: flex;
    gap: 16px;
    align-items: flex-start;
    padding: 16px 0;
    border-bottom: 1px solid var(--border);
  }
  .step:last-child { border-bottom: none; padding-bottom: 0; }
  .step-num {
    width: 32px;
    height: 32px;
    border-radius: 10px;
    background: linear-gradient(135deg, var(--accent), #8b5cf6);
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: 'Syne', sans-serif;
    font-weight: 700;
    font-size: 14px;
    flex-shrink: 0;
  }
  .step-check {
    width: 32px;
    height: 32px;
    border-radius: 10px;
    background: linear-gradient(135deg, var(--green), #059669);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 16px;
    flex-shrink: 0;
  }
  .step-content { flex: 1; }
  .step-title {
    font-weight: 500;
    font-size: 15px;
    margin-bottom: 4px;
  }
  .step-desc {
    font-size: 13px;
    color: var(--muted);
    line-height: 1.5;
  }

  /* Buttons */
  .btn-row {
    display: flex;
    gap: 10px;
    margin-top: 12px;
    flex-wrap: wrap;
  }
  .btn {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 10px 18px;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 500;
    text-decoration: none;
    cursor: pointer;
    border: none;
    transition: all 0.2s ease;
    font-family: 'Inter', sans-serif;
  }
  .btn-primary {
    background: linear-gradient(135deg, var(--accent), #8b5cf6);
    color: white;
  }
  .btn-primary:hover { transform: translateY(-1px); box-shadow: 0 8px 24px rgba(108,99,255,0.4); }
  .btn-secondary {
    background: var(--surface2);
    color: var(--text);
    border: 1px solid var(--border);
  }
  .btn-secondary:hover { border-color: var(--accent); color: var(--accent); }
  .btn-green {
    background: linear-gradient(135deg, var(--green), #059669);
    color: #0a0a0f;
    font-weight: 600;
    width: 100%;
    justify-content: center;
    padding: 14px;
    font-size: 15px;
    margin-top: 4px;
  }
  .btn-green:hover { transform: translateY(-1px); box-shadow: 0 8px 24px rgba(34,211,160,0.4); }

  /* Section title */
  .section-title {
    font-family: 'Syne', sans-serif;
    font-size: 13px;
    font-weight: 600;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin: 28px 0 12px;
    animation: fadeUp 0.6s ease both;
    animation-delay: 0.15s;
  }

  /* Footer */
  .footer {
    text-align: center;
    margin-top: 40px;
    font-size: 13px;
    color: var(--muted);
    animation: fadeUp 0.6s ease both;
    animation-delay: 0.4s;
  }
  .footer a { color: var(--accent); text-decoration: none; }

  @keyframes fadeUp {
    from { opacity: 0; transform: translateY(20px); }
    to { opacity: 1; transform: translateY(0); }
  }
  @keyframes fadeDown {
    from { opacity: 0; transform: translateY(-10px); }
    to { opacity: 1; transform: translateY(0); }
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.6; transform: scale(0.85); }
  }

  /* Not found */
  .not-found {
    text-align: center;
    padding: 80px 20px;
    animation: fadeUp 0.6s ease both;
  }
  .not-found .icon { font-size: 64px; margin-bottom: 20px; }
  .not-found h2 { font-family: 'Syne', sans-serif; font-size: 24px; margin-bottom: 10px; }
  .not-found p { color: var(--muted); margin-bottom: 24px; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="logo">🛡</div>
    <div class="brand">M8 <span>VPN</span></div>
  </div>

  {CONTENT}

  <div class="footer">
    Есть вопросы? <a href="https://t.me/{ADMIN_USERNAME}">@{ADMIN_USERNAME}</a>
    &nbsp;·&nbsp;
    <a href="https://t.me/{BOT_USERNAME}">Открыть бота</a>
  </div>
</div>
</body>
</html>"""

NOT_FOUND_CONTENT = """
<div class="not-found">
  <div class="icon">🔍</div>
  <h2>Подписка не найдена</h2>
  <p>Ссылка недействительна или подписка истекла.</p>
  <a href="https://t.me/{BOT_USERNAME}" class="btn btn-primary">Открыть бота</a>
</div>
"""

SUB_CONTENT = """
<div class="card">
  <div class="card-header">
    <div class="status-dot"></div>
    <div class="card-title">{SUB_NAME}</div>
    <div class="card-subtitle">{EXPIRES_LABEL}</div>
  </div>
  <div class="grid">
    <div class="grid-item">
      <div class="grid-label">📦 Тариф</div>
      <div class="grid-value accent">{TARIFF}</div>
    </div>
    <div class="grid-item">
      <div class="grid-label">✅ Статус</div>
      <div class="grid-value green">Активна</div>
    </div>
    <div class="grid-item">
      <div class="grid-label">📅 Истекает</div>
      <div class="grid-value">{EXPIRES_DATE}</div>
    </div>
    <div class="grid-item">
      <div class="grid-label">📡 Трафик</div>
      <div class="grid-value">Безлимит ∞</div>
    </div>
  </div>
</div>

<div class="section-title">Установка</div>

<div class="card">
  <div class="step">
    <div class="step-num">1</div>
    <div class="step-content">
      <div class="step-title">Установи приложение Happ</div>
      <div class="step-desc">Выбери версию для своего устройства</div>
      <div class="btn-row">
        <a href="https://apps.apple.com/app/happ-proxy-utility/id6504287215" class="btn btn-secondary">🍎 App Store</a>
        <a href="https://play.google.com/store/apps/details?id=com.happproxy" class="btn btn-secondary">🤖 Google Play</a>
      </div>
    </div>
  </div>
  <div class="step">
    <div class="step-num">2</div>
    <div class="step-content">
      <div class="step-title">Добавь подписку</div>
      <div class="step-desc">Нажми кнопку ниже — приложение откроется и подписка добавится автоматически</div>
      <a href="happ://add/{SUB_URL_DIRECT}" class="btn btn-green" id="addBtn">+ Добавить подписку</a>
      <script>
      document.getElementById('addBtn').addEventListener('click', function(e) {
        e.preventDefault();
        var url = '{SUB_URL_DIRECT}';
        // Пробуем открыть Happ через deep link
        window.location.href = 'happ://add/' + url;
        // Если через 2 секунды ничего не произошло — копируем в буфер
        setTimeout(function() {
          if (navigator.clipboard) {
            navigator.clipboard.writeText(url).then(function() {
              document.getElementById('addBtn').textContent = '✓ Ссылка скопирована — вставь в Happ';
            });
          }
        }, 2000);
      });
      </script>
    </div>
  </div>
  <div class="step">
    <div class="step-check">✓</div>
    <div class="step-content">
      <div class="step-title">Подключение и использование</div>
      <div class="step-desc">В главном разделе нажми большую кнопку включения. Выбери сервер <strong>Германия-M8 VPN</strong> из списка.</div>
    </div>
  </div>
</div>
"""


async def handle_sub_page(request: web.Request) -> web.Response:
    sub_id = request.match_info.get("sub_id", "")
    if not sub_id:
        return web.Response(text="Not found", status=404)

    user_agent = request.headers.get("User-Agent", "")
    admin_username = os.getenv("ADMIN_USERNAME", "conceptonic")
    bot_username = os.getenv("BOT_USERNAME", "m8vpn_bot")
    xui_sub_path = os.getenv("XUI_SUB_PATH", "/")
    sub_domain = os.getenv("XUI_DOMAIN", "sub.m8vpn.ru")

    # Ищем подписку по sub_id — быстрый поиск по индексу, fallback на LIKE
    try:
        sub = db.get_subscription_by_sub_id(sub_id)
    except Exception as e:
        sub = None

    # Если запрос от Happ или другого VPN клиента — редиректим на реальный URL подписки
    is_vpn_client = any(x in user_agent.lower() for x in [
        "happ", "v2ray", "clash", "sing-box", "streisand", "shadowrocket",
        "quantumult", "surge", "loon", "stash"
    ])

    if is_vpn_client:
        if not sub:
            return web.Response(text="", status=404)
        # Запрашиваем конфиг напрямую с 3x-ui и отдаём клиенту
        import requests as req
        import urllib3
        urllib3.disable_warnings()
        try:
            real_sub_url = f"https://127.0.0.1:2096{xui_sub_path}{sub_id}"
            resp = req.get(
                real_sub_url,
                headers={"Host": "sub.m8vpn.ru"},
                verify=False,
                timeout=10
            )
            return web.Response(
                body=resp.content,
                content_type="text/plain",
                headers={
                    "profile-update-interval": "1",
                    "profile-title": "M8 VPN",
                    "profile-web-page-url": f"https://{sub_domain}/{sub_id}",
                    "routing": f"happ://routing/onadd/{ROUTING_B64}",
                    "subscription-userinfo": "upload=0; download=0; total=0; expire=0",
                }
            )
        except Exception as e:
            return web.Response(text=f"Error: {e}", status=502)

    def render(content: str) -> str:
        html = HTML_TEMPLATE.replace("{CONTENT}", content)
        html = html.replace("{ADMIN_USERNAME}", admin_username)
        html = html.replace("{BOT_USERNAME}", bot_username)
        return html

    if not sub:
        content = NOT_FOUND_CONTENT.replace("{BOT_USERNAME}", bot_username)
        return web.Response(text=render(content), content_type="text/html")

    expires = sub["expires_at"]
    if isinstance(expires, str):
        expires = datetime.strptime(expires[:19], "%Y-%m-%d %H:%M:%S")

    days_left = (expires - datetime.now()).days
    if days_left > 365:
        expires_label = "Истекает через год"
    elif days_left > 30:
        months = days_left // 30
        expires_label = f"Истекает через {months} мес."
    else:
        expires_label = f"Осталось {days_left} дн."

    import urllib.parse
    # Страница для браузера
    page_url = f"https://{sub_domain}/{sub_id}"
    # Реальный URL подписки для Happ
    real_sub_url = f"https://{sub_domain}/{sub_id}"
    sub_url_encoded = urllib.parse.quote(real_sub_url, safe="")

    tariff_key = sub.get("tariff_key", "")
    tariff_names = {
        "1m": "1 месяц", "3m": "3 месяца",
        "6m": "6 месяцев", "12m": "12 месяцев",
        "trial": "Пробный период",
    }
    tariff_name = tariff_names.get(tariff_key, tariff_key)
    sub_name = f"M8 VPN · {tariff_name}"

    content = (SUB_CONTENT
        .replace("{SUB_NAME}", sub_name)
        .replace("{EXPIRES_LABEL}", expires_label)
        .replace("{TARIFF}", tariff_name)
        .replace("{EXPIRES_DATE}", expires.strftime("%d.%m.%Y"))
        .replace("{SUB_URL_ENCODED}", sub_url_encoded)
        .replace("{SUB_URL_DIRECT}", page_url)
        .replace("{ROUTING_DEEPLINK}", ROUTING_DEEPLINK)
    )
    return web.Response(text=render(content), content_type="text/html")


import base64 as b64
import json as _json

ROUTING_JSON = {
    "Name": "M8 VPN Routing",
    "DomesticDNSType": "DoH",
    "RemoteDNSDomain": "https://8.8.8.8/dns-query",
    "DirectSites": [
        "geosite:private",
        "geosite:category-ru",
        "geosite:whitelist",
        "geosite:microsoft",
        "geosite:apple",
        "geosite:google-play",
        "geosite:epicgames",
        "geosite:riot",
        "geosite:escapefromtarkov",
        "geosite:steam",
        "geosite:origin",
        "geosite:twitch",
        "geosite:pinterest",
        "geosite:faceit"
    ],
    "DnsHosts": {
        "lknpd.nalog.ru": "213.24.64.181",
        "lkfl2.nalog.ru": "213.24.64.175"
    },
    "ProxyIp": [],
    "BlockIp": [],
    "GeositeUrl": "https://cdn.jsdelivr.net/gh/hydraponique/roscomvpn-geosite@202603251836/release/geosite.dat",
    "ProxySites": [
        "geosite:github",
        "geosite:twitch-ads",
        "geosite:youtube",
        "geosite:telegram",
        "domain:tribute.tg"
    ],
    "UseChunkFiles": True,
    "DomesticDNSDomain": "https://77.88.8.8/dns-query",
    "RemoteDNSType": "DoH",
    "DirectIp": [
        "geoip:private",
        "geoip:direct"
    ],
    "FakeDns": False,
    "GlobalProxy": True,
    "BlockSites": [
        "geosite:win-spy",
        "geosite:torrent"
    ],
    "DomesticDNSIp": "77.88.8.8",
    "DomainStrategy": "IPIfNonMatch",
    "RemoteDNSIp": "8.8.8.8",
    "RouteOrder": "block-proxy-direct",
    "GeoipUrl": "https://cdn.jsdelivr.net/gh/hydraponique/roscomvpn-geoip@202604090521/release/geoip.dat"
}

ROUTING_B64 = b64.b64encode(_json.dumps(ROUTING_JSON, ensure_ascii=False).encode()).decode()
ROUTING_DEEPLINK = f"happ://routing/add/{ROUTING_B64}"


async def handle_routing(request: web.Request) -> web.Response:
    """Редирект на deep link для добавления роутинга в Happ."""
    return web.Response(
        text=f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>M8 VPN Routing</title>
<script>window.location.href = '{ROUTING_DEEPLINK}';</script>
</head><body>
<p>Открывается Happ... <a href="{ROUTING_DEEPLINK}">Нажми сюда если не открылось</a></p>
</body></html>""",
        content_type="text/html"
    )


async def handle_healthz(request: web.Request) -> web.Response:
    return web.Response(text="OK")


async def handle_sub_link(request: web.Request) -> web.Response:
    """Обрабатывает /s/{sub_id} — ссылки подписки от бота."""
    # Переиспользуем тот же handler, просто меняем путь
    return await handle_sub_page(request)


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/sub/{sub_id}", handle_sub_page)
    app.router.add_get("/s/{sub_id}", handle_sub_link)
    app.router.add_get("/routing", handle_routing)
    app.router.add_get("/healthz", handle_healthz)
    app.router.add_get("/{sub_id}", handle_sub_page)
    return app


if __name__ == "__main__":
    db.init_db()
    print(f"Сервер страниц подписки запускается на порту {PORT}...")
    web.run_app(create_app(), host="127.0.0.1", port=PORT)