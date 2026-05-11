#!/bin/bash
# Проверяет доступность 3x-ui панели и inbound.
# Если панель недоступна — шлёт алерт в Telegram.
# Запускать через cron каждые 10 минут:
#   */10 * * * * /opt/vpn_bot/monitor_xui.sh >> /opt/vpn_bot/backups/monitor.log 2>&1

ENV_FILE="/opt/vpn_bot/.env"
STATE_FILE="/opt/vpn_bot/xui_monitor_state"  # не /tmp — выживает после перезагрузки

# Читаем .env
if [ -f "$ENV_FILE" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        [[ "$line" =~ ^#.*$ || -z "$line" || "$line" != *"="* ]] && continue
        key="${line%%=*}"; value="${line#*=}"
        [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] || continue
        export "$key=$value"
    done < "$ENV_FILE"
fi

XUI_URL="https://127.0.0.1:${XUI_PORT}${XUI_BASE_PATH}"

send_alert() {
    local msg="$1"
    if [ -n "${BOT_TOKEN:-}" ] && [ -n "${ADMIN_ID:-}" ]; then
        curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
            -d "chat_id=${ADMIN_ID}&text=${msg}&parse_mode=HTML" > /dev/null
    fi
}

get_last_state() {
    [ -f "$STATE_FILE" ] && cat "$STATE_FILE" || echo "ok"
}

set_state() {
    echo "$1" > "$STATE_FILE"
}

# Проверяем доступность панели (логин)
HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" \
    --max-time 10 \
    -X POST "${XUI_URL}/login" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -H "Host: m8vpn.ru" \
    -d "username=${XUI_LOGIN}&password=${XUI_PASSWORD}")

LAST_STATE=$(get_last_state)

if [ "$HTTP_CODE" = "200" ]; then
    echo "[$(date)] 3x-ui OK (HTTP $HTTP_CODE)"
    # Если до этого был down — шлём восстановление
    if [ "$LAST_STATE" = "down" ]; then
        send_alert "✅ <b>3x-ui панель восстановлена</b>"
        set_state "ok"
    fi
else
    echo "[$(date)] 3x-ui НЕДОСТУПНА (HTTP $HTTP_CODE)"
    # Шлём алерт только если прошлый статус был ok (избегаем спама)
    if [ "$LAST_STATE" = "ok" ]; then
        send_alert "🔴 <b>3x-ui панель недоступна!</b>%0A%0AHTTP код: ${HTTP_CODE}%0AURL: ${XUI_URL}"
        set_state "down"
    fi
fi
