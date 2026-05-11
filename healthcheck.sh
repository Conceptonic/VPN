#!/bin/bash
# Проверяет что бот живой по файлу heartbeat.
# Если файл не обновлялся > 5 минут — перезапускает бота и шлёт алерт в Telegram.
# Запускать через cron каждые 5 минут:
#   */5 * * * * /opt/vpn_bot/healthcheck.sh >> /opt/vpn_bot/backups/healthcheck.log 2>&1

HEARTBEAT_FILE="/opt/vpn_bot/heartbeat"
MAX_AGE=300  # секунд (5 минут)
ENV_FILE="/opt/vpn_bot/.env"

# Читаем .env
if [ -f "$ENV_FILE" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        [[ "$line" =~ ^#.*$ || -z "$line" || "$line" != *"="* ]] && continue
        key="${line%%=*}"; value="${line#*=}"
        [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] || continue
        export "$key=$value"
    done < "$ENV_FILE"
fi

send_alert() {
    local msg="$1"
    if [ -n "${BOT_TOKEN:-}" ] && [ -n "${ADMIN_ID:-}" ]; then
        curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
            -d "chat_id=${ADMIN_ID}&text=${msg}&parse_mode=HTML" > /dev/null
    fi
}

# Файл не существует — бот ещё не запускался или лежит
if [ ! -f "$HEARTBEAT_FILE" ]; then
    echo "[$(date)] Heartbeat файл не найден — перезапускаем бота"
    send_alert "⚠️ <b>VPN Bot:</b> heartbeat файл не найден, перезапуск..."
    systemctl restart vpn_bot
    exit 0
fi

NOW=$(date +%s)
FILE_TIME=$(cat "$HEARTBEAT_FILE" | cut -d. -f1)
AGE=$((NOW - FILE_TIME))

if [ "$AGE" -gt "$MAX_AGE" ]; then
    echo "[$(date)] Heartbeat устарел на ${AGE}с — перезапускаем бота"
    send_alert "⚠️ <b>VPN Bot:</b> не отвечал ${AGE}с, выполняю перезапуск..."
    systemctl restart vpn_bot
    sleep 5
    if systemctl is-active --quiet vpn_bot; then
        send_alert "✅ <b>VPN Bot:</b> успешно перезапущен"
        echo "[$(date)] Бот перезапущен успешно"
    else
        send_alert "🔴 <b>VPN Bot:</b> перезапуск не помог! Требуется ручное вмешательство"
        echo "[$(date)] КРИТИЧНО: перезапуск не помог"
    fi
else
    echo "[$(date)] Бот живой (heartbeat ${AGE}с назад)"
fi
