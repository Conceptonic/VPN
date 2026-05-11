#!/bin/bash
# Установка и запуск VPN бота

set -euo pipefail

VENV_DIR="/opt/vpn_bot/venv"
BOT_DIR="/opt/vpn_bot"

echo "=== Установка VPN бота ==="

# Проверяем наличие .env файла
if [ ! -f "${BOT_DIR}/.env" ]; then
    echo "ОШИБКА: файл .env не найден!"
    echo "Скопируй шаблон и заполни: cp .env.example .env"
    exit 1
fi

# Создаём venv если нет
if [ ! -d "$VENV_DIR" ]; then
    echo "Создаём виртуальное окружение..."
    python3 -m venv "$VENV_DIR"
fi

# Обновляем pip и устанавливаем зависимости
echo "Устанавливаем зависимости..."
"${VENV_DIR}/bin/pip" install --upgrade pip --quiet
"${VENV_DIR}/bin/pip" install -r "${BOT_DIR}/requirements.txt" --quiet

echo "=== Установка завершена ==="
echo "Запускаем бота..."
"${VENV_DIR}/bin/python3" "${BOT_DIR}/bot.py"