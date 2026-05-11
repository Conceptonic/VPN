Разработал и запустил с нуля коммерческий VPN-сервис с автоматизированной продажей подписок через Telegram.
Технологии и инструменты:
Python, python-telegram-bot, PostgreSQL, psycopg2, aiohttp, asyncio, Xray-core (VLESS Reality), 3X-UI, nginx (stream + http), Cloudflare WARP, WireGuard, Linux (Ubuntu), systemd, bash, Let's Encrypt, certbot

Что реализовано:

Telegram-бот для продажи подписок с ручным подтверждением оплаты через СБП
Интеграция с 3X-UI API для автоматического создания VPN-аккаунтов
Система подписок с тарифами, пробным периодом, реферальной программой
Страница подписки с автоматическим добавлением в Happ через deep link
Автоматическая рассылка routing-профиля клиентам
Мониторинг сервера (healthcheck, heartbeat, алерты в Telegram)
Автобэкап БД в Telegram
Prometheus-экспортер метрик для 3X-UI

Инфраструктура:

VLESS Reality на порту 443 с nginx stream-роутингом
Split routing: российские сайты напрямую, Google через Cloudflare WARP
Резервные inbound на нескольких портах с разными SNI
BBR congestion control, TLS-фрагментация
Поддомен для страниц подписок

Чему научился:

Работа с асинхронным Python (asyncio, python-telegram-bot)
Проектирование PostgreSQL схемы с connection pool
Настройка production Linux-сервера: nginx, systemd, SSL, firewall
Понимание протоколов обфускации трафика (TLS fingerprinting, Reality, XTLS-Vision)
Работа с xray/v2ray API и конфигурацией
Построение отказоустойчивой системы с мониторингом и автовосстановлением
