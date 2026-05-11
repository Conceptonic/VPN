#!/bin/bash
# ─────────────────────────────────────────────
# Резервное копирование БД vpn_bot
# Запускается cron'ом раз в сутки
# Сохраняет 7 последних дампов локально
# Отправляет дамп в Telegram администратору
# ─────────────────────────────────────────────

set -euo pipefail

# ── Конфиг (читаем из .env) ──────────────────
ENV_FILE="/opt/vpn_bot/.env"
if [ -f "$ENV_FILE" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        # Пропускаем комментарии и пустые строки
        [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
        # Берём только строки с =
        [[ "$line" != *"="* ]] && continue
        key="${line%%=*}"
        value="${line#*=}"
        # Экспортируем только безопасные имена (только UPPER_CASE переменные)
        [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] || continue
        export "$key=$value"
    done < "$ENV_FILE"
fi

BOT_TOKEN="${BOT_TOKEN:-}"
ADMIN_ID="${ADMIN_ID:-}"
DATABASE_URL="${DATABASE_URL:-}"

BACKUP_DIR="/opt/vpn_bot/backups"
KEEP_DAYS=7
DATE=$(date +%Y-%m-%d_%H-%M)
FILENAME="vpn_bot_${DATE}.sql.gz"
FILEPATH="${BACKUP_DIR}/${FILENAME}"

# ── Проверки ─────────────────────────────────
if [ -z "$DATABASE_URL" ]; then
    echo "ОШИБКА: DATABASE_URL не задан"
    exit 1
fi

mkdir -p "$BACKUP_DIR"

# ── Создаём дамп ─────────────────────────────
echo "[$(date)] Начало бэкапа..."
pg_dump "$DATABASE_URL" | gzip > "$FILEPATH"
SIZE=$(du -sh "$FILEPATH" | cut -f1)
echo "[$(date)] Дамп создан: $FILEPATH ($SIZE)"

# ── Отправляем в Telegram ────────────────────
if [ -n "$BOT_TOKEN" ] && [ -n "$ADMIN_ID" ]; then
    USERS=$(psql "$DATABASE_URL" -t -c "SELECT COUNT(*) FROM users;" 2>/dev/null | tr -d ' ' || echo "?")
    SUBS=$(psql "$DATABASE_URL" -t -c "SELECT COUNT(*) FROM subscriptions WHERE status='active';" 2>/dev/null | tr -d ' ' || echo "?")
    CAPTION="🗄 Бэкап БД vpn_bot
📅 ${DATE}
💾 Размер: ${SIZE}
👥 Пользователей: ${USERS}
📦 Активных подписок: ${SUBS}"

    curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendDocument" \
        -F "chat_id=${ADMIN_ID}" \
        -F "document=@${FILEPATH}" \
        -F "caption=${CAPTION}" \
        > /dev/null && echo "[$(date)] Бэкап отправлен в Telegram"
fi

# ── Удаляем старые дампы ─────────────────────
find "$BACKUP_DIR" -name "vpn_bot_*.sql.gz" -mtime +${KEEP_DAYS} -delete
REMAINING=$(ls "$BACKUP_DIR"/vpn_bot_*.sql.gz 2>/dev/null | wc -l)
echo "[$(date)] Бэкапов сохранено: $REMAINING"

echo "[$(date)] Готово ✓"